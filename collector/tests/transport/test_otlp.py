"""Tests for collector.transport.otlp — MeterProvider wiring over mTLS OTLP/gRPC."""
from __future__ import annotations

import pytest
from collector.config import load_settings
from collector.transport.mtls import MtlsCredentialError
from collector.transport.otlp import build_meter_provider, get_meter, shutdown_meter_provider
from opentelemetry.sdk.metrics import Meter, MeterProvider


@pytest.fixture
def otlp_settings(enrolled_pki_dir):
    return load_settings(
        collector_id="node-1",
        site_id="site-a",
        backend={"pki_dir": str(enrolled_pki_dir), "url": "https://localhost:4317"},
    )


def test_build_meter_provider_returns_meter_provider(otlp_settings):
    provider = build_meter_provider(otlp_settings)
    try:
        assert isinstance(provider, MeterProvider)
    finally:
        shutdown_meter_provider(provider)


def test_resource_carries_collector_and_site_id(otlp_settings):
    provider = build_meter_provider(otlp_settings)
    try:
        attrs = provider._sdk_config.resource.attributes
        assert attrs["collector.id"] == "node-1"
        assert attrs["site.id"] == "site-a"
        assert attrs["service.name"] == "analyselaptop-collector"
    finally:
        shutdown_meter_provider(provider)


def test_get_meter_returns_meter(otlp_settings):
    provider = build_meter_provider(otlp_settings)
    try:
        meter = get_meter(provider)
        assert isinstance(meter, Meter)
    finally:
        shutdown_meter_provider(provider)


def test_missing_enrollment_raises_mtls_error(tmp_path):
    settings = load_settings(
        collector_id="node-1",
        backend={"pki_dir": str(tmp_path / "pki")},
    )
    with pytest.raises(MtlsCredentialError):
        build_meter_provider(settings)
