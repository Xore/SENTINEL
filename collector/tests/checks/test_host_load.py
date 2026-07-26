"""Tests for collector.checks.host_load — system load average check."""
from __future__ import annotations

import asyncio
import os

from collector.checks.host_load import HostLoadCheck


class TestHostLoadCheck:
    async def test_run_ok_result(self, settings, monkeypatch):
        monkeypatch.setattr(os, "getloadavg", lambda: (0.5, 0.75, 1.0))
        check = HostLoadCheck(settings, meter=None)

        result = await check.run()

        assert result.ok is True
        assert result.metrics == {"load1": 0.5, "load5": 0.75, "load15": 1.0}
        assert result.error is None

    async def test_oserror_never_raises(self, settings, monkeypatch):
        def raising():
            raise OSError("load average unobtainable")

        monkeypatch.setattr(os, "getloadavg", raising)
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
