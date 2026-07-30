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

    def test_rejects_negative_jiffies(self):
        # Kernel jiffie counters are unsigned; a negative one means the input is
        # not `/proc/stat`. Accepting it would yield a ratio outside [0, 1].
        with pytest.raises(ValueError, match="negative"):
            _parse_cpu_line("cpu  100 0 50 -800 10\n")

    def test_rejects_all_zero_line(self):
        with pytest.raises(ValueError, match="non-positive"):
            _parse_cpu_line("cpu  0 0 0 0\n")


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

    async def test_counter_reset_skips_the_interval_instead_of_clamping(self, settings, tmp_path):
        # A reboot or a namespaced /proc swap makes the monotonic counters go
        # backwards. Reporting a clamped 0%/100% would look like a measurement.
        path = tmp_path / "stat"
        path.write_text(_stat_line(user=1000, idle=8000))
        check = HostCpuCheck(settings, meter=None, proc_stat_path=str(path))
        await check.run()

        path.write_text(_stat_line(user=10, idle=80))
        result = await check.run()

        assert result.ok is True
        assert result.metrics == {}

        # The baseline was refreshed, so the next interval measures normally.
        path.write_text(_stat_line(user=110, idle=130))
        result = await check.run()
        assert result.metrics["cpu_utilization_ratio"] == pytest.approx(1 - 50 / 150)

    async def test_idle_growing_faster_than_total_skips_the_interval(self, settings, monkeypatch):
        # Mutually inconsistent samples (idle_delta > total_delta) would give a
        # negative utilization; there is no clamp, so the interval is skipped.
        samples = iter([(800, 960), (900, 1000)])
        monkeypatch.setattr(
            "collector.checks.host_cpu._read_cpu_jiffies", lambda path: next(samples)
        )
        check = HostCpuCheck(settings, meter=None)
        await check.run()

        result = await check.run()

        assert result.ok is True
        assert result.metrics == {}

    async def test_utilization_is_never_clamped_for_a_valid_interval(self, settings, monkeypatch):
        # A fully busy interval must read as exactly 1.0, and a fully idle one
        # as exactly 0.0 — proof the values come from the delta, not a clamp.
        samples = iter([(800, 960), (800, 1060), (900, 1160)])
        monkeypatch.setattr(
            "collector.checks.host_cpu._read_cpu_jiffies", lambda path: next(samples)
        )
        check = HostCpuCheck(settings, meter=None)
        await check.run()

        assert (await check.run()).metrics["cpu_utilization_ratio"] == pytest.approx(1.0)
        assert (await check.run()).metrics["cpu_utilization_ratio"] == pytest.approx(0.0)

    async def test_missing_file_never_raises(self, settings, tmp_path):
        check = HostCpuCheck(settings, meter=None, proc_stat_path=str(tmp_path / "nope"))
        result = await check.run()
        assert result.ok is False
        # Bounded: the exception type only. The full message can embed the
        # configured path, so it goes to the structured log instead.
        assert result.error == "FileNotFoundError"

    async def test_malformed_file_never_raises(self, settings, tmp_path):
        path = tmp_path / "stat"
        path.write_text("garbage\n")
        check = HostCpuCheck(settings, meter=None, proc_stat_path=str(path))
        result = await check.run()
        assert result.ok is False
        # No raw file content in the result — a parse error would otherwise
        # carry an unbounded line straight into the failure record.
        assert result.error == "ValueError"
        assert "garbage" not in result.error

    @pytest.mark.parametrize(
        "content",
        ["cpu  100 0 50 -800 10\n", "cpu  0 0 0 0\n", "cpu  1 2\n", "cpu  1 2 x 4\n"],
    )
    async def test_implausible_values_fail_the_check(self, settings, tmp_path, content):
        path = tmp_path / "stat"
        path.write_text(content)
        check = HostCpuCheck(settings, meter=None, proc_stat_path=str(path))

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {}

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
