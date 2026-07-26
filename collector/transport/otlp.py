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

from collector.config import CollectorSettings
from collector.transport.mtls import load_channel_credentials

METER_NAME = "analyselaptop.collector"


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
            "service.name": "analyselaptop-collector",
            # Underscored, not OTel's usual dotted resource-attribute style
            # ("collector.id") — Prometheus/VictoriaMetrics label names can't
            # contain dots, and every metric in this project's naming
            # convention (COLLECTOR-V2-REFACTOR.md §10) uses
            # {collector_id, site_id} as the label names. Confirmed via the
            # Phase 1 hub integration test: dotted names were silently
            # dropped by the remote-write exporter's resource-to-label
            # conversion instead of being sanitized.
            "collector_id": settings.collector_id,
            "site_id": settings.site_id,
        }
    )
    return MeterProvider(metric_readers=[reader], resource=resource)


def get_meter(provider: MeterProvider) -> Meter:
    return provider.get_meter(METER_NAME)


def shutdown_meter_provider(provider: MeterProvider) -> None:
    provider.shutdown()
