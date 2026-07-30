"""Tests for collector.checks.host_disk — disk usage check."""
from __future__ import annotations

import asyncio
import shutil
import time
from collections import namedtuple

import pytest
from collector.checks.host_disk import HostDiskCheck, _disk_used_ratio

_Usage = namedtuple("_Usage", ["total", "used", "free"])


class TestPathValidation:
    @pytest.mark.parametrize(
        "path", ["", "  ", " /mnt ", "/mnt ", "/mnt\x00", "/mnt\nreboot", "/mnt\ttab"]
    )
    def test_rejects_malformed_path(self, settings, path):
        with pytest.raises(ValueError, match="path"):
            HostDiskCheck(settings, meter=None, path=path)

    @pytest.mark.parametrize("path", ["/", "/var/log", "C:\\", "/mnt/data-01"])
    def test_accepts_plausible_paths(self, settings, path):
        assert HostDiskCheck(settings, meter=None, path=path).path == path

    async def test_malformed_path_never_reaches_the_filesystem(self, settings, monkeypatch):
        def _explode(path):  # pragma: no cover — must never run
            raise AssertionError("disk_usage called with an unvalidated path")

        monkeypatch.setattr("collector.checks.host_disk.shutil.disk_usage", _explode)
        with pytest.raises(ValueError):
            HostDiskCheck(settings, meter=None, path="/mnt\nreboot")


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

    def test_negative_used_raises(self, monkeypatch):
        monkeypatch.setattr(shutil, "disk_usage", lambda path: _Usage(100, -1, 101))
        with pytest.raises(ValueError, match="negative"):
            _disk_used_ratio("/")

    def test_used_exceeding_total_raises(self, monkeypatch):
        # A lying container runtime. Clamping this to 1.0 would report a
        # full-but-plausible disk instead of an unusable reading.
        monkeypatch.setattr(shutil, "disk_usage", lambda path: _Usage(100, 200, 0))
        with pytest.raises(ValueError, match="exceeds total"):
            _disk_used_ratio("/")

    def test_full_disk_reads_as_exactly_one(self, monkeypatch):
        monkeypatch.setattr(shutil, "disk_usage", lambda path: _Usage(100, 100, 0))
        assert _disk_used_ratio("/") == pytest.approx(1.0)

    def test_error_messages_never_embed_the_path(self, monkeypatch):
        monkeypatch.setattr(shutil, "disk_usage", lambda path: _Usage(0, 0, 0))
        with pytest.raises(ValueError) as excinfo:
            _disk_used_ratio("/srv/customer-a/private")
        assert "customer-a" not in str(excinfo.value)


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
        assert result.error == "FileNotFoundError"

    async def test_permission_denied_never_raises(self, settings, monkeypatch):
        def denied(path):  # pylint: disable=unused-argument
            raise PermissionError("Permission denied")

        monkeypatch.setattr("collector.checks.host_disk.shutil.disk_usage", denied)
        check = HostDiskCheck(settings, meter=None, path="/some/path")
        result = await check.run()

        assert result.ok is False
        # Bounded: the exception type only. The message may embed the mount
        # path, so it goes to the structured log instead.
        assert result.error == "PermissionError"

    async def test_configured_path_never_reaches_the_result(self, settings, monkeypatch):
        monkeypatch.setattr(
            "collector.checks.host_disk.shutil.disk_usage", lambda path: _Usage(0, 0, 0)
        )
        check = HostDiskCheck(settings, meter=None, path="/srv/customer-a/private")

        result = await check.run()

        assert "customer-a" not in result.error
        assert result.labels == {}

    @pytest.mark.parametrize(
        "usage", [_Usage(0, 0, 0), _Usage(-1, 0, 0), _Usage(100, -1, 101), _Usage(100, 200, 0)]
    )
    async def test_implausible_usage_fails_closed(self, settings, monkeypatch, usage):
        monkeypatch.setattr(
            "collector.checks.host_disk.shutil.disk_usage", lambda path: usage
        )
        check = HostDiskCheck(settings, meter=None, path="/some/path")

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {}
        assert result.error == "ValueError"

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
