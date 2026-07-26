"""DNS resolution probe (net_dns) — dnspython asyncio resolve, measuring
resolution time per (hostname, record_type).
"""
from __future__ import annotations

import asyncio
import time

import dns.asyncresolver
import dns.exception
import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings

log = structlog.get_logger()


async def dns_resolve(
    hostname: str,
    record_type: str,
    *,
    timeout_s: float,
    resolvers: list[str] | None = None,
    resolver: dns.asyncresolver.Resolver | None = None,
) -> float:
    """Resolve `hostname`'s `record_type` records.

    Returns resolve time in milliseconds. Raises
    `dns.exception.DNSException`/`OSError` on failure. Pass `resolver` to
    reuse one across calls — constructing a fresh `Resolver()` reads system
    resolver config (e.g. `/etc/resolv.conf`) each time.
    """
    active = resolver if resolver is not None else dns.asyncresolver.Resolver()
    if resolvers:
        active.nameservers = resolvers
    start = time.monotonic()
    await active.resolve(hostname, record_type, lifetime=timeout_s)
    return (time.monotonic() - start) * 1000.0


class DnsCheck(BaseCheck):
    name = "net_dns"
    scan_level = 1

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        target: str,
        record_type: str = "A",
        *,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self.target = target
        self.record_type = record_type
        self.interval_s = config.dns.interval_s
        self._resolver = dns.asyncresolver.Resolver()
        if config.dns.resolvers:
            self._resolver.nameservers = config.dns.resolvers

    async def run(self) -> CheckResult:
        labels = {"target": self.target, "record_type": self.record_type}
        try:
            resolve_ms = await dns_resolve(
                self.target,
                self.record_type,
                timeout_s=self.config.dns.timeout_s,
                resolver=self._resolver,
            )
            return CheckResult(ok=True, metrics={"dns_resolve_ms": resolve_ms}, labels=labels)
        except Exception as exc:
            log.warning(
                "check.degraded",
                check=self.name,
                target=self.target,
                record_type=self.record_type,
                error=str(exc),
            )
            return CheckResult(ok=False, labels=labels, error=str(exc))
