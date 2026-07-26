"""Tests for collector.checks.net_http — HTTP/HTTPS probe."""
from __future__ import annotations

import asyncio
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


@pytest.fixture(autouse=True)
async def _reset_http_check_session():
    """HttpCheck's shared session is class-level and bound to whatever event
    loop is running when it's created. pytest-asyncio gives each test
    function its own loop, so a session created in one test cannot be reused
    (or even safely closed) from another. Reset before every test, and close
    within the *same* test's loop afterward if one was created.
    """
    HttpCheck._session = None
    yield
    if HttpCheck._session is not None and not HttpCheck._session.closed:
        await HttpCheck._session.close()
    HttpCheck._session = None


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


class TestHttpCheckSharedSession:
    async def test_get_session_creates_once(self):
        settings = load_settings(collector_id="c")
        check_a = HttpCheck(settings, meter=None, target="https://10.0.0.1/a")
        check_b = HttpCheck(settings, meter=None, target="https://10.0.0.1/b")

        session_a = await check_a._get_session()
        session_b = await check_b._get_session()

        assert session_a is session_b

    async def test_get_session_recreates_after_close(self):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/")

        first = await check._get_session()
        await first.close()
        second = await check._get_session()

        assert second is not first
        assert not second.closed

    async def test_aclose_closes_the_shared_session(self):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/")

        session = await check._get_session()
        assert not session.closed

        await check.aclose()

        assert session.closed

    async def test_aclose_from_any_instance_closes_shared_session(self):
        """Every HttpCheck instance shares the class-level session — closing
        via one instance must close it for all of them, since the scheduler
        may call aclose() on whichever check instance it happens to hold."""
        settings = load_settings(collector_id="c")
        check_a = HttpCheck(settings, meter=None, target="https://10.0.0.1/a")
        check_b = HttpCheck(settings, meter=None, target="https://10.0.0.1/b")

        session = await check_a._get_session()
        await check_b.aclose()

        assert session.closed

    async def test_aclose_is_safe_when_no_session_was_ever_created(self):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/")
        await check.aclose()  # must not raise

    async def test_aclose_is_safe_to_call_twice(self):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/")
        await check._get_session()

        await check.aclose()
        await check.aclose()  # must not raise on an already-closed session


class TestHttpCheck:
    def test_interval_s_from_config(self):
        settings = load_settings(collector_id="c", http={"interval_s": 20})
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/")
        assert check.interval_s == 20

    def test_semaphore_stored(self):
        settings = load_settings(collector_id="c")
        sem = asyncio.Semaphore(3)
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/", semaphore=sem)
        assert check.semaphore is sem

    async def test_run_ok_on_2xx(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/health")

        async def fake_probe(url, *, timeout_s, verify_tls, session=None):
            return 8.0, 200

        monkeypatch.setattr("collector.checks.net_http.http_probe", fake_probe)
        result = await check.run()

        assert result.ok is True
        assert result.metrics == {"http_response_ms": 8.0}
        assert result.labels == {"target": "https://10.0.0.1/health", "status_code": "200"}

    async def test_run_not_ok_on_404(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/missing")

        async def fake_probe(url, *, timeout_s, verify_tls, session=None):
            return 5.0, 404

        monkeypatch.setattr("collector.checks.net_http.http_probe", fake_probe)
        result = await check.run()

        # CWE-252 regression guard: a 404 must not be reported as ok.
        assert result.ok is False
        assert result.labels["status_code"] == "404"

    async def test_run_not_ok_on_401(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/private")

        async def fake_probe(url, *, timeout_s, verify_tls, session=None):
            return 5.0, 401

        monkeypatch.setattr("collector.checks.net_http.http_probe", fake_probe)
        result = await check.run()

        assert result.ok is False

    async def test_run_never_raises_on_connection_error(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/")

        async def failing_probe(url, *, timeout_s, verify_tls, session=None):
            raise aiohttp.ClientConnectionError("refused")

        monkeypatch.setattr("collector.checks.net_http.http_probe", failing_probe)
        result = await check.run()

        assert result.ok is False
        assert "refused" in result.error

    async def test_run_passes_shared_session_to_http_probe(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = HttpCheck(settings, meter=None, target="https://10.0.0.1/")
        seen = {}

        async def fake_probe(url, *, timeout_s, verify_tls, session=None):
            seen["session"] = session
            return 1.0, 200

        monkeypatch.setattr("collector.checks.net_http.http_probe", fake_probe)
        await check.run()

        assert seen["session"] is HttpCheck._session
        assert seen["session"] is not None
