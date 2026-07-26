"""Tests for collector.scheduler — task ordering, interval accuracy, exception
isolation, and stop_event-driven shutdown."""
from __future__ import annotations

import asyncio
import time

import pytest

from collector.scheduler import CheckTask, run_scheduler


async def test_empty_tasks_raises():
    with pytest.raises(ValueError):
        await run_scheduler([])


async def test_runs_earliest_next_run_first():
    calls: list[str] = []
    now = time.monotonic()

    async def fire(name: str) -> None:
        calls.append(name)

    tasks = [
        CheckTask(next_run=now + 10, interval_s=10, coro_fn=lambda: fire("late"), name="late"),
        CheckTask(next_run=now, interval_s=10, coro_fn=lambda: fire("early"), name="early"),
    ]
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop_event.set)
    await run_scheduler(tasks, stop_event=stop_event)

    assert calls == ["early"]


async def test_interval_accuracy_fires_repeatedly():
    calls: list[float] = []
    now = time.monotonic()

    async def tick() -> None:
        calls.append(time.monotonic())

    tasks = [CheckTask(next_run=now, interval_s=0.02, coro_fn=tick, name="tick")]
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.13, stop_event.set)
    await run_scheduler(tasks, stop_event=stop_event)
    # give fire-and-forget tasks created just before stop a moment to land
    await asyncio.sleep(0.01)

    assert len(calls) >= 4
    gaps = [b - a for a, b in zip(calls, calls[1:], strict=False)]
    assert all(gap > 0.005 for gap in gaps)


async def test_exception_in_one_task_does_not_stop_others():
    healthy_calls: list[int] = []
    now = time.monotonic()

    async def broken() -> None:
        raise RuntimeError("boom")

    async def healthy() -> None:
        healthy_calls.append(1)

    tasks = [
        CheckTask(next_run=now, interval_s=0.02, coro_fn=broken, name="broken"),
        CheckTask(next_run=now, interval_s=0.02, coro_fn=healthy, name="healthy"),
    ]
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.13, stop_event.set)
    await run_scheduler(tasks, stop_event=stop_event)
    await asyncio.sleep(0.01)

    assert len(healthy_calls) >= 4


async def test_stop_event_returns_promptly_when_nothing_due_soon():
    now = time.monotonic()

    async def never() -> None:
        pass

    tasks = [CheckTask(next_run=now + 3600, interval_s=3600, coro_fn=never, name="never")]
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.02, stop_event.set)

    start = time.monotonic()
    await run_scheduler(tasks, stop_event=stop_event)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5
