"""Async priority-queue task scheduler — replaces the Go goroutine pool.

Each `CheckTask` runs its coroutine on its own interval. Tasks are ordered by
`next_run` in a min-heap so the scheduler always sleeps until the next thing
is due, rather than polling. The sample loop in `COLLECTOR-V2-REFACTOR.md`
§5 fires tasks with a bare `asyncio.create_task` and silently drops any
exception the task raises; this adds a done-callback so a broken check is
logged instead of vanishing, and never stops the scheduler or other tasks.
"""
from __future__ import annotations

import asyncio
import functools
import heapq
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger()


@dataclass(order=True)
class CheckTask:
    next_run: float
    interval_s: float = field(compare=False)
    coro_fn: Callable[[], Coroutine[Any, Any, Any]] = field(compare=False)
    name: str = field(compare=False)


def _log_task_outcome(task_name: str, fut: asyncio.Task[Any]) -> None:
    if fut.cancelled():
        return
    exc = fut.exception()
    if exc is not None:
        log.error("scheduler.task_failed", task=task_name, error=str(exc))


async def run_scheduler(
    tasks: list[CheckTask], *, stop_event: asyncio.Event | None = None
) -> None:
    """Run `tasks` forever (or until `stop_event` is set), each on its own interval.

    Every due task is fired via `asyncio.create_task` and never awaited
    directly — a slow or failing task cannot delay other tasks or the
    scheduler loop itself. `tasks` must be non-empty; there is nothing to
    wait on otherwise.
    """
    if not tasks:
        raise ValueError("run_scheduler requires at least one CheckTask")

    heap = list(tasks)
    heapq.heapify(heap)

    while stop_event is None or not stop_event.is_set():
        now = time.monotonic()
        due = heap[0]
        if due.next_run > now:
            sleep_for = due.next_run - now
            if stop_event is not None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=sleep_for)
                except TimeoutError:
                    pass
                continue
            await asyncio.sleep(sleep_for)
            continue

        heapq.heappop(heap)
        fired = asyncio.create_task(due.coro_fn(), name=due.name)
        fired.add_done_callback(functools.partial(_log_task_outcome, due.name))
        due.next_run = now + due.interval_s
        heapq.heappush(heap, due)
