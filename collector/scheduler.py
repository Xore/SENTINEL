"""Cycle-batching, `asyncio.TaskGroup`-based check scheduler.

Every cycle: collect all checks whose `next_run_at <= now`, run them
concurrently inside an `asyncio.TaskGroup`, then sleep for the remainder of
`cycle_s`. A per-check timeout and exception containment (`_run_one`) mean a
single broken or hanging check is recorded as one failed run rather than
cancelling its siblings or crashing the scheduler — `BaseCheck.run()` must
never raise, but this is the safety net for bugs that violate that contract.
`asyncio.CancelledError` still propagates through `TaskGroup` for prompt
shutdown. See `docs/guides/OPUS-AGENT-GUIDE-V2.md` §5.8 and
`docs/contracts/METRICS.md` for the canonical run/duration telemetry emitted
here.
"""
from __future__ import annotations

import asyncio
import heapq
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult

log = structlog.get_logger()

# Scheduler default; tests override with a small value to exercise the
# timeout path deterministically without a real 30s wait.
DEFAULT_CHECK_TIMEOUT_S = 30.0


@dataclass(order=True)
class CheckTask:
    """Priority-queue entry: lower `next_run_at` = higher urgency."""

    next_run_at: float
    priority: int
    check: BaseCheck = field(compare=False)
    interval_s: float = field(compare=False)


class _SchedulerMetrics:
    """Canonical scheduler telemetry (`docs/contracts/METRICS.md`'s Phase 1
    families). `meter=None` (unit tests constructing checks directly, or a
    collector run before enrollment) makes every method a no-op.
    """

    def __init__(self, meter: Meter | None) -> None:
        self._check_runs = (
            meter.create_counter(
                "sentinel_collector_check_runs_total",
                description="Check runs by outcome",
                unit="1",
            )
            if meter is not None
            else None
        )
        self._check_duration = (
            meter.create_histogram(
                "sentinel_collector_check_duration_seconds",
                description="Per-check run duration",
                unit="s",
            )
            if meter is not None
            else None
        )
        self._cycle_duration = (
            meter.create_histogram(
                "sentinel_collector_cycle_duration_seconds",
                description="Scheduler cycle duration",
                unit="s",
            )
            if meter is not None
            else None
        )

    def record_check(self, check: str, outcome: str, duration_s: float) -> None:
        if self._check_runs is not None:
            self._check_runs.add(1, attributes={"check": check, "outcome": outcome})
        if self._check_duration is not None:
            self._check_duration.record(duration_s, attributes={"check": check})

    def record_cycle(self, duration_s: float) -> None:
        if self._cycle_duration is not None:
            self._cycle_duration.record(duration_s)


async def _run_one(
    task: CheckTask, *, check_timeout_s: float, metrics: _SchedulerMetrics
) -> CheckResult:
    """Run a single check, containing a timeout or any exception that
    escapes `BaseCheck.run()`'s never-raise contract as one failed run
    instead of letting it propagate into the surrounding `TaskGroup` — a
    broken or hanging check must not cancel its siblings or crash the
    scheduler. `asyncio.CancelledError` is not caught here, so shutdown
    cancellation still propagates immediately.
    """
    start = time.monotonic()
    outcome = "ok"
    try:
        async with asyncio.timeout(check_timeout_s):
            result = await task.check.run_with_semaphore()
        if not result.ok:
            outcome = "failed"
            log.warning("scheduler.check_failed", check=task.check.name, error=result.error)
    except TimeoutError:
        outcome = "timeout"
        result = CheckResult(ok=False, error=f"exceeded {check_timeout_s}s timeout")
        log.warning("scheduler.check_timeout", check=task.check.name, timeout_s=check_timeout_s)
    except Exception as exc:  # contract safety net — BaseCheck.run() must never raise
        outcome = "exception"
        result = CheckResult(ok=False, error=str(exc))
        log.error("scheduler.check_exception", check=task.check.name, error=str(exc))

    metrics.record_check(task.check.name, outcome, time.monotonic() - start)
    return result


async def run_scheduler(
    checks: Sequence[BaseCheck],
    *,
    cycle_s: float = 30.0,
    check_timeout_s: float = DEFAULT_CHECK_TIMEOUT_S,
    stop_event: asyncio.Event | None = None,
    meter: Meter | None = None,
) -> None:
    """Main scheduler loop.

    Each cycle collects every check due to run, runs them concurrently
    inside a `TaskGroup`, then sleeps for the remainder of `cycle_s`. A
    check's own `interval_s` (not `cycle_s`) determines when it next
    becomes due, so mixed intervals (e.g. a 10s ICMP check alongside a 60s
    SNMP walk) are handled correctly across cycles. Each check is bounded by
    `check_timeout_s` and any exception it raises is contained as a failed
    run (see `_run_one`) — one broken or hanging check never cancels its
    siblings or stops the scheduler. `meter` (`None` in most unit tests)
    emits the canonical run/duration telemetry from `docs/contracts/METRICS.md`.
    """
    metrics = _SchedulerMetrics(meter)
    now = time.monotonic()
    heap: list[CheckTask] = [
        CheckTask(
            next_run_at=now,
            priority=i,
            check=c,
            interval_s=getattr(c, "interval_s", cycle_s),
        )
        for i, c in enumerate(checks)
        if c.is_enabled()
    ]
    heapq.heapify(heap)

    while stop_event is None or not stop_event.is_set():
        cycle_start = time.monotonic()
        due: list[CheckTask] = []

        while heap and heap[0].next_run_at <= cycle_start:
            due.append(heapq.heappop(heap))

        if due:
            # _run_one contains any timeout/exception per check, so a broken
            # or hanging check can never make this TaskGroup raise —
            # CancelledError (shutdown) is the only thing that still
            # propagates through it.
            async with asyncio.TaskGroup() as tg:
                for task in due:
                    tg.create_task(
                        _run_one(task, check_timeout_s=check_timeout_s, metrics=metrics),
                        name=task.check.name,
                    )
            for task in due:
                task.next_run_at = cycle_start + task.interval_s
                heapq.heappush(heap, task)

        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, cycle_s - elapsed)
        metrics.record_cycle(elapsed)
        log.debug("scheduler.cycle", checks_run=len(due), elapsed_ms=round(elapsed * 1000, 1))

        if stop_event is None:
            await asyncio.sleep(sleep_for)
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=sleep_for)
        except TimeoutError:
            pass
