"""Tests for collector.checks.host_memory — Linux memory utilization check."""

from __future__ import annotations

import asyncio
import os
import time

import pytest
from collector.checks.host_memory import HostMemoryCheck, _parse_meminfo, _read_meminfo

_MEMINFO_WITH_AVAILABLE = """\
MemTotal:       10000000 kB
MemFree:         1000000 kB
MemAvailable:    4000000 kB
Buffers:          200000 kB
Cached:          800000 kB
"""

_MEMINFO_WITHOUT_AVAILABLE = """\
MemTotal:       10000000 kB
MemFree:         1000000 kB
Buffers:          200000 kB
Cached:          800000 kB
"""


class TestParseMeminfo:
    def test_parses_known_fields(self):
        fields = _parse_meminfo(_MEMINFO_WITH_AVAILABLE)
        assert fields["MemTotal"] == 10000000
        assert fields["MemAvailable"] == 4000000

    def test_rejects_non_integer_value(self):
        with pytest.raises(ValueError, match="non-integer"):
            _parse_meminfo("MemTotal:       abc kB\n")

    def test_ignores_lines_without_colon(self):
        fields = _parse_meminfo("garbage line\nMemTotal:       10000000 kB\n")
        assert fields == {"MemTotal": 10000000}

    def test_ignores_empty_value(self):
        fields = _parse_meminfo("Empty:\nMemTotal:       10000000 kB\n")
        assert fields == {"MemTotal": 10000000}


class TestReadMeminfo:
    def test_reads_real_file(self, tmp_path):
        path = tmp_path / "meminfo"
        path.write_text(_MEMINFO_WITH_AVAILABLE)
        fields = _read_meminfo(str(path))
        assert fields["MemTotal"] == 10000000

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _read_meminfo(str(tmp_path / "nope"))


class TestHostMemoryCheck:
    @pytest.fixture(autouse=True)
    def _linux_platform(self, monkeypatch):
        monkeypatch.setattr("collector.checks.host_memory.sys.platform", "linux")

    async def test_uses_mem_available_when_present(self, settings, tmp_path):
        path = tmp_path / "meminfo"
        path.write_text(_MEMINFO_WITH_AVAILABLE)
        check = HostMemoryCheck(settings, meter=None, meminfo_path=str(path))

        result = await check.run()

        assert result.ok is True
        assert result.metrics["memory_used_ratio"] == pytest.approx(1 - 4000000 / 10000000)

    async def test_falls_back_to_free_plus_buffers_plus_cached(self, settings, tmp_path):
        path = tmp_path / "meminfo"
        path.write_text(_MEMINFO_WITHOUT_AVAILABLE)
        check = HostMemoryCheck(settings, meter=None, meminfo_path=str(path))

        result = await check.run()

        assert result.ok is True
        available = 1000000 + 200000 + 800000
        assert result.metrics["memory_used_ratio"] == pytest.approx(1 - available / 10000000)

    async def test_missing_file_never_raises(self, settings, tmp_path):
        check = HostMemoryCheck(settings, meter=None, meminfo_path=str(tmp_path / "nope"))
        result = await check.run()
        assert result.ok is False
        assert result.error is not None

    async def test_missing_mem_total_never_raises(self, settings, tmp_path):
        path = tmp_path / "meminfo"
        path.write_text("MemFree:       1000000 kB\n")
        check = HostMemoryCheck(settings, meter=None, meminfo_path=str(path))
        result = await check.run()
        assert result.ok is False

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
    async def test_permission_denied_never_raises(self, settings, tmp_path):
        path = tmp_path / "meminfo"
        path.write_text(_MEMINFO_WITH_AVAILABLE)
        path.chmod(0o000)
        try:
            check = HostMemoryCheck(settings, meter=None, meminfo_path=str(path))
            result = await check.run()
            assert result.ok is False
        finally:
            path.chmod(0o644)

    async def test_unsupported_platform_reports_failure(self, settings, tmp_path, monkeypatch):
        monkeypatch.setattr("collector.checks.host_memory.sys.platform", "win32")
        check = HostMemoryCheck(settings, meter=None, meminfo_path=str(tmp_path / "meminfo"))
        result = await check.run()
        assert result.ok is False
        assert "win32" in result.error

    async def test_slow_read_is_cancellable(self, settings, monkeypatch):
        check = HostMemoryCheck(settings, meter=None)

        def slow_read(path):  # pylint: disable=unused-argument
            time.sleep(1.5)
            return {}  # pragma: no cover — never reached

        monkeypatch.setattr("collector.checks.host_memory._read_meminfo", slow_read)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(check.run(), timeout=0.2)

    def test_semaphore_stored(self, settings):
        sem = asyncio.Semaphore(3)
        check = HostMemoryCheck(settings, meter=None, semaphore=sem)
        assert check.semaphore is sem
