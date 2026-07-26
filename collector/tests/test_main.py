"""Tests for collector.__main__ — config -> PKI check -> OTLP -> scheduler wiring."""
from __future__ import annotations

import asyncio

import pytest

import collector.__main__ as main_module
from collector.__main__ import main
from collector.checks import BaseCheck, CheckResult


async def test_missing_collector_id_exits_with_code_1():
    with pytest.raises(SystemExit) as exc_info:
        await main()
    assert exc_info.value.code == 1


class _FakeCounter:
    def __init__(self):
        self.value = 0

    # attributes is unused, but must stay in the signature to duck-type the
    # real opentelemetry Counter.add(amount, attributes=...) call in __main__.py.
    def add(self, amount, attributes=None):  # pylint: disable=unused-argument
        self.value += amount


class _FakeHistogram:
    def __init__(self):
        self.values: list[float] = []

    def record(self, amount, attributes=None):  # pylint: disable=unused-argument
        self.values.append(amount)


class _FakeMeter:
    def __init__(self):
        self.counters: dict[str, _FakeCounter] = {}
        self.histograms: dict[str, _FakeHistogram] = {}

    # description/unit are unused for the same duck-typing reason as above.
    def create_counter(self, name, description=None, unit=None):  # pylint: disable=unused-argument
        counter = _FakeCounter()
        self.counters[name] = counter
        return counter

    # collector.scheduler creates histograms for canonical run/duration
    # telemetry (docs/contracts/METRICS.md); this fake must duck-type that
    # too now that run_scheduler() is called with a real meter in main().
    def create_histogram(self, name, description=None, unit=None):  # pylint: disable=unused-argument
        histogram = _FakeHistogram()
        self.histograms[name] = histogram
        return histogram


class _FakeMeterProvider:
    def __init__(self):
        self.meter = _FakeMeter()


async def test_wires_up_and_emits_heartbeat(monkeypatch, enrolled_pki_dir, capsys):
    monkeypatch.setenv("COLLECTOR_ID", "node-1")
    monkeypatch.setenv("SITE_ID", "site-a")
    monkeypatch.setenv("BACKEND__PKI_DIR", str(enrolled_pki_dir))
    monkeypatch.setenv("BACKEND__URL", "https://localhost:4317")
    monkeypatch.setattr(main_module, "HEARTBEAT_INTERVAL_S", 0.01)

    # build_meter_provider/shutdown_meter_provider belong to transport/otlp.py,
    # which already has its own tests exercising the real OTLP SDK objects
    # (construction, resource attributes, meter creation). Here they'd try a
    # real gRPC export against a backend.url that isn't a real server, which
    # is slow (retry/backoff) and leaves a background thread running past the
    # test if not shut down correctly. This test's job is __main__'s
    # orchestration — that it enrolls, builds a provider, creates a counter,
    # runs the scheduler, and shuts down — not OTLP wire behaviour.
    fake_provider = _FakeMeterProvider()
    shutdown_calls = []
    monkeypatch.setattr(main_module, "build_meter_provider", lambda settings: fake_provider)
    monkeypatch.setattr(main_module, "get_meter", lambda provider: provider.meter)
    monkeypatch.setattr(main_module, "shutdown_meter_provider", shutdown_calls.append)

    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop_event.set)

    await main(stop_event=stop_event)
    await asyncio.sleep(0.01)  # let the last fire-and-forget heartbeat land

    out = capsys.readouterr().out
    assert "collector.started" in out
    assert "collector.heartbeat" in out
    assert "collector.shutdown" in out
    assert shutdown_calls == [fake_provider]
    # Canonical name (docs/contracts/METRICS.md) and the temporary Phase 1
    # compatibility alias must both increment on every heartbeat cycle.
    assert fake_provider.meter.counters["sentinel_collector_heartbeat_total"].value >= 1
    assert fake_provider.meter.counters["collector_heartbeat_total"].value >= 1
    assert (
        fake_provider.meter.counters["sentinel_collector_heartbeat_total"].value
        == fake_provider.meter.counters["collector_heartbeat_total"].value
    )


async def test_broken_check_is_contained_and_shutdown_still_runs(
    monkeypatch, enrolled_pki_dir, capsys
):
    """S2-01: a check that bypasses BaseCheck's never-raise contract must be
    contained as a failed run by the scheduler, not crash it — main() keeps
    running (and later shuts down cleanly on stop_event) instead of
    propagating an ExceptionGroup.
    """
    monkeypatch.setenv("COLLECTOR_ID", "node-1")
    monkeypatch.setenv("BACKEND__PKI_DIR", str(enrolled_pki_dir))
    monkeypatch.setenv("BACKEND__URL", "https://localhost:4317")
    monkeypatch.setattr(main_module, "HEARTBEAT_INTERVAL_S", 0.01)

    fake_provider = _FakeMeterProvider()
    shutdown_calls = []
    monkeypatch.setattr(main_module, "build_meter_provider", lambda settings: fake_provider)
    monkeypatch.setattr(main_module, "get_meter", lambda provider: provider.meter)
    monkeypatch.setattr(main_module, "shutdown_meter_provider", shutdown_calls.append)

    class _BrokenHeartbeat(main_module._HeartbeatCheck):  # pylint: disable=protected-access
        async def run(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "_HeartbeatCheck", _BrokenHeartbeat)

    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop_event.set)
    await main(stop_event=stop_event)  # must not raise

    assert shutdown_calls == [fake_provider]
    out = capsys.readouterr().out
    assert "scheduler.check_exception" in out
    assert "collector.shutdown" in out


class _TrackingCheck(BaseCheck):
    name = "tracking"
    scan_level = 1

    def __init__(self, config, meter, *, raise_on_close=False):
        super().__init__(config, meter)
        self.closed = False
        self._raise_on_close = raise_on_close

    async def run(self) -> CheckResult:
        return CheckResult(ok=True)

    async def aclose(self) -> None:
        if self._raise_on_close:
            raise RuntimeError("close failed")
        self.closed = True


async def test_close_checks_closes_every_check(settings):
    checks = [_TrackingCheck(settings, meter=None), _TrackingCheck(settings, meter=None)]
    log = main_module.structlog.get_logger()

    await main_module._close_checks(checks, log)  # pylint: disable=protected-access

    assert all(c.closed for c in checks)


async def test_close_checks_survives_one_check_raising(settings):
    broken = _TrackingCheck(settings, meter=None, raise_on_close=True)
    healthy = _TrackingCheck(settings, meter=None)
    log = main_module.structlog.get_logger()

    await main_module._close_checks([broken, healthy], log)  # pylint: disable=protected-access

    assert healthy.closed is True


async def test_main_closes_heartbeat_check_on_shutdown(monkeypatch, enrolled_pki_dir):
    monkeypatch.setenv("COLLECTOR_ID", "node-1")
    monkeypatch.setenv("BACKEND__PKI_DIR", str(enrolled_pki_dir))
    monkeypatch.setenv("BACKEND__URL", "https://localhost:4317")
    monkeypatch.setattr(main_module, "HEARTBEAT_INTERVAL_S", 0.01)

    fake_provider = _FakeMeterProvider()
    monkeypatch.setattr(main_module, "build_meter_provider", lambda settings: fake_provider)
    monkeypatch.setattr(main_module, "get_meter", lambda provider: provider.meter)
    monkeypatch.setattr(main_module, "shutdown_meter_provider", lambda provider: None)

    close_calls = []
    heartbeat_check_cls = main_module._HeartbeatCheck  # pylint: disable=protected-access
    original_aclose = heartbeat_check_cls.aclose

    async def tracking_aclose(self):
        close_calls.append(self)
        await original_aclose(self)

    monkeypatch.setattr(heartbeat_check_cls, "aclose", tracking_aclose)

    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.03, stop_event.set)
    await main(stop_event=stop_event)

    assert len(close_calls) == 1
    assert isinstance(close_calls[0], heartbeat_check_cls)
