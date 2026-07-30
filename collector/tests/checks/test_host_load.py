"""Tests for collector.checks.host_load — system load average check."""

from __future__ import annotations

import asyncio
import os

import pytest
from collector.checks.host_load import HostLoadCheck


class TestHostLoadCheck:
    async def test_run_ok_result(self, settings, monkeypatch):
        monkeypatch.setattr(os, "getloadavg", lambda: (0.5, 0.75, 1.0), raising=False)
        check = HostLoadCheck(settings, meter=None)

        result = await check.run()

        assert result.ok is True
        assert result.metrics == {"load1": 0.5, "load5": 0.75, "load15": 1.0}
        assert result.error is None

    async def test_integer_averages_are_coerced_to_float(self, settings, monkeypatch):
        monkeypatch.setattr(os, "getloadavg", lambda: (0, 1, 2), raising=False)
        check = HostLoadCheck(settings, meter=None)

        result = await check.run()

        assert result.ok is True
        assert all(isinstance(value, float) for value in result.metrics.values())

    @pytest.mark.parametrize(
        "averages",
        [
            (float("nan"), 0.5, 0.5),
            (0.5, float("inf"), 0.5),
            (0.5, 0.5, float("-inf")),
            (-0.1, 0.5, 0.5),
        ],
    )
    async def test_implausible_averages_fail_closed(self, settings, monkeypatch, averages):
        # A NaN would silently poison every downstream aggregate; a negative
        # load average is not a quantity the kernel can produce.
        monkeypatch.setattr(os, "getloadavg", lambda: averages, raising=False)
        check = HostLoadCheck(settings, meter=None)

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {}
        assert "implausible load average" in result.error

    @pytest.mark.parametrize(
        "getloadavg",
        [
            lambda: (1.0, 2.0),  # too few values to unpack
            lambda: (1.0, 2.0, 3.0, 4.0),  # too many
            lambda: ("a", "b", "c"),  # not convertible to float
            lambda: None,  # not iterable at all
        ],
    )
    async def test_non_oserror_failures_never_escape_run(self, settings, monkeypatch, getloadavg):
        # `getloadavg` is resolved dynamically, so unpacking and conversion
        # failures must become failed runs rather than escaping into the
        # scheduler — `run()` may never raise.
        monkeypatch.setattr(os, "getloadavg", getloadavg, raising=False)
        check = HostLoadCheck(settings, meter=None)

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {}

    async def test_non_callable_attribute_is_rejected_before_use(self, settings, monkeypatch):
        monkeypatch.setattr(os, "getloadavg", "not callable", raising=False)
        check = HostLoadCheck(settings, meter=None)

        result = await check.run()

        assert result.ok is False
        assert "unavailable" in result.error

    async def test_oserror_never_raises(self, settings, monkeypatch):
        def raising():
            raise OSError("load average unobtainable")

        monkeypatch.setattr(os, "getloadavg", raising, raising=False)
        check = HostLoadCheck(settings, meter=None)

        result = await check.run()

        assert result.ok is False
        assert "unobtainable" in result.error

    async def test_missing_attribute_never_raises(self, settings, monkeypatch):
        # Simulates a platform (e.g. Windows) where os.getloadavg doesn't exist.
        monkeypatch.delattr(os, "getloadavg", raising=False)
        check = HostLoadCheck(settings, meter=None)

        result = await check.run()

        assert result.ok is False
        assert result.error is not None

    def test_semaphore_stored(self, settings):
        sem = asyncio.Semaphore(3)
        check = HostLoadCheck(settings, meter=None, semaphore=sem)
        assert check.semaphore is sem
