"""Tests for collector.scheduler — TaskGroup-based cycle scheduling."""
from __future__ import annotations

import asyncio
import time

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


async def test_exception_escaping_run_is_contained_not_raised(settings):
    # S2-01: a check that bypasses BaseCheck's never-raise contract must be
    # contained as one failed run, not crash the scheduler.
    check = _BrokenCheck(settings, meter=None)
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.03, stop_event.set)
    await run_scheduler([check], cycle_s=0.01, stop_event=stop_event)  # must not raise


async def test_broken_check_does_not_cancel_healthy_sibling(settings):
    """S2-01 sibling isolation: a check that bypasses BaseCheck's never-raise
    contract must not cancel or block other checks scheduled in the same
    cycle. Superseded the old ExceptionGroup-propagation behavior
    (docs/guides/OPUS-AGENT-GUIDE-V2.md §5.8 predates this fix).
    """
    broken = _BrokenCheck(settings, meter=None)
    healthy = _CountingCheck(settings, interval_s=0.02)
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.13, stop_event.set)
    await run_scheduler([broken, healthy], cycle_s=0.01, stop_event=stop_event)
    assert healthy.call_count >= 4


class _HangingCheck(BaseCheck):
    name = "hanging"
    scan_level = 1
    interval_s = 1.0

    def is_enabled(self) -> bool:
        return True

    async def run(self) -> CheckResult:
        await asyncio.sleep(10.0)
        return CheckResult(ok=True)  # pragma: no cover — never reached


async def test_hanging_check_is_timed_out_not_leaked(settings):
    check = _HangingCheck(settings, meter=None)
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop_event.set)
    start = time.monotonic()
    await run_scheduler(
        [check], cycle_s=0.01, check_timeout_s=0.02, stop_event=stop_event
    )
    # Bounded by the 0.02s check timeout, not the check's real 10s sleep.
    assert time.monotonic() - start < 1.0


async def test_timed_out_check_does_not_block_healthy_sibling(settings):
    hanging = _HangingCheck(settings, meter=None)
    healthy = _CountingCheck(settings, interval_s=0.02)
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.13, stop_event.set)
    await run_scheduler(
        [hanging, healthy], cycle_s=0.01, check_timeout_s=0.02, stop_event=stop_event
    )
    assert healthy.call_count >= 4


async def test_no_pending_tasks_after_shutdown(settings):
    check = _CountingCheck(settings, interval_s=0.02)
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop_event.set)

    before = asyncio.all_tasks() - {asyncio.current_task()}
    await run_scheduler([check], cycle_s=0.01, stop_event=stop_event)
    after = asyncio.all_tasks() - {asyncio.current_task()}

    assert after <= before


class _FakeCounter:
    def __init__(self):
        self.calls: list[tuple[float, dict]] = []

    def add(self, amount, attributes=None):
        self.calls.append((amount, attributes or {}))


class _FakeHistogram:
    def __init__(self):
        self.calls: list[tuple[float, dict]] = []

    def record(self, amount, attributes=None):
        self.calls.append((amount, attributes or {}))


class _FakeMeter:
    def __init__(self):
        self.instruments: dict[str, object] = {}

    # description is unused but must stay in the signature to duck-type the
    # real opentelemetry Meter.create_counter/create_histogram calls.
    def create_counter(self, name, description=None, unit=None):  # pylint: disable=unused-argument
        instrument = _FakeCounter()
        self.instruments[name] = (instrument, unit)
        return instrument

    def create_histogram(self, name, description=None, unit=None):  # pylint: disable=unused-argument
        instrument = _FakeHistogram()
        self.instruments[name] = (instrument, unit)
        return instrument


async def test_canonical_metrics_names_units_and_labels(settings):
    meter = _FakeMeter()
    ok_check = _CountingCheck(settings, interval_s=10.0)
    broken = _BrokenCheck(settings, meter=None)
    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.03, stop_event.set)

    await run_scheduler([ok_check, broken], cycle_s=0.01, stop_event=stop_event, meter=meter)

    runs_instrument, runs_unit = meter.instruments["sentinel_collector_check_runs_total"]
    duration_instrument, duration_unit = meter.instruments[
        "sentinel_collector_check_duration_seconds"
    ]
    cycle_instrument, cycle_unit = meter.instruments["sentinel_collector_cycle_duration_seconds"]

    assert runs_unit == "1"
    assert duration_unit == "s"
    assert cycle_unit == "s"

    outcomes = {(attrs["check"], attrs["outcome"]) for _, attrs in runs_instrument.calls}
    assert ("counting", "ok") in outcomes
    assert ("broken", "exception") in outcomes
    # error text must never appear as a metric attribute value.
    for _, attrs in runs_instrument.calls:
        assert set(attrs) <= {"check", "outcome"}

    assert {attrs["check"] for _, attrs in duration_instrument.calls} == {"counting", "broken"}
    assert len(cycle_instrument.calls) >= 1


async def test_stop_event_already_set_runs_zero_cycles(settings):
    check = _CountingCheck(settings)
    stop_event = asyncio.Event()
    stop_event.set()
    await run_scheduler([check], cycle_s=0.01, stop_event=stop_event)
    assert check.call_count == 0
