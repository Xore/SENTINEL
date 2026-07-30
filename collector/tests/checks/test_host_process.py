"""Tests for collector.checks.host_process — process-presence check."""

from __future__ import annotations

import asyncio
import os
import time

import pytest
from collector.checks.host_process import (
    MAX_COMM_LEN,
    HostProcessCheck,
    ProcessScan,
    _scan_for_process,
)


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


def _check(settings, tmp_path=None, **kwargs):
    """Construct a check with valid defaults for the fields under test."""
    kwargs.setdefault("target_id", "web-server")
    kwargs.setdefault("process_name", "nginx")
    if tmp_path is not None:
        kwargs.setdefault("proc_root", str(tmp_path))
    return HostProcessCheck(settings, meter=None, **kwargs)


class TestTargetIdValidation:
    """Only a bounded `target_id` may become a metric label (METRICS.md)."""

    @pytest.mark.parametrize(
        "target_id",
        [
            "",
            "Upper",
            "under_score",
            "-leading",
            "trailing-",
            "has space",
            "has.dot",
            "nul\x00byte",
            "new\nline",
            "a" * 64,
        ],
    )
    def test_rejects_invalid_target_id(self, settings, target_id):
        with pytest.raises(ValueError, match="target_id"):
            _check(settings, target_id=target_id)

    @pytest.mark.parametrize("target_id", ["a", "web", "web-server-01", "a" * 63])
    def test_accepts_valid_target_id(self, settings, target_id):
        assert _check(settings, target_id=target_id).target_id == target_id


class TestProcessNameValidation:
    @pytest.mark.parametrize(
        "process_name",
        ["", " padded ", "trailing ", "nul\x00byte", "new\nline", "tab\tsep"],
    )
    def test_rejects_malformed_process_name(self, settings, process_name):
        with pytest.raises(ValueError, match="process_name"):
            _check(settings, process_name=process_name)

    def test_rejects_name_longer_than_kernel_comm(self, settings):
        # A name the kernel would truncate can never match, so it is a
        # configuration error rather than a permanently-failing check.
        with pytest.raises(ValueError, match="TASK_COMM_LEN"):
            _check(settings, process_name="x" * (MAX_COMM_LEN + 1))

    def test_accepts_name_at_kernel_limit(self, settings):
        check = _check(settings, process_name="x" * MAX_COMM_LEN)
        assert check.run is not None  # constructed without raising

    def test_accepts_name_containing_a_space(self, settings):
        # Real `comm` values can contain spaces, e.g. Firefox's "Web Content".
        assert _check(settings, process_name="Web Content") is not None


class TestScanForProcess:
    def test_finds_matching_process(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd", "200": "nginx"})
        assert _scan_for_process(str(proc_root), "nginx") == ProcessScan(found=True, unreadable=0)

    def test_returns_absent_when_not_present(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd"})
        assert _scan_for_process(str(proc_root), "nginx") == ProcessScan(found=False, unreadable=0)

    def test_skips_non_numeric_entries(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {})
        assert _scan_for_process(str(proc_root), "anything").found is False

    def test_vanished_pid_is_a_clean_absence_not_an_inspection_failure(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd", "200": "nginx"})
        # Simulate the process exiting between listdir() and reading comm.
        (proc_root / "200" / "comm").unlink()

        assert _scan_for_process(str(proc_root), "nginx") == ProcessScan(
            found=False, unreadable=0
        )
        assert _scan_for_process(str(proc_root), "sshd").found is True

    def test_missing_proc_root_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _scan_for_process(str(tmp_path / "nope"), "sshd")

    def test_unreadable_comm_is_counted_on_any_platform(self, tmp_path, monkeypatch):
        # The POSIX chmod variant below is the real thing; this one exercises the
        # same branch where the test host has no POSIX permission semantics.
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd", "200": "nginx"})
        real_open = open

        def _denied(path, *args, **kwargs):
            if str(path).replace("\\", "/").endswith("/100/comm"):
                raise PermissionError(13, "Permission denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", _denied)

        assert _scan_for_process(str(proc_root), "sshd") == ProcessScan(found=False, unreadable=1)
        # An unreadable PID must not mask a match found elsewhere. Directory
        # order is unspecified, so only the match itself is asserted.
        assert _scan_for_process(str(proc_root), "nginx").found is True

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
    def test_unreadable_comm_is_counted_not_treated_as_absence(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd"})
        (proc_root / "100" / "comm").chmod(0o000)
        try:
            scan = _scan_for_process(str(proc_root), "sshd")
            assert scan == ProcessScan(found=False, unreadable=1)
        finally:
            (proc_root / "100" / "comm").chmod(0o644)

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
    def test_unreadable_pid_does_not_mask_a_real_match(self, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd", "200": "nginx"})
        (proc_root / "100" / "comm").chmod(0o000)
        try:
            assert _scan_for_process(str(proc_root), "nginx").found is True
        finally:
            (proc_root / "100" / "comm").chmod(0o644)


class TestHostProcessCheck:
    @pytest.fixture(autouse=True)
    def _linux_platform(self, monkeypatch):
        monkeypatch.setattr("collector.checks.host_process.sys.platform", "linux")

    async def test_run_ok_when_running(self, settings, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "nginx"})
        check = _check(settings, proc_root=str(proc_root))

        result = await check.run()

        assert result.ok is True
        assert result.metrics == {"process_running": 1.0}
        assert result.labels == {"target_id": "web-server"}

    async def test_run_not_ok_when_absent(self, settings, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "sshd"})
        check = _check(settings, proc_root=str(proc_root))

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {"process_running": 0.0}
        assert "web-server" in result.error

    async def test_uninspectable_pids_degrade_without_claiming_absence(self, settings, monkeypatch):
        monkeypatch.setattr(
            "collector.checks.host_process._scan_for_process",
            lambda proc_root, process_name: ProcessScan(found=False, unreadable=2),
        )
        check = _check(settings)

        result = await check.run()

        assert result.ok is False
        # Crucially no `process_running` sample: a zero here would assert an
        # absence that was never established.
        assert result.metrics == {}
        assert "absence unproven" in result.error
        assert result.labels == {"target_id": "web-server"}

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
    async def test_real_permission_denial_degrades(self, settings, tmp_path):
        proc_root = _make_fake_proc(tmp_path, {"100": "nginx"})
        (proc_root / "100" / "comm").chmod(0o000)
        try:
            check = _check(settings, proc_root=str(proc_root))
            result = await check.run()

            assert result.ok is False
            assert result.metrics == {}
            assert "absence unproven" in result.error
        finally:
            (proc_root / "100" / "comm").chmod(0o644)

    @pytest.mark.parametrize(
        "scan",
        [
            ProcessScan(found=True, unreadable=0),
            ProcessScan(found=False, unreadable=0),
            ProcessScan(found=False, unreadable=1),
        ],
    )
    async def test_raw_process_name_never_leaves_the_check(self, settings, monkeypatch, scan):
        monkeypatch.setattr(
            "collector.checks.host_process._scan_for_process",
            lambda proc_root, process_name: scan,
        )
        check = _check(settings, process_name="secret-proc")

        result = await check.run()

        assert "secret-proc" not in str(result.labels)
        assert "secret-proc" not in (result.error or "")

    async def test_missing_proc_root_never_raises(self, settings, tmp_path):
        check = _check(settings, proc_root=str(tmp_path / "nope"))

        result = await check.run()

        assert result.ok is False
        # Bounded result: the exception type, not the configured path.
        assert result.error == "web-server: FileNotFoundError"

    async def test_unsupported_platform_reports_failure(self, settings, tmp_path, monkeypatch):
        monkeypatch.setattr("collector.checks.host_process.sys.platform", "win32")
        check = _check(settings, proc_root=str(tmp_path / "proc"))

        result = await check.run()

        assert result.ok is False
        assert "win32" in result.error

    async def test_slow_scan_is_cancellable(self, settings, monkeypatch):
        def slow_scan(proc_root, process_name):  # pylint: disable=unused-argument
            time.sleep(1.5)
            return ProcessScan(found=False, unreadable=0)  # pragma: no cover — never reached

        monkeypatch.setattr("collector.checks.host_process._scan_for_process", slow_scan)
        check = _check(settings)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(check.run(), timeout=0.2)

    def test_semaphore_stored(self, settings):
        sem = asyncio.Semaphore(3)
        check = _check(settings, semaphore=sem)
        assert check.semaphore is sem
