"""Tests for collector.checks.host_cpu — Linux CPU utilization check."""

from __future__ import annotations

import asyncio
import os
import time

import pytest
from collector.checks.host_cpu import HostCpuCheck, _parse_cpu_line, _read_cpu_jiffies


def _stat_line(*, user=100, nice=0, system=50, idle=800, iowait=10, irq=0, softirq=0, steal=0):
    return f"cpu  {user} {nice} {system} {idle} {iowait} {irq} {softirq} {steal}\n"


class TestParseCpuLine:
    def test_parses_idle_and_total(self):
        idle, total = _parse_cpu_line(_stat_line())
        assert idle == 810  # idle + iowait
        assert total == 960

    def test_rejects_non_cpu_line(self):
        with pytest.raises(ValueError, match="unexpected"):
            _parse_cpu_line("cpu0 1 2 3 4\n")

    def test_rejects_non_integer_field(self):
        with pytest.raises(ValueError, match="non-integer"):
            _parse_cpu_line("cpu  1 2 x 4\n")

    def test_rejects_too_few_fields(self):
        with pytest.raises(ValueError, match="insufficient"):
            _parse_cpu_line("cpu  1 2\n")

    def test_handles_missing_optional_iowait_field(self):
        idle, total = _parse_cpu_line("cpu  100 0 50 800\n")
        assert idle == 800
        assert total == 950


class TestReadCpuJiffies:
    def test_reads_real_file(self, tmp_path):
        path = tmp_path / "stat"
        path.write_text(_stat_line())
        idle, total = _read_cpu_jiffies(str(path))
        assert idle == 810
        assert total == 960

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _read_cpu_jiffies(str(tmp_path / "nope"))

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
    def test_permission_denied_raises(self, tmp_path):
        path = tmp_path / "stat"
        path.write_text(_stat_line())
        path.chmod(0o000)
        try:
            with pytest.raises(PermissionError):
                _read_cpu_jiffies(str(path))
        finally:
            path.chmod(0o644)  # restore so tmp_path cleanup can remove it


class TestHostCpuCheck:
    @pytest.fixture(autouse=True)
    def _linux_platform(self, monkeypatch):
        monkeypatch.setattr("collector.checks.host_cpu.sys.platform", "linux")

    async def test_first_run_records_baseline_with_no_metrics(self, settings, tmp_path):
        path = tmp_path / "stat"
        path.write_text(_stat_line())
        check = HostCpuCheck(settings, meter=None, proc_stat_path=str(path))

        result = await check.run()

        assert result.ok is True
        assert result.metrics == {}

    async def test_second_run_computes_utilization_from_delta(self, settings, tmp_path):
        path = tmp_path / "stat"
        path.write_text(_stat_line(user=100, idle=800))
        check = HostCpuCheck(settings, meter=None, proc_stat_path=str(path))
        await check.run()

        # 100 more busy jiffies, 50 more idle jiffies -> total_delta=150, idle_delta=50
        path.write_text(_stat_line(user=200, idle=850))
        result = await check.run()

        assert result.ok is True
        assert result.metrics["cpu_utilization_ratio"] == pytest.approx(1 - 50 / 150)

    async def test_missing_file_never_raises(self, settings, tmp_path):
        check = HostCpuCheck(settings, meter=None, proc_stat_path=str(tmp_path / "nope"))
        result = await check.run()
        assert result.ok is False
        assert result.error is not None

    async def test_malformed_file_never_raises(self, settings, tmp_path):
        path = tmp_path / "stat"
        path.write_text("garbage\n")
        check = HostCpuCheck(settings, meter=None, proc_stat_path=str(path))
        result = await check.run()
        assert result.ok is False

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
    async def test_permission_denied_never_raises(self, settings, tmp_path):
        path = tmp_path / "stat"
        path.write_text(_stat_line())
        path.chmod(0o000)
        try:
            check = HostCpuCheck(settings, meter=None, proc_stat_path=str(path))
            result = await check.run()
            assert result.ok is False
        finally:
            path.chmod(0o644)

    async def test_unsupported_platform_reports_failure(self, settings, tmp_path, monkeypatch):
        monkeypatch.setattr("collector.checks.host_cpu.sys.platform", "win32")
        check = HostCpuCheck(settings, meter=None, proc_stat_path=str(tmp_path / "stat"))
        result = await check.run()
        assert result.ok is False
        assert "win32" in result.error

    async def test_slow_read_is_cancellable(self, settings, monkeypatch):
        check = HostCpuCheck(settings, meter=None)

        def slow_read(path):  # pylint: disable=unused-argument
            time.sleep(1.5)
            return 0, 1  # pragma: no cover — never reached

        monkeypatch.setattr("collector.checks.host_cpu._read_cpu_jiffies", slow_read)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(check.run(), timeout=0.2)

    def test_semaphore_stored(self, settings):
        sem = asyncio.Semaphore(3)
        check = HostCpuCheck(settings, meter=None, semaphore=sem)
        assert check.semaphore is sem
