"""HTTP/HTTPS probe (net_http) — aiohttp GET measuring response time; TLS
certificate verification is configurable via `HttpConfig.verify_tls` (useful
for self-signed OT/internal endpoints).
"""
from __future__ import annotations

import time

import aiohttp
import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings

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
    name = "net_http"
    scan_level = 1

    def __init__(self, config: CollectorSettings, meter: Meter, target: str) -> None:
        super().__init__(config, meter)
        self.target = target

    async def run(self) -> CheckResult:
        try:
            response_ms, status = await http_probe(
                self.target,
                timeout_s=self.config.http.timeout_s,
                verify_tls=self.config.http.verify_tls,
            )
            labels = {"target": self.target, "status_code": str(status)}
            # Strict 2xx-only success, not "< 400" or "< 500" — the v1
            # monitor's CWE-252 finding (docs/security/code-scanning-
            # remediation.md) showed a lenient range reports 401/403/404 as
            # healthy, masking auth failures and dead endpoints.
            return CheckResult(
                ok=200 <= status < 300,
                metrics={"http_response_ms": response_ms},
                labels=labels,
            )
        except Exception as exc:
            log.warning("check.degraded", check=self.name, target=self.target, error=str(exc))
            return CheckResult(ok=False, labels={"target": self.target}, error=str(exc))
