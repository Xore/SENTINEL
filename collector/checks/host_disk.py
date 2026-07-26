"""Disk usage check (host_disk) — `shutil.disk_usage` used-ratio for one
configured mount path. Portable (works on Linux/Windows/macOS), unlike the
other host checks in this claim that read Linux-specific `/proc` files.

Standalone in this claim: not yet registered by `collector/__main__.py` and
does not create any OTel instrument. Registration and metric emission are a
later, separately reviewed claim (see docs/guides/SONNET-5-WORK-QUEUE.md).
"""
from __future__ import annotations

import asyncio
import shutil

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings
from collector.utils.thread_pool import run_in_thread

log = structlog.get_logger()

DEFAULT_DISK_PATH = "/"


def _disk_used_ratio(path: str) -> float:
    usage = shutil.disk_usage(path)
    if usage.total <= 0:
        raise ValueError(f"non-positive disk total for {path!r}: {usage.total}")
    return usage.used / usage.total


class HostDiskCheck(BaseCheck):
    """Disk used-ratio for one configured mount path."""

    name = "host_disk"
    scan_level = 1
    interval_s = 60.0

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        *,
        path: str = DEFAULT_DISK_PATH,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self.path = path

    async def run(self) -> CheckResult:
        try:
            used_ratio = await run_in_thread(_disk_used_ratio, self.path)
        except Exception as exc:  # BaseCheck.run() must never raise
            log.warning("check.degraded", check=self.name, path=self.path, error=str(exc))
            return CheckResult(ok=False, error=str(exc))

        used_ratio = max(0.0, min(1.0, used_ratio))
        return CheckResult(ok=True, metrics={"disk_used_ratio": used_ratio}, labels={})
