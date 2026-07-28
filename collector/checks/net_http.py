"""HTTP/HTTPS probe (net_http) — aiohttp GET measuring response time; TLS
certificate verification is configurable via `HttpConfig.verify_tls` (useful
for self-signed OT/internal endpoints).
"""

from __future__ import annotations

import asyncio
import time
from typing import ClassVar

import aiohttp
import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings, HttpTarget

log = structlog.get_logger()


async def http_probe(
    url: str,
    *,
    timeout_s: float,
    verify_tls: bool,
    session: aiohttp.ClientSession | None = None,
) -> tuple[float, int]:
    """GET `url`. Returns (response_ms, status_code).

    Raises on connection failure/timeout. A non-2xx status is not itself an
    error here — the caller (`HttpCheck.run`) decides what "ok" means.
    """
    owns_session = session is None
    active = session if session is not None else aiohttp.ClientSession()
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        start = time.monotonic()
        async with active.get(url, timeout=timeout, ssl=verify_tls) as resp:
            await resp.read()
            response_ms = (time.monotonic() - start) * 1000.0
            return response_ms, resp.status
    finally:
        if owns_session:
            await active.close()


class HttpCheck(BaseCheck):
    """HTTP/HTTPS probe.

    All `HttpCheck` instances (across all targets) share one class-level
    `aiohttp.ClientSession` — creating a fresh session per probe call
    re-establishes the TCP connection pool and re-resolves DNS every time,
    which is expensive at scheduler-cycle frequency (see
    docs/guides/ASYNCIO-OPTIMIZATION.md §5).
    """

    name = "net_http"
    scan_level = 1

    _session: ClassVar[aiohttp.ClientSession | None] = None

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        target: HttpTarget,
        *,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self.target = target
        self.interval_s = config.http.interval_s
        self._response_seconds = (
            meter.create_histogram(
                "sentinel_collector_http_response_seconds",
                description="HTTP response time",
                unit="s",
            )
            if meter is not None
            else None
        )

    def is_enabled(self) -> bool:
        return super().is_enabled() and self.config.http.enabled

    @classmethod
    async def _get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            cls._session = aiohttp.ClientSession(connector=connector)
        return cls._session

    async def aclose(self) -> None:
        """Close the shared class-level session.

        Every `HttpCheck` instance (across every target) shares the one
        session `_get_session` creates, so closing it from any single
        instance is correct and sufficient — safe to call multiple times or
        when no session was ever created.
        """
        session = type(self)._session
        if session is not None and not session.closed:
            await session.close()

    async def run(self) -> CheckResult:
        try:
            session = await self._get_session()
            response_ms, status = await http_probe(
                self.target.url,
                timeout_s=self.config.http.timeout_s,
                verify_tls=self.config.http.verify_tls,
                session=session,
            )
            # Strict 2xx-only success, not "< 400" or "< 500" — the v1
            # monitor's CWE-252 finding (docs/security/code-scanning-
            # remediation.md) showed a lenient range reports 401/403/404 as
            # healthy, masking auth failures and dead endpoints.
            ok = 200 <= status < 300
            if self._response_seconds is not None:
                # Only a bounded target_id + ok/error state ever reaches a
                # metric attribute — the raw URL and status code stay in
                # CheckResult/structured logs, never an exported label.
                self._response_seconds.record(
                    response_ms / 1000.0,
                    attributes={
                        "target_id": self.target.target_id,
                        "state": "ok" if ok else "error",
                    },
                )
            labels = {"target_id": self.target.target_id, "status_code": str(status)}
            return CheckResult(
                ok=ok,
                metrics={"http_response_ms": response_ms},
                labels=labels,
            )
        except Exception as exc:
            error = f"HTTP probe failed: {type(exc).__name__}"
            log.warning(
                "check.degraded",
                check=self.name,
                target_id=self.target.target_id,
                error_type=type(exc).__name__,
            )
            return CheckResult(
                ok=False,
                labels={"target_id": self.target.target_id},
                error=error,
            )
