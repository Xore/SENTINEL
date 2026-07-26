"""Tests for collector.checks.net_http — HTTP/HTTPS probe."""
from __future__ import annotations

from unittest.mock import patch

import aiohttp
import pytest
from collector.checks.net_http import HttpCheck, http_probe
from collector.config import load_settings


class _FakeResponse:
    def __init__(self, status: int):
        self.status = status

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def read(self) -> bytes:
        return b""


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls: list[dict] = []
        self.closed = False

    def get(self, url: str, timeout=None, ssl=None) -> _FakeResponse:
        self.calls.append({"url": url, "timeout": timeout, "ssl": ssl})
        return self.response

    async def close(self) -> None:
        self.closed = True


class TestHttpProbe:
    async def test_returns_response_time_and_status(self):
        session = _FakeSession(_FakeResponse(200))
        response_ms, status = await http_probe(
            "https://10.0.0.1/health", timeout_s=1.0, verify_tls=True, session=session
        )
        assert response_ms >= 0
        assert status == 200
        assert session.calls[0]["url"] == "https://10.0.0.1/health"
        assert session.calls[0]["ssl"] is True

    async def test_does_not_close_injected_session(self):
        session = _FakeSession(_FakeResponse(200))
        await http_probe("https://10.0.0.1/", timeout_s=1.0, verify_tls=True, session=session)
        assert session.closed is False

    async def test_creates_and_closes_own_session_when_not_provided(self):
        fake_session = _FakeSession(_FakeResponse(200))
        with patch(
            "collector.checks.net_http.aiohttp.ClientSession", return_value=fake_session
        ):
            await http_probe("https://10.0.0.1/", timeout_s=1.0, verify_tls=True)
        assert fake_session.closed is True

    async def test_raises_on_connection_error(self):
        class _RefusingSession:
            def get(self, url, timeout=None, ssl=None):
                raise aiohttp.ClientConnectionError("refused")

        with pytest.raises(aiohttp.ClientConnectionError):
            await http_probe(
                "https://10.0.0.1/", timeout_s=1.0, verify_tls=True, session=_RefusingSession()
            )


class TestHttpCheck:
    async def test_run_ok_on_2xx(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/health")

        async def fake_probe(url, *, timeout_s, verify_tls):
            return 8.0, 200

        monkeypatch.setattr("collector.checks.net_http.http_probe", fake_probe)
        result = await check.run()

        assert result.ok is True
        assert result.metrics == {"http_response_ms": 8.0}
        assert result.labels == {"target": "https://10.0.0.1/health", "status_code": "200"}

    async def test_run_not_ok_on_404(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/missing")

        async def fake_probe(url, *, timeout_s, verify_tls):
            return 5.0, 404

        monkeypatch.setattr("collector.checks.net_http.http_probe", fake_probe)
        result = await check.run()

        # CWE-252 regression guard: a 404 must not be reported as ok.
        assert result.ok is False
        assert result.labels["status_code"] == "404"

    async def test_run_not_ok_on_401(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/private")

        async def fake_probe(url, *, timeout_s, verify_tls):
            return 5.0, 401

        monkeypatch.setattr("collector.checks.net_http.http_probe", fake_probe)
        result = await check.run()

        assert result.ok is False

    async def test_run_never_raises_on_connection_error(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/")

        async def failing_probe(url, *, timeout_s, verify_tls):
            raise aiohttp.ClientConnectionError("refused")

        monkeypatch.setattr("collector.checks.net_http.http_probe", failing_probe)
        result = await check.run()

        assert result.ok is False
        assert "refused" in result.error
