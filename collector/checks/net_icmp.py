"""Raw ICMP echo probe (net_icmp) — one echo request per scheduler cycle for
this check instance's target. Requires `CAP_NET_RAW` (or root) to open an
`AF_INET`/`SOCK_RAW`/`IPPROTO_ICMP` socket.
"""
from __future__ import annotations

import asyncio
import os
import socket
import struct
import time

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings

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


def _ping_once_blocking(
    target_ip: str, identifier: int, sequence: int, timeout_s: float
) -> float:
    """Send one echo request and block for the matching reply.

    Returns RTT in milliseconds. Raises `TimeoutError`/`OSError` on failure.
    This is a plain blocking function run off the event loop via
    `asyncio.to_thread` (see `ping()`) — not an `async def` — so it can be
    exercised in tests by mocking `socket.socket`, without a real
    (privileged) raw socket or asyncio fd registration.
    """
    payload = struct.pack("!d", time.monotonic())
    packet = _build_echo_request(identifier, sequence, payload)

    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    try:
        start = time.monotonic()
        sock.sendto(packet, (target_ip, 0))
        deadline = start + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no reply from {target_ip} within {timeout_s}s")
            sock.settimeout(remaining)
            try:
                reply, _addr = sock.recvfrom(1024)
            except TimeoutError:
                raise TimeoutError(f"no reply from {target_ip} within {timeout_s}s") from None
            if _parse_echo_reply(reply, identifier, sequence):
                return (time.monotonic() - start) * 1000.0
            # Not our reply (e.g. one meant for a concurrent ping) — keep waiting.
    finally:
        sock.close()


async def ping(target_ip: str, *, identifier: int, sequence: int, timeout_s: float) -> float:
    """Async wrapper around the blocking ping — RTT in milliseconds."""
    return await asyncio.to_thread(
        _ping_once_blocking, target_ip, identifier, sequence, timeout_s
    )


class IcmpCheck(BaseCheck):
    name = "net_icmp"
    scan_level = 1

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        target: str,
        *,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self.target = target
        self.interval_s = config.icmp.interval_s
        self._sequence = 0
        self._identifier = target_identifier(target)

    async def run(self) -> CheckResult:
        self._sequence = (self._sequence + 1) % 65536
        try:
            rtt_ms = await ping(
                self.target,
                identifier=self._identifier,
                sequence=self._sequence,
                timeout_s=self.config.icmp.timeout_s,
            )
            return CheckResult(
                ok=True,
                metrics={"icmp_rtt_ms": rtt_ms, "icmp_loss_pct": 0.0},
                labels={"target": self.target},
            )
        except Exception as exc:  # BaseCheck.run() must never raise
            log.warning("check.degraded", check=self.name, target=self.target, error=str(exc))
            return CheckResult(
                ok=False,
                metrics={"icmp_loss_pct": 100.0},
                labels={"target": self.target},
                error=str(exc),
            )
