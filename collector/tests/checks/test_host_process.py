"""Tests for collector.checks.host_process — process-presence check."""
from __future__ import annotations

import asyncio
import time

import pytest
from collector.checks.host_process import HostProcessCheck, _is_process_running


def _make_fake_proc(tmp_path, pid_to_comm: dict[str, str]):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    for pid, comm in pid_to_comm.items():
        pid_dir = proc_root / pid
        pid_dir.mkdir()
        (pid_dir / "comm").write_text(comm + "\n")
    # A non-numeric entry (e.g. "self", "net") must be skipped, not crash.
    (proc_root / "self").mkdir()
    return proc_root


class TestIsProcessRunning:
    def test_finds_matching_process(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd", "200": "nginx"})
        assert _is_process_running(str(proc_root), "nginx") is True

    def test_returns_false_when_absent(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd"})
        assert _is_process_running(str(proc_root), "nginx") is False

    def test_skips_non_numeric_entries(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {})
        assert _is_process_running(str(proc_root), "anything") is False

    def test_skips_pid_that_vanished_mid_scan(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd", "200": "nginx"})
        # Simulate the process exiting between listdir() and reading comm.
        (proc_root / "200" / "comm").unlink()
        assert _is_process_running(str(proc_root), "nginx") is False
        assert _is_process_running(str(proc_root), "sshd") is True

    def test_missing_proc_root_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _is_process_running(str(tmp_path / "nope"), "sshd")

    def test_unreadable_comm_is_skipped_not_fatal(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd"})
        (proc_root / "100" / "comm").chmod(0o000)
        try:
            assert _is_process_running(str(proc_root), "sshd") is False
        finally:
            (proc_root / "100" / "comm").chmod(0o644)


class TestHostProcessCheck:
    async def test_run_ok_when_running(self, settings, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "nginx"})
        check = HostProcessCheck(
            settings, meter=None, process_name="nginx", proc_root=str(proc_root)
        )

        result = await check.run()

        assert result.ok is True
        assert result.metrics == {"process_running": 1.0}
        assert result.labels == {"process": "nginx"}

    async def test_run_not_ok_when_missing(self, settings, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd"})
        check = HostProcessCheck(
            settings, meter=None, process_name="nginx", proc_root=str(proc_root)
        )

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {"process_running": 0.0}
        assert "nginx" in result.error

    async def test_missing_proc_root_never_raises(self, settings, tmp_path):
        check = HostProcessCheck(
            settings, meter=None, process_name="sshd", proc_root=str(tmp_path / "nope")
        )
        result = await check.run()
        assert result.ok is False
        assert result.error is not None

    async def test_unsupported_platform_reports_failure(self, settings, tmp_path, monkeypatch):
        monkeypatch.setattr("collector.checks.host_process.sys.platform", "win32")
        check = HostProcessCheck(
            settings, meter=None, process_name="sshd", proc_root=str(tmp_path / "proc")
        )
        result = await check.run()
        assert result.ok is False
        assert "win32" in result.error

    async def test_slow_scan_is_cancellable(self, settings, monkeypatch):
        def slow_scan(proc_root, process_name):  # pylint: disable=unused-argument
            time.sleep(1.5)
            return False  # pragma: no cover — never reached

        monkeypatch.setattr("collector.checks.host_process._is_process_running", slow_scan)
        check = HostProcessCheck(settings, meter=None, process_name="sshd")

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(check.run(), timeout=0.2)

    def test_semaphore_stored(self, settings):
        sem = asyncio.Semaphore(3)
        check = HostProcessCheck(settings, meter=None, process_name="sshd", semaphore=sem)
        assert check.semaphore is sem
