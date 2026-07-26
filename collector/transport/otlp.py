"""OTLP/gRPC metric export — wires an mTLS-secured `OTLPMetricExporter` into
an OpenTelemetry `MeterProvider` for the collector's self-metrics and (in
later phases) check metrics.
"""
from __future__ import annotations

from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

import collector
from collector.config import CollectorSettings
from collector.transport.mtls import load_channel_credentials

METER_NAME = "analyselaptop.collector"

# docs/contracts/METRICS.md's required-attributes table.
SERVICE_NAME = "sentinel-collector"


def build_meter_provider(settings: CollectorSettings) -> MeterProvider:
    """Build a MeterProvider that exports via OTLP/gRPC with mTLS to `backend.url`.

    Raises `collector.transport.mtls.MtlsCredentialError` if the collector
    has not been enrolled yet (see `collector.pki.enroll.ensure_enrolled`).
    """
    credentials = load_channel_credentials(settings.backend.pki_dir)
    exporter = OTLPMetricExporter(endpoint=settings.backend.url, credentials=credentials)
    reader = PeriodicExportingMetricReader(exporter)
    resource = Resource.create(
        {
            # Dotted "service.name"/"service.version" are standard OTel
            # semantic-convention resource attributes with dedicated
            # promotion handling in the OTLP/Prometheus remote-write path
            # (service.name -> the `job` label, always; also -> the
            # generically-converted `service_name` label when
            # resource_to_telemetry_conversion is enabled — see
            # docs/contracts/METRICS.md's required-attributes table, which
            # specifies the resulting underscored `service_name` label).
            "service.name": SERVICE_NAME,
            "service.version": collector.__version__,
            # Underscored, not OTel's usual dotted resource-attribute style
            # ("collector.id") — Prometheus/VictoriaMetrics label names can't
            # contain dots, and every metric in this project's naming
            # convention (docs/contracts/METRICS.md) uses
            # {collector_id, site_id} as the label names directly (no
            # promotion/sanitization involved). Confirmed via the Phase 1
            # hub integration test: dotted names were silently dropped by
            # the remote-write exporter's resource-to-label conversion
            # instead of being sanitized.
            "collector_id": settings.collector_id,
            "site_id": settings.site_id,
        }
    )
    return MeterProvider(metric_readers=[reader], resource=resource)


def get_meter(provider: MeterProvider) -> Meter:
    return provider.get_meter(METER_NAME)


def shutdown_meter_provider(provider: MeterProvider) -> None:
    provider.shutdown()
