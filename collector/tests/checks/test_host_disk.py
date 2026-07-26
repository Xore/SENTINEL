"""Tests for collector.checks.host_disk — disk usage check."""
from __future__ import annotations

import asyncio
import shutil
import time
from collections import namedtuple

import pytest
from collector.checks.host_disk import HostDiskCheck, _disk_used_ratio

_Usage = namedtuple("_Usage", ["total", "used", "free"])


class TestDiskUsedRatio:
    def test_computes_ratio_from_real_path(self, tmp_path):
        ratio = _disk_used_ratio(str(tmp_path))
        assert 0.0 <= ratio <= 1.0

    def test_missing_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _disk_used_ratio(str(tmp_path / "nope"))

    def test_non_positive_total_raises(self, monkeypatch):
        monkeypatch.setattr(shutil, "disk_usage", lambda path: _Usage(0, 0, 0))
        with pytest.raises(ValueError, match="non-positive"):
            _disk_used_ratio("/")


class TestHostDiskCheck:
    async def test_run_ok_result(self, settings, tmp_path):
        check = HostDiskCheck(settings, meter=None, path=str(tmp_path))
        result = await check.run()

        assert result.ok is True
        assert 0.0 <= result.metrics["disk_used_ratio"] <= 1.0

    async def test_missing_path_never_raises(self, settings, tmp_path):
        check = HostDiskCheck(settings, meter=None, path=str(tmp_path / "nope"))
        result = await check.run()
        assert result.ok is False
        assert result.error is not None

    async def test_permission_denied_never_raises(self, settings, monkeypatch):
        def denied(path):  # pylint: disable=unused-argument
            raise PermissionError("Permission denied")

        monkeypatch.setattr("collector.checks.host_disk.shutil.disk_usage", denied)
        check = HostDiskCheck(settings, meter=None, path="/some/path")
        result = await check.run()

        assert result.ok is False
        assert "Permission denied" in result.error

    async def test_zero_total_never_raises(self, settings, monkeypatch):
        monkeypatch.setattr(
            "collector.checks.host_disk.shutil.disk_usage", lambda path: _Usage(0, 0, 0)
        )
        check = HostDiskCheck(settings, meter=None, path="/some/path")
        result = await check.run()
        assert result.ok is False

    async def test_slow_call_is_cancellable(self, settings, monkeypatch):
        def slow_ratio(path):  # pylint: disable=unused-argument
            time.sleep(1.5)
            return 0.0  # pragma: no cover — never reached

        monkeypatch.setattr("collector.checks.host_disk._disk_used_ratio", slow_ratio)
        check = HostDiskCheck(settings, meter=None)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(check.run(), timeout=0.2)

    def test_semaphore_stored(self, settings):
        sem = asyncio.Semaphore(3)
        check = HostDiskCheck(settings, meter=None, semaphore=sem)
        assert check.semaphore is sem

    def test_default_path_is_root(self, settings):
        check = HostDiskCheck(settings, meter=None)
        assert check.path == "/"
