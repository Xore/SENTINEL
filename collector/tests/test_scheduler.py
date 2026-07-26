"""Tests for collector.scheduler — TaskGroup-based cycle scheduling."""
from __future__ import annotations

import asyncio
import time

import pytest

from collector.checks import BaseCheck, CheckResult
from collector.scheduler import run_scheduler


class _CountingCheck(BaseCheck):
    name = "counting"
    scan_level = 1

    def __init__(self, settings, *, interval_s: float = 0.02, enabled: bool = True):
        super().__init__(settings, meter=None)
        self.interval_s = interval_s
        self.call_count = 0
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    async def run(self) -> CheckResult:
        self.call_count += 1
        return CheckResult(ok=True)


class _BrokenCheck(BaseCheck):
    name = "broken"
    scan_level = 1
    interval_s = 1.0

    def is_enabled(self) -> bool:
        return True

    async def run(self) -> CheckResult:
        raise RuntimeError("unexpected")


async def test_empty_checks_list_stops_on_event():
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.03, stop_event.set)
    start = time.monotonic()
    await run_scheduler([], cycle_s=0.01, stop_event=stop_event)
    assert time.monotonic() - start < 0.5


async def test_disabled_check_never_runs(settings):
    check = _CountingCheck(settings, enabled=False)
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop_event.set)
    await run_scheduler([check], cycle_s=0.01, stop_event=stop_event)
    assert check.call_count == 0


async def test_multiple_due_checks_run_in_same_cycle(settings):
    a = _CountingCheck(settings, interval_s=10.0)
    b = _CountingCheck(settings, interval_s=10.0)
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.03, stop_event.set)
    await run_scheduler([a, b], cycle_s=0.01, stop_event=stop_event)
    assert a.call_count == 1
    assert b.call_count == 1


async def test_interval_accuracy_fires_repeatedly(settings):
    check = _CountingCheck(settings, interval_s=0.02)
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.13, stop_event.set)
    await run_scheduler([check], cycle_s=0.01, stop_event=stop_event)
    assert check.call_count >= 4


async def test_exception_escaping_run_raises_exception_group(settings):
    check = _BrokenCheck(settings, meter=None)
    with pytest.raises(ExceptionGroup) as exc_info:
        await run_scheduler([check], cycle_s=0.0)
    assert isinstance(exc_info.value.exceptions[0], RuntimeError)


async def test_broken_check_mixed_with_healthy_still_raises(settings):
    """Documents TaskGroup's structured-concurrency behaviour: a check that
    bypasses the BaseCheck never-raise contract cancels every check
    scheduled in the same cycle, not just itself — this is intentional
    (docs/guides/OPUS-AGENT-GUIDE-V2.md §5.8), not a bug to work around.
    """
    broken = _BrokenCheck(settings, meter=None)
    healthy = _CountingCheck(settings, interval_s=10.0)
    with pytest.raises(ExceptionGroup):
        await run_scheduler([broken, healthy], cycle_s=0.0)


async def test_stop_event_already_set_runs_zero_cycles(settings):
    check = _CountingCheck(settings)
    stop_event = asyncio.Event()
    stop_event.set()
    await run_scheduler([check], cycle_s=0.01, stop_event=stop_event)
    assert check.call_count == 0
