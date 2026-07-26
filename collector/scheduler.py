"""Cycle-batching, `asyncio.TaskGroup`-based check scheduler.

Every cycle: collect all checks whose `next_run_at <= now`, run them
concurrently inside an `asyncio.TaskGroup`, then sleep for the remainder of
`cycle_s`. A per-check timeout and exception containment (`_run_one`) mean a
single broken or hanging check is recorded as one failed run rather than
cancelling its siblings or crashing the scheduler — `BaseCheck.run()` must
never raise, but this is the safety net for bugs that violate that contract.
The in-flight batch also races against `stop_event` (`_run_batch_or_stop`) so
a hanging check can't delay a graceful shutdown for the full
`check_timeout_s`; `asyncio.CancelledError` from true task cancellation (not
just `stop_event`) still propagates for prompt shutdown. See
`docs/guides/OPUS-AGENT-GUIDE-V2.md` §5.8 and `docs/contracts/METRICS.md` for
the canonical run/duration telemetry emitted here.
"""
from __future__ import annotations

import asyncio
import contextlib
import heapq
import math
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


async def _run_batch(
    due: list[CheckTask], *, check_timeout_s: float, metrics: _SchedulerMetrics
) -> None:
    async with asyncio.TaskGroup() as tg:
        for task in due:
            tg.create_task(
                _run_one(task, check_timeout_s=check_timeout_s, metrics=metrics),
                name=task.check.name,
            )


async def _run_batch_or_stop(
    due: list[CheckTask],
    *,
    check_timeout_s: float,
    metrics: _SchedulerMetrics,
    stop_event: asyncio.Event | None,
) -> None:
    """Run one cycle's due checks, but return promptly if `stop_event` is
    set mid-batch instead of waiting out up to `check_timeout_s` per check.
    Without this, a single hanging check could delay a graceful shutdown for
    the full default 30s (Codex review 1). A check cancelled this way is not
    recorded as a failed/timeout outcome: `CancelledError` propagates past
    `_run_one`'s `except TimeoutError`/`except Exception` clauses untouched,
    so its metrics call is simply never reached.
    """
    if stop_event is None:
        await _run_batch(due, check_timeout_s=check_timeout_s, metrics=metrics)
        return

    batch_task = asyncio.ensure_future(
        _run_batch(due, check_timeout_s=check_timeout_s, metrics=metrics)
    )
    stop_wait = asyncio.ensure_future(stop_event.wait())
    try:
        done, _pending = await asyncio.wait(
            {batch_task, stop_wait}, return_when=asyncio.FIRST_COMPLETED
        )
    except asyncio.CancelledError:
        # This coroutine's own task was cancelled (e.g. by the collector's
        # outer TaskGroup, not by stop_event) — not our cancellation to own;
        # clean up both waiters and propagate.
        batch_task.cancel()
        stop_wait.cancel()
        await asyncio.gather(batch_task, stop_wait, return_exceptions=True)
        raise

    if batch_task in done:
        stop_wait.cancel()
        await asyncio.gather(stop_wait, return_exceptions=True)
        batch_task.result()
        return

    log.info("scheduler.batch_cancelled_for_shutdown", checks_pending=len(due))
    batch_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await batch_task


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
    `check_timeout_s` (must be positive and finite) and any exception it
    raises is contained as a failed run (see `_run_one`) — one broken or
    hanging check never cancels its siblings or stops the scheduler. An
    in-flight batch also races against `stop_event` so shutdown doesn't wait
    out a hanging check (see `_run_batch_or_stop`). `meter` (`None` in most
    unit tests) emits the canonical run/duration telemetry from
    `docs/contracts/METRICS.md`.
    """
    if not math.isfinite(check_timeout_s) or check_timeout_s <= 0:
        raise ValueError(f"check_timeout_s must be positive and finite, got {check_timeout_s!r}")

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
            await _run_batch_or_stop(
                due, check_timeout_s=check_timeout_s, metrics=metrics, stop_event=stop_event
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
