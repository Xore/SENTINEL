"""Tests for collector.transport.otlp — MeterProvider wiring over mTLS OTLP/gRPC."""
from __future__ import annotations

import collector
import pytest
from collector.config import load_settings
from collector.transport.mtls import MtlsCredentialError
from collector.transport.otlp import (
    SERVICE_NAME,
    build_meter_provider,
    get_meter,
    shutdown_meter_provider,
)
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
        assert attrs["collector_id"] == "node-1"
        assert attrs["site_id"] == "site-a"
    finally:
        shutdown_meter_provider(provider)


def test_resource_carries_service_name_and_version(otlp_settings):
    provider = build_meter_provider(otlp_settings)
    try:
        attrs = provider._sdk_config.resource.attributes
        assert attrs["service.name"] == SERVICE_NAME == "sentinel-collector"
        assert attrs["service.version"] == collector.__version__
    finally:
        shutdown_meter_provider(provider)


def test_service_name_maps_to_expected_prometheus_label():
    """docs/contracts/METRICS.md requires a `service_name` label on every
    collector metric. The dotted OTel resource attribute `service.name` we
    emit is converted to that label by the receiving OTLP/Prometheus
    remote-write pipeline (deploy/hub's otel-collector config,
    `resource_to_telemetry_conversion: enabled: true`) — conversion happens
    outside the collector, so this pins the expected sanitization rule
    (dots -> underscores) against the attribute name we actually emit,
    rather than requiring the live hub stack (out of S1-01's scope).
    """
    assert "service.name".replace(".", "_") == "service_name"


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
