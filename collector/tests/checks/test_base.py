"""Tests for collector.checks — BaseCheck ABC and CheckResult."""
from __future__ import annotations

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
