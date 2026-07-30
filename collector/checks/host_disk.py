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


def _validate_mount_path(value: str) -> str:
    """Bound the configured mount path — non-empty, single-line, printable.

    The path is an operational value only: `METRICS.md` forbids raw paths as
    metric labels, and this check keeps it out of `CheckResult` entirely,
    reporting it through structured logs instead.
    """
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"path must be a non-empty, non-whitespace-padded value: got {value!r}")
    if not value.isprintable():
        raise ValueError("path must not contain control characters")
    return value


def _disk_used_ratio(path: str) -> float:
    """Used ratio for `path`, failing closed on impossible usage figures.

    `shutil.disk_usage` is a `statvfs`/`GetDiskFreeSpaceEx` wrapper, so bad
    values mean a broken filesystem or a lying container runtime — not a
    number worth clamping into range.
    """
    usage = shutil.disk_usage(path)
    if usage.total <= 0:
        raise ValueError(f"non-positive disk total: {usage.total}")
    if usage.used < 0:
        raise ValueError(f"negative disk used: {usage.used}")
    if usage.used > usage.total:
        raise ValueError(f"disk used {usage.used} exceeds total {usage.total}")
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
        self.path = _validate_mount_path(path)

    async def run(self) -> CheckResult:
        try:
            used_ratio = await run_in_thread(_disk_used_ratio, self.path)
        except Exception as exc:  # BaseCheck.run() must never raise
            # `CancelledError` is a `BaseException`, so external cancellation
            # still propagates past this handler as the scheduler requires.
            log.warning("check.degraded", check=self.name, path=self.path, error=str(exc))
            # The full message (which may embed the mount path) stays in the
            # structured log; the result carries only the exception type.
            return CheckResult(ok=False, error=type(exc).__name__)

        return CheckResult(ok=True, metrics={"disk_used_ratio": used_ratio}, labels={})
