"""Linux CPU utilization check (host_cpu) — computes utilization from the
delta between two consecutive `/proc/stat` samples across scheduler cycles.

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

DEFAULT_PROC_STAT_PATH = "/proc/stat"


def _parse_cpu_line(line: str) -> tuple[int, int]:
    """Parse `/proc/stat`'s aggregate `cpu` line into `(idle, total)` jiffies.

    Fails closed: raises `ValueError` if the line isn't the expected aggregate
    CPU line, doesn't have enough fields, or reports values that cannot come
    from a healthy kernel (negative jiffies or a non-positive total). Producing
    a plausible-looking ratio from impossible input would be worse than
    reporting a failed check.

    `idle <= total` needs no separate check here: idle is a subset sum of
    values that have already been proven non-negative. The cross-sample
    equivalent is not implied that way and is checked in `run()`.
    """
    fields = line.split()
    if not fields or fields[0] != "cpu":
        raise ValueError(f"unexpected /proc/stat format: {line!r}")
    try:
        values = [int(x) for x in fields[1:]]
    except ValueError as exc:
        raise ValueError(f"non-integer /proc/stat cpu field: {line!r}") from exc
    if len(values) < 4:
        raise ValueError(f"insufficient /proc/stat cpu fields: {line!r}")
    if any(value < 0 for value in values):
        raise ValueError(f"negative /proc/stat cpu jiffies: {line!r}")
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    total = sum(values)
    if total <= 0:
        raise ValueError(f"non-positive /proc/stat cpu total: {line!r}")
    return idle, total


def _read_cpu_jiffies(path: str) -> tuple[int, int]:
    with open(path, encoding="ascii") as f:
        first_line = f.readline()
    return _parse_cpu_line(first_line)


class HostCpuCheck(BaseCheck):
    """CPU utilization since the previous cycle's sample.

    The first `run()` after construction has no prior sample to diff
    against, so it records a baseline and reports success with no metrics
    yet — utilization is only meaningful across an interval.
    """

    name = "host_cpu"
    scan_level = 1
    interval_s = 30.0

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        *,
        proc_stat_path: str = DEFAULT_PROC_STAT_PATH,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self._proc_stat_path = proc_stat_path
        self._prev: tuple[int, int] | None = None

    async def run(self) -> CheckResult:
        if sys.platform != "linux":
            return CheckResult(ok=False, error=f"unsupported platform: {sys.platform}")

        try:
            idle, total = await run_in_thread(_read_cpu_jiffies, self._proc_stat_path)
        except Exception as exc:  # BaseCheck.run() must never raise
            # `CancelledError` is a `BaseException`, so external cancellation
            # still propagates past this handler as the scheduler requires.
            log.warning("check.degraded", check=self.name, error=str(exc))
            # The full message can embed the configured path and raw file
            # content, so it stays in the structured log; the result carries
            # only the bounded exception type.
            return CheckResult(ok=False, error=type(exc).__name__)

        if self._prev is None:
            self._prev = (idle, total)
            return CheckResult(ok=True, metrics={}, labels={})

        prev_idle, prev_total = self._prev
        self._prev = (idle, total)
        total_delta = total - prev_total
        idle_delta = idle - prev_idle

        if total_delta <= 0 or idle_delta < 0 or idle_delta > total_delta:
            # Monotonic kernel counters went backwards or became mutually
            # inconsistent — a reboot, CPU hotplug, or a namespaced `/proc`
            # being swapped underneath us. The baseline above is already
            # refreshed, so skip this interval instead of reporting a clamped
            # utilization that would look like a real measurement.
            log.info(
                "check.counter_reset",
                check=self.name,
                total_delta=total_delta,
                idle_delta=idle_delta,
            )
            return CheckResult(ok=True, metrics={}, labels={})

        utilization = 1.0 - (idle_delta / total_delta)
        return CheckResult(ok=True, metrics={"cpu_utilization_ratio": utilization}, labels={})
