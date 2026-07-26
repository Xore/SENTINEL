"""Tests for collector.checks.net_tcp — TCP connect probe."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from collector.checks.net_tcp import TcpCheck, tcp_connect
from collector.config import TcpTarget, load_settings


def _fake_open_connection(reader=None, writer=None):
    async def _open(host, port):
        return reader or MagicMock(), writer or MagicMock(wait_closed=AsyncMock())

    return _open


class _FakeHistogram:
    def __init__(self):
        self.calls: list[tuple[float, dict]] = []

    def record(self, amount, attributes=None):
        self.calls.append((amount, attributes or {}))


class _FakeMeter:
    def __init__(self):
        self.instruments: dict[str, object] = {}

    def create_histogram(self, name, description=None, unit=None):
        instrument = _FakeHistogram()
        self.instruments[name] = instrument
        return instrument


class TestTcpConnect:
    async def test_returns_connect_time_on_success(self):
        writer = MagicMock()
        writer.wait_closed = AsyncMock()
        with patch(
            "collector.checks.net_tcp.asyncio.open_connection",
            _fake_open_connection(writer=writer),
        ):
            connect_ms = await tcp_connect("10.0.0.1", 443, timeout_s=1.0)
        assert connect_ms >= 0
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_raises_on_connection_refused(self):
        async def _refused(host, port):
            raise ConnectionRefusedError("refused")

        with (
            patch("collector.checks.net_tcp.asyncio.open_connection", _refused),
            pytest.raises(ConnectionRefusedError),
        ):
            await tcp_connect("10.0.0.1", 443, timeout_s=1.0)

    async def test_raises_timeout_error_when_slower_than_timeout(self):
        async def _slow(host, port):
            await asyncio.sleep(10)
            return MagicMock(), MagicMock()

        with (
            patch("collector.checks.net_tcp.asyncio.open_connection", _slow),
            pytest.raises(TimeoutError),
        ):
            await tcp_connect("10.0.0.1", 443, timeout_s=0.01)


class TestTcpCheck:
    def test_interval_s_from_config(self):
        settings = load_settings(collector_id="c", tcp={"interval_s": 15})
        check = TcpCheck(settings, meter=None, target=TcpTarget(target_id="t", host="h", port=1))
        assert check.interval_s == 15

    def test_semaphore_stored(self):
        settings = load_settings(collector_id="c")
        sem = asyncio.Semaphore(3)
        check = TcpCheck(
            settings, meter=None, target=TcpTarget(target_id="t", host="h", port=1), semaphore=sem
        )
        assert check.semaphore is sem

    async def test_run_ok_result(self, monkeypatch):
        settings = load_settings(collector_id="c")
        target = TcpTarget(target_id="web", host="10.0.0.1", port=443)
        check = TcpCheck(settings, meter=None, target=target)

        async def fake_connect(host, port, timeout_s):
            return 3.4

        monkeypatch.setattr("collector.checks.net_tcp.tcp_connect", fake_connect)
        result = await check.run()

        assert result.ok is True
        assert result.metrics == {"tcp_connect_ms": 3.4}
        assert result.labels == {"target": "10.0.0.1", "port": "443"}
        assert result.error is None

    async def test_run_never_raises_on_failure(self, monkeypatch):
        settings = load_settings(collector_id="c")
        target = TcpTarget(target_id="web", host="10.0.0.1", port=443)
        check = TcpCheck(settings, meter=None, target=target)

        async def failing_connect(host, port, timeout_s):
            raise ConnectionRefusedError("refused")

        monkeypatch.setattr("collector.checks.net_tcp.tcp_connect", failing_connect)
        result = await check.run()

        assert result.ok is False
        assert result.metrics == {}
        assert result.labels == {"target": "10.0.0.1", "port": "443"}
        assert "refused" in result.error

    def test_is_enabled_false_when_tcp_config_disabled(self):
        settings = load_settings(collector_id="c", tcp={"enabled": False})
        check = TcpCheck(settings, meter=None, target=TcpTarget(target_id="t", host="h", port=1))
        assert check.is_enabled() is False

    async def test_run_ok_emits_canonical_metric_with_target_id_label(self, monkeypatch):
        settings = load_settings(collector_id="c")
        meter = _FakeMeter()
        target = TcpTarget(target_id="web", host="10.0.0.1", port=443)
        check = TcpCheck(settings, meter=meter, target=target)

        async def fake_connect(host, port, timeout_s):
            return 15.0

        monkeypatch.setattr("collector.checks.net_tcp.tcp_connect", fake_connect)
        await check.run()

        calls = meter.instruments["sentinel_collector_tcp_connect_seconds"].calls
        assert calls == [(0.015, {"target_id": "web"})]

    async def test_run_failure_does_not_emit_metric(self, monkeypatch):
        settings = load_settings(collector_id="c")
        meter = _FakeMeter()
        target = TcpTarget(target_id="web", host="10.0.0.1", port=443)
        check = TcpCheck(settings, meter=meter, target=target)

        async def failing_connect(host, port, timeout_s):
            raise ConnectionRefusedError("refused")

        monkeypatch.setattr("collector.checks.net_tcp.tcp_connect", failing_connect)
        await check.run()

        calls = meter.instruments["sentinel_collector_tcp_connect_seconds"].calls
        assert calls == []
