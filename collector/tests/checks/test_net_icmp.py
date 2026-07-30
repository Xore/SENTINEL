"""Tests for collector.checks.net_icmp — packet framing and the ICMP check."""

from __future__ import annotations

import asyncio
import socket
import struct
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from collector.checks.net_icmp import (
    ICMP_ECHO_REPLY,
    IcmpCheck,
    _build_echo_request,
    _checksum,
    _parse_echo_reply,
    _ping_once_blocking,
    ping,
    resolve_ipv4,
    target_identifier,
)
from collector.config import IcmpTarget, load_settings
from collector.utils import thread_pool
from collector.utils.thread_pool import run_in_thread


def _reply_packet(identifier: int, sequence: int, icmp_type: int = ICMP_ECHO_REPLY) -> bytes:
    """A minimal IPv4 datagram (20-byte header, no options) wrapping an ICMP
    echo reply — as `_ping_once_blocking` would receive from a real socket.
    """
    ip_header = bytes([0x45]) + b"\x00" * 19
    icmp_header = struct.pack("!BBHHH", icmp_type, 0, 0, identifier, sequence)
    return ip_header + icmp_header + b"payload"


def _addrinfo(address: str) -> list[tuple]:
    """One `getaddrinfo` answer tuple, shaped as the loop returns it."""
    return [(socket.AF_INET, socket.SOCK_RAW, 0, "", (address, 0))]


class _SocketModuleShim:
    """Stands in for `net_icmp`'s `socket` import with only `socket()` replaced.

    Async tests must not patch the real `socket.socket` class: the Windows
    `ProactorEventLoop` does `isinstance(conn, socket.socket)` while reading
    its own self-pipe, which raises once that name is a function. Swapping the
    module reference inside `net_icmp` keeps the substitution where the test
    needs it and leaves the loop's socket machinery alone.
    """

    def __init__(self, factory) -> None:
        self.socket = factory

    def __getattr__(self, name: str):
        return getattr(socket, name)


@pytest.fixture
def sized_cpu_pool():
    """Pin the shared CPU pool to a known worker count for one test.

    Pool size is process-global state, so the fixture restores the
    unconfigured default afterwards — otherwise a test that shrinks the pool
    to prove a saturation property would leave every later test running on it.
    """

    def _configure(workers: int) -> int:
        thread_pool.configure(workers)
        return workers

    yield _configure
    thread_pool.shutdown()
    thread_pool._workers = None  # noqa: SLF001 — restoring module state the public API only sets


class TestChecksum:
    def test_built_packet_checksum_is_valid(self):
        packet = _build_echo_request(identifier=1, sequence=1, payload=b"abc")
        # The internet checksum property: recomputing over data that already
        # includes a correct checksum field yields zero.
        assert _checksum(packet) == 0

    def test_checksum_pads_odd_length(self):
        assert _checksum(b"\x01") == _checksum(b"\x01\x00")


class TestParseEchoReply:
    def test_valid_reply_matches(self):
        packet = _reply_packet(identifier=42, sequence=7)
        assert _parse_echo_reply(packet, identifier=42, sequence=7) is True

    def test_wrong_identifier_does_not_match(self):
        packet = _reply_packet(identifier=42, sequence=7)
        assert _parse_echo_reply(packet, identifier=99, sequence=7) is False

    def test_wrong_sequence_does_not_match(self):
        packet = _reply_packet(identifier=42, sequence=7)
        assert _parse_echo_reply(packet, identifier=42, sequence=8) is False

    def test_wrong_type_does_not_match(self):
        packet = _reply_packet(identifier=42, sequence=7, icmp_type=8)  # echo request, not reply
        assert _parse_echo_reply(packet, identifier=42, sequence=7) is False

    def test_short_packet_does_not_match(self):
        assert _parse_echo_reply(b"\x45\x00", identifier=1, sequence=1) is False

    def test_invalid_ipv4_header_length_does_not_match(self):
        packet = bytes([0x41]) + b"\x00" * 19 + struct.pack("!BBHHH", 0, 0, 0, 1, 1)
        assert _parse_echo_reply(packet, identifier=1, sequence=1) is False


def testtarget_identifier_in_range_and_differs_by_target():
    a = target_identifier("10.0.0.1")
    b = target_identifier("10.0.0.2")
    assert 0 <= a <= 0xFFFF
    assert 0 <= b <= 0xFFFF
    assert a != b


class TestResolveIpv4:
    """`resolve_ipv4` is the whole reason `_ping_once_blocking` no longer calls
    `socket.gethostbyname`: resolution must be bounded by the probe's own
    timeout and must not run on the collector's shared CPU pool.
    """

    async def test_ipv4_literal_short_circuits_without_touching_the_resolver(self, monkeypatch):
        loop = asyncio.get_running_loop()

        async def forbidden_getaddrinfo(*_args, **_kwargs):
            raise AssertionError("an IPv4 literal must never reach a resolver")

        monkeypatch.setattr(loop, "getaddrinfo", forbidden_getaddrinfo)
        assert await resolve_ipv4("10.0.0.1", timeout_s=1.0) == "10.0.0.1"

    async def test_hostname_resolves_to_the_first_ipv4_answer(self, monkeypatch):
        loop = asyncio.get_running_loop()
        seen: dict[str, object] = {}

        async def fake_getaddrinfo(host, port, *, family=0, **_kwargs):
            seen.update(host=host, port=port, family=family)
            return _addrinfo("192.0.2.7") + _addrinfo("192.0.2.8")

        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)

        assert await resolve_ipv4("switch.lan", timeout_s=1.0) == "192.0.2.7"
        # IPv4 only: an AAAA answer must not be able to arrive at a probe that
        # config validation already restricted to IPv4 (`_validate_icmp_host`).
        assert seen == {"host": "switch.lan", "port": None, "family": socket.AF_INET}

    async def test_empty_answer_raises_rather_than_returning_the_name(self, monkeypatch):
        loop = asyncio.get_running_loop()

        async def empty_getaddrinfo(*_args, **_kwargs):
            return []

        monkeypatch.setattr(loop, "getaddrinfo", empty_getaddrinfo)
        with pytest.raises(OSError, match="no IPv4 address for switch.lan"):
            await resolve_ipv4("switch.lan", timeout_s=1.0)

    async def test_resolver_error_propagates(self, monkeypatch):
        loop = asyncio.get_running_loop()

        async def failing_getaddrinfo(*_args, **_kwargs):
            raise socket.gaierror("Name or service not known")

        monkeypatch.setattr(loop, "getaddrinfo", failing_getaddrinfo)
        with pytest.raises(socket.gaierror, match="not known"):
            await resolve_ipv4("switch.lan", timeout_s=1.0)

    async def test_hanging_resolver_fails_within_the_probe_timeout(self, monkeypatch):
        """A black-holed nameserver must cost `timeout_s`, not the resolver's
        own (uncapped) retry schedule.
        """
        loop = asyncio.get_running_loop()

        async def hanging_getaddrinfo(*_args, **_kwargs):
            await asyncio.sleep(30.0)  # pragma: no cover — cancelled by the timeout

        monkeypatch.setattr(loop, "getaddrinfo", hanging_getaddrinfo)

        start = time.monotonic()
        with pytest.raises(TimeoutError, match="could not resolve black.hole within"):
            await resolve_ipv4("black.hole", timeout_s=0.05)
        assert time.monotonic() - start < 1.0

    async def test_hanging_resolver_does_not_occupy_a_cpu_pool_worker(
        self, monkeypatch, sized_cpu_pool
    ):
        """The reason resolution is not routed through `run_in_thread`.

        With every pool worker required to rendezvous at once, a resolution
        that consumed one would leave the barrier one short and break it.
        """
        workers = sized_cpu_pool(2)
        loop = asyncio.get_running_loop()

        async def hanging_getaddrinfo(*_args, **_kwargs):
            await asyncio.sleep(30.0)  # pragma: no cover — cancelled below

        monkeypatch.setattr(loop, "getaddrinfo", hanging_getaddrinfo)

        resolving = asyncio.create_task(resolve_ipv4("black.hole", timeout_s=30.0))
        await asyncio.sleep(0.01)  # let it reach the resolver and stall there

        barrier = threading.Barrier(workers)

        def rendezvous() -> bool:
            barrier.wait(timeout=2.0)
            return True

        occupied = await asyncio.gather(*(run_in_thread(rendezvous) for _ in range(workers)))
        assert occupied == [True] * workers

        resolving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await resolving


class TestPingOnceBlocking:
    def test_returns_rtt_on_matching_reply(self):
        fake_sock = MagicMock()
        fake_sock.recvfrom.return_value = (_reply_packet(5, 1), ("10.0.0.1", 0))
        with patch("collector.checks.net_icmp.socket.socket", return_value=fake_sock):
            rtt_ms = _ping_once_blocking("10.0.0.1", identifier=5, sequence=1, timeout_s=1.0)
        assert rtt_ms >= 0
        fake_sock.sendto.assert_called_once()
        fake_sock.close.assert_called_once()

    def test_skips_non_matching_reply_then_matches(self):
        fake_sock = MagicMock()
        fake_sock.recvfrom.side_effect = [
            (_reply_packet(999, 999), ("10.0.0.1", 0)),  # someone else's reply
            (_reply_packet(5, 1), ("10.0.0.1", 0)),
        ]
        with patch("collector.checks.net_icmp.socket.socket", return_value=fake_sock):
            rtt_ms = _ping_once_blocking("10.0.0.1", identifier=5, sequence=1, timeout_s=1.0)
        assert rtt_ms >= 0
        assert fake_sock.recvfrom.call_count == 2

    def test_skips_matching_packet_from_wrong_source(self):
        fake_sock = MagicMock()
        fake_sock.recvfrom.side_effect = [
            (_reply_packet(5, 1), ("10.0.0.2", 0)),
            (_reply_packet(5, 1), ("10.0.0.1", 0)),
        ]
        with patch("collector.checks.net_icmp.socket.socket", return_value=fake_sock):
            rtt_ms = _ping_once_blocking("10.0.0.1", identifier=5, sequence=1, timeout_s=1.0)
        assert rtt_ms >= 0
        assert fake_sock.recvfrom.call_count == 2

    def test_raises_timeout_error_when_deadline_exceeded(self):
        fake_sock = MagicMock()
        fake_sock.recvfrom.side_effect = TimeoutError("timed out")
        with (
            patch("collector.checks.net_icmp.socket.socket", return_value=fake_sock),
            pytest.raises(TimeoutError),
        ):
            _ping_once_blocking("10.0.0.1", identifier=5, sequence=1, timeout_s=0.01)
        fake_sock.close.assert_called_once()

    def test_closes_socket_on_send_error(self):
        fake_sock = MagicMock()
        fake_sock.sendto.side_effect = OSError("Operation not permitted")
        with (
            patch("collector.checks.net_icmp.socket.socket", return_value=fake_sock),
            pytest.raises(OSError, match="not permitted"),
        ):
            _ping_once_blocking("10.0.0.1", identifier=5, sequence=1, timeout_s=1.0)
        fake_sock.close.assert_called_once()


async def test_ping_delegates_to_blocking_helper_via_run_in_thread(monkeypatch):
    fake_sock = MagicMock()
    fake_sock.recvfrom.return_value = (_reply_packet(5, 1), ("10.0.0.1", 0))
    monkeypatch.setattr(
        "collector.checks.net_icmp.socket", _SocketModuleShim(lambda *_a, **_k: fake_sock)
    )
    rtt_ms = await ping("10.0.0.1", identifier=5, sequence=1, timeout_s=1.0)
    assert rtt_ms >= 0


# Long enough that a worker blocking without a deadline fails the recovery
# test's bound instead of quietly satisfying it, short enough that such a
# failure does not stall the run while the orphaned thread drains.
_NO_DEADLINE_BLOCK_S = 5.0


class _DeadlineSocket:
    """A fake raw socket that blocks for exactly as long as production says.

    Deliberately not a `MagicMock` with a hardcoded sleep: the point of the
    recovery test is that `_ping_once_blocking`'s own socket deadline is what
    frees the worker, so the fake must derive its blocking time from the
    `settimeout` value it is given. A regression that dropped the deadline
    would leave `_timeout` unset here, and the fake blocks far past the
    assertion's bound — the test can fail when the production bound breaks.
    """

    def __init__(self, reply: bytes | None = None) -> None:
        self._reply = reply
        self._timeout: float | None = None
        self.closed = False

    def settimeout(self, value: float) -> None:
        self._timeout = value

    def sendto(self, packet: bytes, _addr: tuple) -> int:
        return len(packet)

    def recvfrom(self, _bufsize: int) -> tuple[bytes, tuple[str, int]]:
        if self._reply is not None:
            return self._reply, ("10.0.0.1", 0)
        time.sleep(self._timeout if self._timeout is not None else _NO_DEADLINE_BLOCK_S)
        raise TimeoutError("timed out")

    def close(self) -> None:
        self.closed = True


async def test_cancelled_icmp_workers_free_within_their_socket_deadline(
    monkeypatch, sized_cpu_pool
):
    """Cancelling the awaiting coroutine does not stop the worker thread — a
    `run_in_executor` future cannot be cancelled once it is running. What
    bounds the worker is `timeout_s`, enforced by the socket deadline inside
    `_ping_once_blocking`. Saturate the pool, cancel every caller, and require
    a later probe to still get a worker within a small multiple of that.
    """
    workers = sized_cpu_pool(2)
    timeout_s = 0.3
    made = 0
    made_lock = threading.Lock()

    def socket_factory(*_args, **_kwargs) -> _DeadlineSocket:
        nonlocal made
        with made_lock:
            blocking = made < workers
            made += 1
        return _DeadlineSocket(None if blocking else _reply_packet(9, 1))

    monkeypatch.setattr("collector.checks.net_icmp.socket", _SocketModuleShim(socket_factory))

    saturating = [
        asyncio.create_task(ping("10.0.0.1", identifier=index, sequence=1, timeout_s=timeout_s))
        for index in range(workers)
    ]
    for task in saturating:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(task, timeout=0.02)

    start = time.monotonic()
    rtt_ms = await asyncio.wait_for(
        ping("10.0.0.1", identifier=9, sequence=1, timeout_s=timeout_s),
        timeout=timeout_s * 4,
    )
    elapsed = time.monotonic() - start

    assert rtt_ms >= 0
    assert elapsed < timeout_s * 4


class _FakeHistogram:
    def __init__(self):
        self.calls: list[tuple[float, dict]] = []

    def record(self, amount, attributes=None):
        self.calls.append((amount, attributes or {}))


class _FakeGauge:
    def __init__(self):
        self.calls: list[tuple[float, dict]] = []

    def set(self, amount, attributes=None):
        self.calls.append((amount, attributes or {}))


class _FakeMeter:
    def __init__(self):
        self.instruments: dict[str, object] = {}

    def create_histogram(self, name, description=None, unit=None):
        instrument = _FakeHistogram()
        self.instruments[name] = instrument
        return instrument

    def create_gauge(self, name, description=None, unit=None):
        instrument = _FakeGauge()
        self.instruments[name] = instrument
        return instrument


_TARGET = IcmpTarget(target_id="core-switch", host="10.0.0.1")
_HOSTNAME_TARGET = IcmpTarget(target_id="named-switch", host="switch.lan")


class TestIcmpCheck:
    def test_interval_s_from_config(self):
        settings = load_settings(collector_id="c", icmp={"interval_s": 5})
        check = IcmpCheck(settings, meter=None, target=_TARGET)
        assert check.interval_s == 5

    def test_semaphore_stored(self):
        settings = load_settings(collector_id="c")
        sem = asyncio.Semaphore(3)
        check = IcmpCheck(settings, meter=None, target=_TARGET, semaphore=sem)
        assert check.semaphore is sem

    def test_is_enabled_false_when_icmp_config_disabled(self):
        settings = load_settings(collector_id="c", icmp={"enabled": False})
        check = IcmpCheck(settings, meter=None, target=_TARGET)
        assert check.is_enabled() is False

    def test_is_enabled_true_when_icmp_config_enabled(self):
        settings = load_settings(collector_id="c", icmp={"enabled": True})
        check = IcmpCheck(settings, meter=None, target=_TARGET)
        assert check.is_enabled() is True

    async def test_run_ok_result(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = IcmpCheck(settings, meter=None, target=_TARGET)

        async def fake_ping(target, *, identifier, sequence, timeout_s):
            return 12.5

        monkeypatch.setattr("collector.checks.net_icmp.ping", fake_ping)
        result = await check.run()

        assert result.ok is True
        assert result.metrics["icmp_rtt_ms"] == 12.5
        assert result.metrics["icmp_loss_pct"] == 0.0
        assert result.labels == {"target": "10.0.0.1"}
        assert result.error is None

    async def test_run_never_raises_on_failure(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = IcmpCheck(settings, meter=None, target=_TARGET)

        async def failing_ping(target, *, identifier, sequence, timeout_s):
            raise TimeoutError("no reply from 10.0.0.1 within 2.0s")

        monkeypatch.setattr("collector.checks.net_icmp.ping", failing_ping)
        result = await check.run()

        assert result.ok is False
        assert result.metrics["icmp_loss_pct"] == 100.0
        assert result.labels == {"target": "10.0.0.1"}
        assert "no reply" in result.error

    async def test_run_increments_sequence_each_call(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = IcmpCheck(settings, meter=None, target=_TARGET)
        seen_sequences = []

        async def fake_ping(target, *, identifier, sequence, timeout_s):
            seen_sequences.append(sequence)
            return 1.0

        monkeypatch.setattr("collector.checks.net_icmp.ping", fake_ping)
        await check.run()
        await check.run()

        assert seen_sequences == [1, 2]

    async def test_run_ok_emits_canonical_metrics_with_target_id_label(self, monkeypatch):
        settings = load_settings(collector_id="c")
        meter = _FakeMeter()
        check = IcmpCheck(settings, meter=meter, target=_TARGET)

        async def fake_ping(target, *, identifier, sequence, timeout_s):
            return 20.0

        monkeypatch.setattr("collector.checks.net_icmp.ping", fake_ping)
        await check.run()

        rtt_calls = meter.instruments["sentinel_collector_icmp_rtt_seconds"].calls
        loss_calls = meter.instruments["sentinel_collector_icmp_loss_ratio"].calls
        assert rtt_calls == [(0.02, {"target_id": "core-switch"})]
        assert loss_calls == [(0.0, {"target_id": "core-switch"})]

    async def test_run_failure_emits_loss_ratio_but_not_rtt(self, monkeypatch):
        settings = load_settings(collector_id="c")
        meter = _FakeMeter()
        check = IcmpCheck(settings, meter=meter, target=_TARGET)

        async def failing_ping(target, *, identifier, sequence, timeout_s):
            raise TimeoutError("no reply")

        monkeypatch.setattr("collector.checks.net_icmp.ping", failing_ping)
        await check.run()

        rtt_calls = meter.instruments["sentinel_collector_icmp_rtt_seconds"].calls
        loss_calls = meter.instruments["sentinel_collector_icmp_loss_ratio"].calls
        assert rtt_calls == []
        assert loss_calls == [(1.0, {"target_id": "core-switch"})]

    async def test_permission_denied_is_contained_not_raised(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = IcmpCheck(settings, meter=None, target=_TARGET)

        async def denied_ping(target, *, identifier, sequence, timeout_s):
            raise PermissionError("Operation not permitted")

        monkeypatch.setattr("collector.checks.net_icmp.ping", denied_ping)
        result = await check.run()

        assert result.ok is False
        assert "not permitted" in result.error

    async def test_run_pings_the_resolved_literal_for_a_hostname_target(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = IcmpCheck(settings, meter=None, target=_HOSTNAME_TARGET)
        loop = asyncio.get_running_loop()

        async def fake_getaddrinfo(*_args, **_kwargs):
            return _addrinfo("192.0.2.7")

        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
        pinged: list[str] = []

        async def fake_ping(destination_ip, *, identifier, sequence, timeout_s):
            pinged.append(destination_ip)
            return 3.0

        monkeypatch.setattr("collector.checks.net_icmp.ping", fake_ping)
        result = await check.run()

        assert pinged == ["192.0.2.7"]
        assert result.ok is True
        # The label stays the configured name — resolution is an implementation
        # detail of reaching the target, not a change of which target it is.
        assert result.labels == {"target": "switch.lan"}

    async def test_run_resolution_failure_is_contained_and_skips_the_ping(self, monkeypatch):
        settings = load_settings(collector_id="c")
        meter = _FakeMeter()
        check = IcmpCheck(settings, meter=meter, target=_HOSTNAME_TARGET)
        loop = asyncio.get_running_loop()

        async def failing_getaddrinfo(*_args, **_kwargs):
            raise socket.gaierror("Name or service not known")

        monkeypatch.setattr(loop, "getaddrinfo", failing_getaddrinfo)
        pinged: list[str] = []

        async def fake_ping(destination_ip, *, identifier, sequence, timeout_s):
            pinged.append(destination_ip)  # pragma: no cover — must not be reached
            return 3.0

        monkeypatch.setattr("collector.checks.net_icmp.ping", fake_ping)
        result = await check.run()

        assert pinged == []
        assert result.ok is False
        assert result.metrics == {"icmp_loss_pct": 100.0}
        assert "not known" in result.error
        loss_calls = meter.instruments["sentinel_collector_icmp_loss_ratio"].calls
        assert loss_calls == [(1.0, {"target_id": "named-switch"})]
