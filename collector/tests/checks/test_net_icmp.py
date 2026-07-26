"""Tests for collector.checks.net_icmp — packet framing and the ICMP check."""
from __future__ import annotations

import asyncio
import struct
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
    target_identifier,
)
from collector.config import IcmpTarget, load_settings


def _reply_packet(identifier: int, sequence: int, icmp_type: int = ICMP_ECHO_REPLY) -> bytes:
    """A minimal IPv4 datagram (20-byte header, no options) wrapping an ICMP
    echo reply — as `_ping_once_blocking` would receive from a real socket.
    """
    ip_header = bytes([0x45]) + b"\x00" * 19
    icmp_header = struct.pack("!BBHHH", icmp_type, 0, 0, identifier, sequence)
    return ip_header + icmp_header + b"payload"


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


def testtarget_identifier_in_range_and_differs_by_target():
    a = target_identifier("10.0.0.1")
    b = target_identifier("10.0.0.2")
    assert 0 <= a <= 0xFFFF
    assert 0 <= b <= 0xFFFF
    assert a != b


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


async def test_ping_delegates_to_blocking_helper_via_run_in_thread():
    fake_sock = MagicMock()
    fake_sock.recvfrom.return_value = (_reply_packet(5, 1), ("10.0.0.1", 0))
    with patch("collector.checks.net_icmp.socket.socket", return_value=fake_sock):
        rtt_ms = await ping("10.0.0.1", identifier=5, sequence=1, timeout_s=1.0)
    assert rtt_ms >= 0


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
