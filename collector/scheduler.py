"""Cycle-batching, `asyncio.TaskGroup`-based check scheduler.

Every cycle: collect all checks whose `next_run_at <= now`, run them
concurrently inside an `asyncio.TaskGroup`, then sleep for the remainder of
`cycle_s`. `TaskGroup` gives structured concurrency — an exception that
escapes a check's `BaseCheck.run()` contract (which must never raise)
surfaces immediately as an `ExceptionGroup` instead of being silently
dropped. See `docs/guides/OPUS-AGENT-GUIDE-V2.md` §5.8.
"""
from __future__ import annotations

import asyncio
import heapq
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import structlog

from collector.checks import BaseCheck, CheckResult

log = structlog.get_logger()


@dataclass(order=True)
class CheckTask:
    """Priority-queue entry: lower `next_run_at` = higher urgency."""

    next_run_at: float
    priority: int
    check: BaseCheck = field(compare=False)
    interval_s: float = field(compare=False)


async def _run_one(task: CheckTask) -> CheckResult:
    """Run a single check; `BaseCheck.run()` itself must never raise."""
    result = await task.check.run_with_semaphore()
    if not result.ok:
        log.warning("scheduler.check_failed", check=task.check.name, error=result.error)
    return result


async def run_scheduler(
    checks: Sequence[BaseCheck],
    *,
    cycle_s: float = 30.0,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Main scheduler loop.

    Each cycle collects every check due to run, runs them concurrently
    inside a `TaskGroup`, then sleeps for the remainder of `cycle_s`. A
    check's own `interval_s` (not `cycle_s`) determines when it next
    becomes due, so mixed intervals (e.g. a 10s ICMP check alongside a 60s
    SNMP walk) are handled correctly across cycles.
    """
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
            # Structured concurrency: an exception escaping BaseCheck.run()'s
            # never-raise contract cancels siblings and re-raises as
            # ExceptionGroup instead of vanishing.
            async with asyncio.TaskGroup() as tg:
                for task in due:
                    tg.create_task(_run_one(task), name=task.check.name)
            for task in due:
                task.next_run_at = cycle_start + task.interval_s
                heapq.heappush(heap, task)

        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, cycle_s - elapsed)
        log.debug("scheduler.cycle", checks_run=len(due), elapsed_ms=round(elapsed * 1000, 1))

        if stop_event is None:
            await asyncio.sleep(sleep_for)
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=sleep_for)
        except TimeoutError:
            pass
