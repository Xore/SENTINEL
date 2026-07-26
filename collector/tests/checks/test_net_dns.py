"""Tests for collector.checks.net_dns — DNS resolution probe."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import dns.resolver
import pytest
from collector.checks.net_dns import DnsCheck, dns_resolve
from collector.config import load_settings


class _FakeResolver:
    def __init__(self, raises: Exception | None = None):
        self.nameservers: list[str] | None = None
        self.calls: list[tuple] = []
        self._raises = raises

    async def resolve(self, hostname, record_type, lifetime=None):
        self.calls.append((hostname, record_type, lifetime))
        if self._raises:
            raise self._raises
        return None


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


class TestDnsCheck:
    def test_interval_s_from_config(self):
        settings = load_settings(collector_id="c", dns={"interval_s": 45})
        check = DnsCheck(settings, meter=None, target="example.com")
        assert check.interval_s == 45

    def test_semaphore_stored(self):
        settings = load_settings(collector_id="c")
        sem = asyncio.Semaphore(3)
        check = DnsCheck(settings, meter=None, target="example.com", semaphore=sem)
        assert check.semaphore is sem

    async def test_run_ok_result(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = DnsCheck(settings, meter=None, target="example.com", record_type="A")

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
        check = DnsCheck(settings, meter=None, target="nope.invalid", record_type="A")

        async def failing_resolve(hostname, record_type, *, timeout_s, resolver=None, **kw):
            raise dns.resolver.NXDOMAIN()

        monkeypatch.setattr("collector.checks.net_dns.dns_resolve", failing_resolve)
        result = await check.run()

        assert result.ok is False
        assert result.labels == {"target": "nope.invalid", "record_type": "A"}
        assert result.error is not None

    def test_default_record_type_is_a(self):
        settings = load_settings(collector_id="c")
        check = DnsCheck(settings, meter=None, target="example.com")
        assert check.record_type == "A"
