"""Linux memory utilization check (host_memory) — reads `/proc/meminfo` for
an instantaneous used-ratio snapshot (no delta needed, unlike CPU jiffies).

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
from collector.utils.thread_pool import run_in_thread

log = structlog.get_logger()

DEFAULT_MEMINFO_PATH = "/proc/meminfo"


def _parse_meminfo(text: str) -> dict[str, int]:
    """Parse `/proc/meminfo` into a `{field: kB}` mapping.

    Raises `ValueError` if a line's value isn't a leading integer.
    """
    fields: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        parts = rest.split()
        if not parts:
            continue
        try:
            fields[key.strip()] = int(parts[0])
        except ValueError as exc:
            raise ValueError(f"non-integer /proc/meminfo value: {line!r}") from exc
    return fields


def _read_meminfo(path: str) -> dict[str, int]:
    with open(path, encoding="ascii") as f:
        return _parse_meminfo(f.read())


class HostMemoryCheck(BaseCheck):
    """Memory used-ratio from `/proc/meminfo`.

    Prefers the kernel's own `MemAvailable` estimate (accounts for
    reclaimable cache, unlike a naive `MemFree` reading); falls back to
    `MemFree + Buffers + Cached` on kernels too old to report it.
    """

    name = "host_memory"
    scan_level = 1
    interval_s = 30.0

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        *,
        meminfo_path: str = DEFAULT_MEMINFO_PATH,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self._meminfo_path = meminfo_path

    async def run(self) -> CheckResult:
        if sys.platform != "linux":
            return CheckResult(ok=False, error=f"unsupported platform: {sys.platform}")

        try:
            fields = await run_in_thread(_read_meminfo, self._meminfo_path)
            if "MemTotal" not in fields:
                raise ValueError("/proc/meminfo missing MemTotal")
            total_kb = fields["MemTotal"]
            if "MemAvailable" in fields:
                available_kb = fields["MemAvailable"]
            else:
                available_kb = (
                    fields.get("MemFree", 0) + fields.get("Buffers", 0) + fields.get("Cached", 0)
                )
            if total_kb <= 0:
                raise ValueError(f"non-positive MemTotal: {total_kb}")
        except Exception as exc:  # BaseCheck.run() must never raise
            log.warning("check.degraded", check=self.name, error=str(exc))
            return CheckResult(ok=False, error=str(exc))

        used_ratio = max(0.0, min(1.0, 1.0 - (available_kb / total_kb)))
        return CheckResult(ok=True, metrics={"memory_used_ratio": used_ratio}, labels={})
