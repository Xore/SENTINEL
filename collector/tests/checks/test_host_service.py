"""Tests for collector.checks.host_service — systemd service-status check."""
from __future__ import annotations

import asyncio

import pytest
from collector.checks.host_service import HostServiceCheck, _service_is_active


class _FakeProcess:
    def __init__(self, *, stdout: bytes, returncode: int, hang: bool = False):
        self._stdout = stdout
        self.returncode = returncode
        self._hang = hang
        self.killed = False
        self.waited = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(10.0)
        return self._stdout, b""

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True


def _fake_exec(process: _FakeProcess):
    async def _exec(*args, **kwargs):  # pylint: disable=unused-argument
        return process

    return _exec


class TestServiceIsActive:
    async def test_active_service_returns_true(self, monkeypatch):
        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec",
            _fake_exec(_FakeProcess(stdout=b"active\n", returncode=0)),
        )
        assert await _service_is_active("nginx", timeout_s=1.0) is True

    async def test_inactive_service_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec",
            _fake_exec(_FakeProcess(stdout=b"inactive\n", returncode=3)),
        )
        assert await _service_is_active("nginx", timeout_s=1.0) is False

    async def test_missing_systemctl_raises_runtime_error(self, monkeypatch):
        async def _raise_not_found(*args, **kwargs):
            raise FileNotFoundError("systemctl")

        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec", _raise_not_found
        )
        with pytest.raises(RuntimeError, match="systemctl not found"):
            await _service_is_active("nginx", timeout_s=1.0)

    async def test_timeout_kills_process_and_raises(self, monkeypatch):
        process = _FakeProcess(stdout=b"", returncode=0, hang=True)
        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec",
            _fake_exec(process),
        )
        with pytest.raises(TimeoutError):
            await _service_is_active("nginx", timeout_s=0.05)
        assert process.killed is True
        assert process.waited is True


class TestHostServiceCheck:
    async def test_run_ok_when_active(self, settings, monkeypatch):
        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec",
            _fake_exec(_FakeProcess(stdout=b"active\n", returncode=0)),
        )
        check = HostServiceCheck(settings, meter=None, service_name="nginx")

        result = await check.run()

        assert result.ok is True
        assert result.metrics == {"service_active": 1.0}
        assert result.labels == {"service": "nginx"}

    async def test_run_not_ok_when_inactive(self, settings, monkeypatch):
        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec",
            _fake_exec(_FakeProcess(stdout=b"inactive\n", returncode=3)),
        )
        check = HostServiceCheck(settings, meter=None, service_name="nginx")

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {"service_active": 0.0}
        assert "nginx" in result.error

    async def test_missing_systemctl_never_raises(self, settings, monkeypatch):
        async def _raise_not_found(*args, **kwargs):
            raise FileNotFoundError("systemctl")

        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec", _raise_not_found
        )
        check = HostServiceCheck(settings, meter=None, service_name="nginx")

        result = await check.run()

        assert result.ok is False
        assert "systemctl not found" in result.error

    async def test_timeout_never_raises(self, settings, monkeypatch):
        process = _FakeProcess(stdout=b"", returncode=0, hang=True)
        monkeypatch.setattr(
            "collector.checks.host_service.asyncio.create_subprocess_exec",
            _fake_exec(process),
        )
        check = HostServiceCheck(settings, meter=None, service_name="nginx", timeout_s=0.05)

        result = await check.run()

        assert result.ok is False
        assert result.error is not None

    async def test_unsupported_platform_reports_failure(self, settings, monkeypatch):
        monkeypatch.setattr("collector.checks.host_service.sys.platform", "win32")
        check = HostServiceCheck(settings, meter=None, service_name="nginx")

        result = await check.run()

        assert result.ok is False
        assert "win32" in result.error

    def test_semaphore_stored(self, settings):
        sem = asyncio.Semaphore(3)
        check = HostServiceCheck(settings, meter=None, service_name="nginx", semaphore=sem)
        assert check.semaphore is sem
