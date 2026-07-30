"""Tests for collector.checks.host_service — systemd service-status check."""

from __future__ import annotations

import asyncio

import pytest
from collector.checks.host_service import (
    KNOWN_INACTIVE_STATES,
    MAX_UNIT_NAME_LEN,
    HostServiceCheck,
    _query_service_state,
)


class _FakeProcess:
    """Stand-in for `asyncio.subprocess.Process`.

    `returncode` starts as `None` — as it does for a live child — because
    `_kill_and_reap()` only signals a process it believes is still running.
    """

    def __init__(
        self,
        *,
        stdout: bytes,
        stderr: bytes = b"",
        exit_code: int = 0,
        hang: bool = False,
    ):
        self._stdout = stdout
        self._stderr = stderr
        self._exit_code = exit_code
        self._hang = hang
        self.returncode: int | None = None
        self.killed = False
        self.waited = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(10.0)
        self.returncode = self._exit_code
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        if self.returncode is None:
            self.returncode = -9
        return self.returncode


def _fake_exec(process: _FakeProcess):
    async def _exec(*args, **kwargs):  # pylint: disable=unused-argument
        return process

    return _exec


def _patch_exec(monkeypatch, process: _FakeProcess) -> _FakeProcess:
    monkeypatch.setattr(
        "collector.checks.host_service.asyncio.create_subprocess_exec",
        _fake_exec(process),
    )
    return process


def _check(settings, **kwargs):
    kwargs.setdefault("target_id", "web-server")
    kwargs.setdefault("service_name", "nginx.service")
    return HostServiceCheck(settings, meter=None, **kwargs)


class TestConstructorValidation:
    """Nothing unbounded may be accepted, and nothing may execute before the
    configuration has been validated."""

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

    @pytest.mark.parametrize(
        "service_name",
        [
            "",
            " nginx ",
            "nginx ",
            "nul\x00byte",
            "new\nline",
            "tab\tsep",
            "-p",  # would be read by systemctl as an option
            "--version",
            "/absolute/path",
            "nginx;reboot",
            "nginx service",
            "a" * (MAX_UNIT_NAME_LEN + 1),
        ],
    )
    def test_rejects_invalid_service_name(self, settings, service_name):
        with pytest.raises(ValueError, match="service_name"):
            _check(settings, service_name=service_name)

    @pytest.mark.parametrize(
        "service_name",
        ["nginx", "nginx.service", "systemd-resolved.service", "getty@tty1.service", "a" * 255],
    )
    def test_accepts_valid_service_name(self, settings, service_name):
        assert _check(settings, service_name=service_name) is not None

    @pytest.mark.parametrize("timeout_s", [0, -1.0, float("nan"), float("inf"), True, "5"])
    def test_rejects_invalid_timeout(self, settings, timeout_s):
        with pytest.raises(ValueError, match="timeout_s"):
            _check(settings, timeout_s=timeout_s)

    async def test_invalid_config_never_reaches_systemctl(self, settings, monkeypatch):
        async def _explode(*args, **kwargs):  # pragma: no cover — must never run
            raise AssertionError("systemctl was invoked with unvalidated configuration")

        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec", _explode
        )
        with pytest.raises(ValueError):
            _check(settings, service_name="--version")


class TestQueryServiceState:
    async def test_active_service_returns_state_token(self, monkeypatch):
        _patch_exec(monkeypatch, _FakeProcess(stdout=b"active\n"))
        assert await _query_service_state("nginx", timeout_s=1.0) == "active"

    @pytest.mark.parametrize("state", sorted(KNOWN_INACTIVE_STATES))
    async def test_known_inactive_states_are_measurements(self, monkeypatch, state):
        _patch_exec(monkeypatch, _FakeProcess(stdout=state.encode() + b"\n", exit_code=3))
        assert await _query_service_state("nginx", timeout_s=1.0) == state

    @pytest.mark.parametrize("stdout", [b"", b"\n", b"unknown\n", b"Failed to connect to bus\n"])
    async def test_undetermined_state_raises_rather_than_reporting_inactive(
        self, monkeypatch, stdout
    ):
        # A unit whose state systemd could not report is not an inactive unit.
        _patch_exec(monkeypatch, _FakeProcess(stdout=stdout, stderr=b"denied", exit_code=4))
        with pytest.raises(RuntimeError, match="no usable state"):
            await _query_service_state("nginx", timeout_s=1.0)

    async def test_missing_systemctl_raises_runtime_error(self, monkeypatch):
        async def _raise_not_found(*args, **kwargs):
            raise FileNotFoundError("systemctl")

        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec", _raise_not_found
        )
        with pytest.raises(RuntimeError, match="systemctl not found"):
            await _query_service_state("nginx", timeout_s=1.0)

    async def test_service_name_is_passed_after_an_option_terminator(self, monkeypatch):
        seen: list[tuple[str, ...]] = []

        async def _record(*args, **kwargs):  # pylint: disable=unused-argument
            seen.append(args)
            return _FakeProcess(stdout=b"active\n")

        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec", _record
        )
        await _query_service_state("nginx.service", timeout_s=1.0)

        assert seen == [("systemctl", "is-active", "--", "nginx.service")]

    async def test_timeout_kills_and_reaps_the_child(self, monkeypatch):
        process = _patch_exec(monkeypatch, _FakeProcess(stdout=b"", hang=True))

        with pytest.raises(TimeoutError):
            await _query_service_state("nginx", timeout_s=0.05)

        assert process.killed is True
        assert process.waited is True

    async def test_transport_error_kills_and_reaps_the_child(self, monkeypatch):
        process = _FakeProcess(stdout=b"")

        async def _boom():
            raise OSError("broken pipe")

        process.communicate = _boom  # type: ignore[method-assign]
        _patch_exec(monkeypatch, process)

        with pytest.raises(OSError, match="broken pipe"):
            await _query_service_state("nginx", timeout_s=1.0)

        assert process.killed is True
        assert process.waited is True

    async def test_external_cancellation_still_reaps_the_child(self, monkeypatch):
        # Shutdown cancels in-flight checks. The child must not be orphaned, and
        # the cancellation must still propagate.
        process = _patch_exec(monkeypatch, _FakeProcess(stdout=b"", hang=True))
        task = asyncio.ensure_future(_query_service_state("nginx", timeout_s=30.0))
        await asyncio.sleep(0.05)  # let it reach the blocked communicate()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # `_kill_and_reap` shields the reap, so it completes after the awaiting
        # coroutine has already been torn down.
        await asyncio.sleep(0.05)
        assert process.killed is True
        assert process.waited is True

    async def test_already_exited_child_is_not_signalled(self, monkeypatch):
        process = _FakeProcess(stdout=b"")

        async def _exit_then_fail():
            process.returncode = 3
            raise OSError("read after exit")

        process.communicate = _exit_then_fail  # type: ignore[method-assign]
        _patch_exec(monkeypatch, process)

        with pytest.raises(OSError):
            await _query_service_state("nginx", timeout_s=1.0)

        assert process.killed is False
        assert process.waited is True


class TestHostServiceCheck:
    @pytest.fixture(autouse=True)
    def _linux_platform(self, monkeypatch):
        monkeypatch.setattr("collector.checks.host_service.sys.platform", "linux")

    async def test_run_ok_when_active(self, settings, monkeypatch):
        _patch_exec(monkeypatch, _FakeProcess(stdout=b"active\n"))
        check = _check(settings)

        result = await check.run()

        assert result.ok is True
        assert result.metrics == {"service_active": 1.0}
        assert result.labels == {"target_id": "web-server"}

    async def test_run_not_ok_when_inactive(self, settings, monkeypatch):
        _patch_exec(monkeypatch, _FakeProcess(stdout=b"inactive\n", exit_code=3))
        check = _check(settings)

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {"service_active": 0.0}
        assert result.labels == {"target_id": "web-server"}
        assert "web-server" in result.error

    async def test_undetermined_state_emits_no_sample(self, settings, monkeypatch):
        _patch_exec(monkeypatch, _FakeProcess(stdout=b"unknown\n", exit_code=4))
        check = _check(settings)

        result = await check.run()

        assert result.ok is False
        # A `service_active=0` here would record the unit as down when systemd
        # never said so.
        assert result.metrics == {}
        assert result.error == "web-server: RuntimeError"

    async def test_permission_failure_emits_no_sample(self, settings, monkeypatch):
        # An unprivileged collector gets an error on stderr and no state token.
        _patch_exec(
            monkeypatch,
            _FakeProcess(stdout=b"", stderr=b"Interactive authentication required", exit_code=1),
        )
        check = _check(settings)

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {}
        assert result.error == "web-server: RuntimeError"

    @pytest.mark.parametrize("stdout", [b"active\n", b"failed\n", b"unknown\n"])
    async def test_raw_service_name_never_leaves_the_check(self, settings, monkeypatch, stdout):
        _patch_exec(monkeypatch, _FakeProcess(stdout=stdout, exit_code=3))
        check = _check(settings, service_name="secret-unit.service")

        result = await check.run()

        assert "secret-unit" not in str(result.labels)
        assert "secret-unit" not in (result.error or "")

    async def test_missing_systemctl_never_raises(self, settings, monkeypatch):
        async def _raise_not_found(*args, **kwargs):
            raise FileNotFoundError("systemctl")

        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec", _raise_not_found
        )
        check = _check(settings)

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {}
        assert result.error == "web-server: RuntimeError"

    async def test_timeout_never_raises(self, settings, monkeypatch):
        process = _patch_exec(monkeypatch, _FakeProcess(stdout=b"", hang=True))
        check = _check(settings, timeout_s=0.05)

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {}
        assert result.error == "web-server: TimeoutError"
        assert process.killed is True

    async def test_cancellation_propagates_out_of_run(self, settings, monkeypatch):
        # The scheduler cancels checks on shutdown and relies on the
        # `CancelledError` surfacing rather than being swallowed as a failure.
        process = _patch_exec(monkeypatch, _FakeProcess(stdout=b"", hang=True))
        check = _check(settings, timeout_s=30.0)
        task = asyncio.ensure_future(check.run())
        await asyncio.sleep(0.05)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await asyncio.sleep(0.05)
        assert process.killed is True
        assert process.waited is True

    async def test_unsupported_platform_reports_failure(self, settings, monkeypatch):
        monkeypatch.setattr("collector.checks.host_service.sys.platform", "win32")
        check = _check(settings)

        result = await check.run()

        assert result.ok is False
        assert "win32" in result.error

    def test_semaphore_stored(self, settings):
        sem = asyncio.Semaphore(3)
        check = _check(settings, semaphore=sem)
        assert check.semaphore is sem
