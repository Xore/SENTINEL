"""Tests for collector.checks.net_dns — DNS resolution probe."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import dns.resolver
import pytest
from collector.checks.net_dns import DnsCheck, dns_resolve
from collector.config import DnsTarget, load_settings


class _FakeResolver:
    def __init__(self, raises: Exception | None = None, sleep_s: float = 0.0):
        self.nameservers: list[str] | None = None
        self.calls: list[tuple] = []
        self._raises = raises
        self._sleep_s = sleep_s

    async def resolve(self, hostname, record_type, lifetime=None):
        self.calls.append((hostname, record_type, lifetime))
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        if self._raises:
            raise self._raises
        return None


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


_TARGET = DnsTarget(target_id="app-dns", hostname="example.com")


class TestDnsResolve:
    async def test_returns_resolve_time(self):
        resolver = _FakeResolver()
        resolve_ms = await dns_resolve("example.com", "A", timeout_s=1.0, resolver=resolver)
        assert resolve_ms >= 0
        assert resolver.calls == [("example.com", "A", 1.0)]

    async def test_sets_nameservers_when_provided(self):
        resolver = _FakeResolver()
        await dns_resolve(
            "example.com", "A", timeout_s=1.0, resolvers=["10.0.0.53"], resolver=resolver
        )
        assert resolver.nameservers == ["10.0.0.53"]

    async def test_does_not_touch_nameservers_when_not_provided(self):
        resolver = _FakeResolver()
        await dns_resolve("example.com", "A", timeout_s=1.0, resolver=resolver)
        assert resolver.nameservers is None

    async def test_raises_on_nxdomain(self):
        resolver = _FakeResolver(raises=dns.resolver.NXDOMAIN())
        with pytest.raises(dns.resolver.NXDOMAIN):
            await dns_resolve("nope.invalid", "A", timeout_s=1.0, resolver=resolver)

    async def test_creates_own_resolver_when_not_provided(self):
        fake = _FakeResolver()
        with patch("collector.checks.net_dns.dns.asyncresolver.Resolver", return_value=fake):
            await dns_resolve("example.com", "A", timeout_s=1.0)
        assert fake.calls == [("example.com", "A", 1.0)]

    async def test_external_cancellation_stops_a_slow_resolve(self):
        # dns_resolve's own `lifetime` bound is internal to dnspython; this
        # confirms an *external* asyncio timeout/cancellation (as the
        # scheduler applies via asyncio.timeout()) still interrupts it.
        resolver = _FakeResolver(sleep_s=10.0)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                dns_resolve("example.com", "A", timeout_s=10.0, resolver=resolver), timeout=0.05
            )


class TestDnsCheck:
    def test_interval_s_from_config(self):
        settings = load_settings(collector_id="c", dns={"interval_s": 45})
        check = DnsCheck(settings, meter=None, target=_TARGET)
        assert check.interval_s == 45

    def test_semaphore_stored(self):
        settings = load_settings(collector_id="c")
        sem = asyncio.Semaphore(3)
        check = DnsCheck(settings, meter=None, target=_TARGET, semaphore=sem)
        assert check.semaphore is sem

    def test_is_enabled_false_when_dns_config_disabled(self):
        settings = load_settings(collector_id="c", dns={"enabled": False})
        check = DnsCheck(settings, meter=None, target=_TARGET)
        assert check.is_enabled() is False

    async def test_run_ok_result(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = DnsCheck(settings, meter=None, target=_TARGET, record_type="A")

        async def fake_resolve(hostname, record_type, *, timeout_s, resolver=None, **kw):
            return 4.2

        monkeypatch.setattr("collector.checks.net_dns.dns_resolve", fake_resolve)
        result = await check.run()

        assert result.ok is True
        assert result.metrics == {"dns_resolve_ms": 4.2}
        assert result.labels == {"target": "example.com", "record_type": "A"}
        assert result.error is None

    async def test_run_never_raises_on_nxdomain(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = DnsCheck(settings, meter=None, target=_TARGET, record_type="A")

        async def failing_resolve(hostname, record_type, *, timeout_s, resolver=None, **kw):
            raise dns.resolver.NXDOMAIN()

        monkeypatch.setattr("collector.checks.net_dns.dns_resolve", failing_resolve)
        result = await check.run()

        assert result.ok is False
        assert result.labels == {"target": "example.com", "record_type": "A"}
        assert result.error is not None

    async def test_run_never_raises_on_timeout(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = DnsCheck(settings, meter=None, target=_TARGET, record_type="A")

        async def timing_out_resolve(hostname, record_type, *, timeout_s, resolver=None, **kw):
            raise TimeoutError("timed out")

        monkeypatch.setattr("collector.checks.net_dns.dns_resolve", timing_out_resolve)
        result = await check.run()

        assert result.ok is False
        assert "timed out" in result.error

    def test_default_record_type_is_a(self):
        settings = load_settings(collector_id="c")
        check = DnsCheck(settings, meter=None, target=_TARGET)
        assert check.record_type == "A"

    async def test_run_ok_emits_canonical_metric_with_target_id_and_record_type(
        self, monkeypatch
    ):
        settings = load_settings(collector_id="c")
        meter = _FakeMeter()
        check = DnsCheck(settings, meter=meter, target=_TARGET, record_type="A")

        async def fake_resolve(hostname, record_type, *, timeout_s, resolver=None, **kw):
            return 4.2

        monkeypatch.setattr("collector.checks.net_dns.dns_resolve", fake_resolve)
        await check.run()

        calls = meter.instruments["sentinel_collector_dns_resolve_seconds"].calls
        assert len(calls) == 1
        amount, attributes = calls[0]
        assert amount == pytest.approx(0.0042)
        assert attributes == {"target_id": "app-dns", "record_type": "A"}

    async def test_run_failure_does_not_emit_metric(self, monkeypatch):
        settings = load_settings(collector_id="c")
        meter = _FakeMeter()
        check = DnsCheck(settings, meter=meter, target=_TARGET, record_type="A")

        async def failing_resolve(hostname, record_type, *, timeout_s, resolver=None, **kw):
            raise dns.resolver.NXDOMAIN()

        monkeypatch.setattr("collector.checks.net_dns.dns_resolve", failing_resolve)
        await check.run()

        calls = meter.instruments["sentinel_collector_dns_resolve_seconds"].calls
        assert calls == []
