# ADR 0002 — Telemetry Path and Metric Naming

- **Status:** Accepted
- **Date:** 2026-07-26

## Decision

Collectors send OTLP/gRPC over mTLS to the site `backend/ingest` service.
Ingest validates collector identity and required resource attributes, converts
and writes time series to the site VictoriaMetrics endpoint, and updates
PostgreSQL event/registry state where applicable.

Site `vmagent`, not each edge collector, performs optional dual-write to HA or
global VictoriaMetrics. This keeps WAN/global topology out of collector config
and preserves local autonomy.

New project-owned metrics use the `sentinel_` prefix. Existing
`collector_heartbeat_total` remains a temporary compatibility alias through the
Phase 1 migration. Metric names, types, units, required labels, and cardinality
limits are defined in `docs/contracts/METRICS.md`.

## Consequences

- Collector certificates authenticate only to site ingest.
- Ingest rejects a payload whose `collector_id`/`site_id` attributes conflict
  with the certificate identity.
- Arbitrary URLs, payload data, exception messages, SSIDs, and unbounded network
  identifiers cannot become labels.
