"""systemd service-status check (host_service) — `systemctl is-active
<service>` for one configured service, mirroring `host_process.py`'s
one-instance-per-name shape.

Uses `asyncio.create_subprocess_exec` directly rather than the bounded
thread pool: subprocess spawning/communication is genuinely async I/O via
the event loop, not a blocking call needing the executor.

Standalone in this claim: not yet registered by `collector/__main__.py` and
does not create any OTel instrument. Registration and metric emission are a
later, separately reviewed claim (see docs/guides/SONNET-5-WORK-QUEUE.md).
"""
from __future__ import annotations

import asyncio
import sys

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings

log = structlog.get_logger()

DEFAULT_TIMEOUT_S = 5.0


async def _service_is_active(service_name: str, *, timeout_s: float) -> bool:
    """True if `systemctl is-active <service_name>` reports `active`.

    Raises `RuntimeError` if `systemctl` isn't on `PATH` (non-systemd Linux
    or a minimal container), or `TimeoutError` if the command doesn't finish
    within `timeout_s` (the subprocess is killed either way).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "is-active",
            service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("systemctl not found") from exc

    try:
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise

    return proc.returncode == 0 and stdout.decode().strip() == "active"


class HostServiceCheck(BaseCheck):
    """Whether one named systemd service is currently active."""

    name = "host_service"
    scan_level = 1
    interval_s = 60.0

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        service_name: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self.service_name = service_name
        self._timeout_s = timeout_s

    async def run(self) -> CheckResult:
        if sys.platform != "linux":
            return CheckResult(ok=False, error=f"unsupported platform: {sys.platform}")

        labels = {"service": self.service_name}
        try:
            active = await _service_is_active(self.service_name, timeout_s=self._timeout_s)
        except Exception as exc:  # BaseCheck.run() must never raise
            log.warning(
                "check.degraded", check=self.name, service=self.service_name, error=str(exc)
            )
            return CheckResult(ok=False, labels=labels, error=str(exc))

        if not active:
            return CheckResult(
                ok=False,
                metrics={"service_active": 0.0},
                labels=labels,
                error=f"service {self.service_name!r} not active",
            )
        return CheckResult(ok=True, metrics={"service_active": 1.0}, labels=labels)
