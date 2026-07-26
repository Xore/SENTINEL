"""Tests for collector.checks — BaseCheck ABC and CheckResult."""
from __future__ import annotations

import asyncio

import pytest
from collector.checks import BaseCheck, CheckResult
from collector.config import load_settings


class _DummyCheck(BaseCheck):
    name = "dummy"
    scan_level = 2

    async def run(self) -> CheckResult:
        return CheckResult(ok=True, metrics={"dummy_ms": 1.0}, labels={"target": "x"})


def test_cannot_instantiate_base_check_directly(settings):
    with pytest.raises(TypeError):
        BaseCheck(settings, meter=None)


async def test_run_returns_check_result(settings):
    check = _DummyCheck(settings, meter=None)
    result = await check.run()
    assert result.ok is True
    assert result.metrics == {"dummy_ms": 1.0}
    assert result.labels == {"target": "x"}
    assert result.error is None


def test_is_enabled_true_when_scan_level_at_or_below_max():
    check = _DummyCheck(load_settings(collector_id="c", scan_level_max=2), meter=None)
    assert check.is_enabled() is True


def test_is_enabled_false_when_scan_level_above_max():
    check = _DummyCheck(load_settings(collector_id="c", scan_level_max=1), meter=None)
    assert check.is_enabled() is False


def test_check_result_defaults():
    result = CheckResult(ok=False)
    assert result.metrics == {}
    assert result.labels == {}
    assert result.error is None


def test_default_interval_s():
    assert _DummyCheck.interval_s == 30.0


async def test_run_with_semaphore_passes_through_when_none(settings):
    check = _DummyCheck(settings, meter=None)
    assert check.semaphore is None
    result = await check.run_with_semaphore()
    assert result.ok is True


async def test_run_with_semaphore_acquires_and_releases(settings):
    semaphore = asyncio.Semaphore(1)
    check = _DummyCheck(settings, meter=None, semaphore=semaphore)

    assert semaphore.locked() is False
    result = await check.run_with_semaphore()
    assert result.ok is True
    assert semaphore.locked() is False  # released after run() completes


async def test_run_with_semaphore_serializes_concurrent_calls():
    settings = load_settings(collector_id="c")
    semaphore = asyncio.Semaphore(1)
    order: list[str] = []

    class _SlowCheck(BaseCheck):
        name = "slow"
        scan_level = 1

        async def run(self) -> CheckResult:
            order.append("start")
            await asyncio.sleep(0.01)
            order.append("end")
            return CheckResult(ok=True)

    check_a = _SlowCheck(settings, meter=None, semaphore=semaphore)
    check_b = _SlowCheck(settings, meter=None, semaphore=semaphore)

    await asyncio.gather(check_a.run_with_semaphore(), check_b.run_with_semaphore())

    # With a semaphore of 1, the second call cannot start until the first ends.
    assert order == ["start", "end", "start", "end"]


async def test_default_aclose_is_a_noop(settings):
    check = _DummyCheck(settings, meter=None)
    assert await check.aclose() is None
