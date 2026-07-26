"""TCP connect probe (net_tcp) — measures connect time to a host:port via
`asyncio.open_connection`. No raw sockets, no special capability required.
"""
from __future__ import annotations

import asyncio
import time

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings, TcpTarget

log = structlog.get_logger()


async def tcp_connect(host: str, port: int, timeout_s: float) -> float:
    """Open then close a TCP connection to `host:port`.

    Returns connect time in milliseconds. Raises `OSError`/`TimeoutError` on
    failure (refused, unreachable, or slower than `timeout_s`).
    """
    start = time.monotonic()
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout=timeout_s
    )
    connect_ms = (time.monotonic() - start) * 1000.0
    writer.close()
    await writer.wait_closed()
    return connect_ms


class TcpCheck(BaseCheck):
    name = "net_tcp"
    scan_level = 1

    def __init__(self, config: CollectorSettings, meter: Meter, target: TcpTarget) -> None:
        super().__init__(config, meter)
        self.target = target

    async def run(self) -> CheckResult:
        labels = {"target": self.target.host, "port": str(self.target.port)}
        try:
            connect_ms = await tcp_connect(
                self.target.host, self.target.port, self.config.tcp.timeout_s
            )
            return CheckResult(ok=True, metrics={"tcp_connect_ms": connect_ms}, labels=labels)
        except Exception as exc:
            log.warning(
                "check.degraded",
                check=self.name,
                target=self.target.host,
                port=self.target.port,
                error=str(exc),
            )
            return CheckResult(ok=False, labels=labels, error=str(exc))
