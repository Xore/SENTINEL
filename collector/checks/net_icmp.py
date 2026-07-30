"""Raw ICMP echo probe (net_icmp) — one echo request per scheduler cycle for
this check instance's target. Requires `CAP_NET_RAW` (or root) to open an
`AF_INET`/`SOCK_RAW`/`IPPROTO_ICMP` socket.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import struct
import time

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings, IcmpTarget
from collector.utils.thread_pool import run_in_thread

log = structlog.get_logger()

ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0


def _checksum(data: bytes) -> int:
    """Internet checksum (RFC 1071) over `data`."""
    if len(data) % 2:
        data += b"\x00"
    total = sum((data[i] << 8) + data[i + 1] for i in range(0, len(data), 2))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF


def _build_echo_request(identifier: int, sequence: int, payload: bytes) -> bytes:
    header = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, 0, 0, identifier, sequence)
    chksum = _checksum(header + payload)
    header = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, 0, chksum, identifier, sequence)
    return header + payload


def _parse_echo_reply(packet: bytes, identifier: int, sequence: int) -> bool:
    """True if `packet` (a full IPv4 datagram) is the echo reply we're waiting for."""
    if len(packet) < 20 + 8:
        return False
    ihl = (packet[0] & 0x0F) * 4
    if ihl < 20 or len(packet) < ihl + 8:
        return False
    icmp = packet[ihl : ihl + 8]
    if len(icmp) < 8:
        return False
    icmp_type, _code, _chksum, recv_id, recv_seq = struct.unpack("!BBHHH", icmp)
    return icmp_type == ICMP_ECHO_REPLY and recv_id == identifier and recv_seq == sequence


def target_identifier(target: str) -> int:
    """A per-target ICMP identifier.

    Raw ICMP sockets receive every ICMP packet arriving at the host, not
    just replies to what they sent, so concurrent checks for different
    targets need distinguishable identifiers to avoid one instance matching
    a reply meant for another.
    """
    return (os.getpid() ^ hash(target)) & 0xFFFF


async def resolve_ipv4(host: str, *, timeout_s: float) -> str:
    """Resolve `host` to an IPv4 literal, bounded by `timeout_s`.

    Deliberately **not** routed through `run_in_thread`. A blocked resolver is
    not CPU work, and a `run_in_executor` future cannot be cancelled once it
    is running: putting resolution on the collector's small shared CPU pool
    means a black-holed nameserver occupies a worker until the resolver's own
    (uncapped, ~5s x 2 per nameserver on glibc) timeout fires, long after the
    awaiting probe was cancelled. That starves every other check using the
    pool and puts the probe outside its configured `timeout_s`.

    `loop.getaddrinfo` uses the event loop's default executor instead, which
    is separate from the collector's CPU pool and sized for exactly this kind
    of stall. `asyncio.timeout` still cannot reclaim that thread early —
    nothing can — but the *probe* now fails on schedule and the CPU pool is
    untouched, which is what the check's timeout budget actually promises.

    IPv4 literals short-circuit without touching a resolver. IPv6 is rejected
    upstream by config validation (`_validate_icmp_host`); this raises rather
    than silently probing something else if one arrives anyway.
    """
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        pass
    else:
        return host

    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(timeout_s):
            infos = await loop.getaddrinfo(host, None, family=socket.AF_INET)
    except TimeoutError:
        raise TimeoutError(f"could not resolve {host} within {timeout_s}s") from None
    if not infos:
        raise OSError(f"no IPv4 address for {host}")
    return str(infos[0][4][0])


def _ping_once_blocking(
    destination_ip: str, identifier: int, sequence: int, timeout_s: float
) -> float:
    """Send one echo request to an IPv4 literal and block for the matching reply.

    `destination_ip` must already be a literal — `resolve_ipv4()` is the
    caller's job, precisely so that no name resolution happens on the shared
    CPU pool. Returns RTT in milliseconds; raises `TimeoutError`/`OSError`.
    This is a plain blocking function run off the event loop (see `ping()`) —
    not an `async def` — so it can be exercised in tests by mocking
    `socket.socket`, without a real (privileged) raw socket or asyncio fd
    registration.
    """
    payload = struct.pack("!d", time.monotonic())
    packet = _build_echo_request(identifier, sequence, payload)

    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    try:
        start = time.monotonic()
        sock.sendto(packet, (destination_ip, 0))
        deadline = start + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no reply from {destination_ip} within {timeout_s}s")
            sock.settimeout(remaining)
            try:
                reply, addr = sock.recvfrom(1024)
            except TimeoutError:
                raise TimeoutError(
                    f"no reply from {destination_ip} within {timeout_s}s"
                ) from None
            if addr[0] == destination_ip and _parse_echo_reply(reply, identifier, sequence):
                return (time.monotonic() - start) * 1000.0
            # Not our reply (e.g. one meant for a concurrent ping) — keep waiting.
    finally:
        sock.close()


async def ping(destination_ip: str, *, identifier: int, sequence: int, timeout_s: float) -> float:
    """Async wrapper around the blocking ping — RTT in milliseconds.

    `destination_ip` must be an IPv4 literal; call `resolve_ipv4()` once per
    check run, not once per ping, so a latency burst does not pay resolution
    `sample_count` times.

    Runs on the collector's shared CPU thread pool
    (`collector.utils.thread_pool.run_in_thread`) rather than the loop's
    default executor — raw-socket ICMP is exactly the kind of blocking call
    that pool exists for (docs/guides/ASYNCIO-OPTIMIZATION.md §3). The pool's
    worker count is configuration (`CollectorSettings.cpu_pool_workers`,
    ADR 0012), so what bounds this call is `timeout_s`, enforced by the socket
    deadline inside `_ping_once_blocking` — not the pool's size.
    """
    return await run_in_thread(_ping_once_blocking, destination_ip, identifier, sequence, timeout_s)


class IcmpCheck(BaseCheck):
    name = "net_icmp"
    scan_level = 1

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        target: IcmpTarget,
        *,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self.target = target
        self.interval_s = config.icmp.interval_s
        self._sequence = 0
        self._identifier = target_identifier(target.host)
        self._rtt_seconds = (
            meter.create_histogram(
                "sentinel_collector_icmp_rtt_seconds",
                description="ICMP echo round-trip time",
                unit="s",
            )
            if meter is not None
            else None
        )
        self._loss_ratio = (
            meter.create_gauge(
                "sentinel_collector_icmp_loss_ratio",
                description="ICMP echo loss ratio (0.0-1.0) for the most recent probe",
                unit="1",
            )
            if meter is not None
            else None
        )

    def is_enabled(self) -> bool:
        return super().is_enabled() and self.config.icmp.enabled

    def _record(self, *, rtt_ms: float | None, loss_pct: float) -> None:
        attributes = {"target_id": self.target.target_id}
        if self._rtt_seconds is not None and rtt_ms is not None:
            self._rtt_seconds.record(rtt_ms / 1000.0, attributes=attributes)
        if self._loss_ratio is not None:
            self._loss_ratio.set(loss_pct / 100.0, attributes=attributes)

    async def run(self) -> CheckResult:
        self._sequence = (self._sequence + 1) % 65536
        timeout_s = self.config.icmp.timeout_s
        try:
            destination_ip = await resolve_ipv4(self.target.host, timeout_s=timeout_s)
            rtt_ms = await ping(
                destination_ip,
                identifier=self._identifier,
                sequence=self._sequence,
                timeout_s=timeout_s,
            )
            self._record(rtt_ms=rtt_ms, loss_pct=0.0)
            return CheckResult(
                ok=True,
                metrics={"icmp_rtt_ms": rtt_ms, "icmp_loss_pct": 0.0},
                labels={"target": self.target.host},
            )
        except Exception as exc:  # BaseCheck.run() must never raise
            log.warning("check.degraded", check=self.name, target=self.target.host, error=str(exc))
            self._record(rtt_ms=None, loss_pct=100.0)
            return CheckResult(
                ok=False,
                metrics={"icmp_loss_pct": 100.0},
                labels={"target": self.target.host},
                error=str(exc),
            )
