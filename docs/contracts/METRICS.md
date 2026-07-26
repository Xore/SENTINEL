# Metrics Contract

## Naming

- New project metrics start with `sentinel_`.
- Use base SI units in names where Prometheus conventions require them:
  `_seconds`, `_bytes`, `_total`, `_ratio`.
- Counters end in `_total`; state and current values are gauges.
- Do not encode units in labels.

`collector_heartbeat_total` is a temporary Phase 1 compatibility name. Emit
`sentinel_collector_heartbeat_total` as canonical and retain the old name only
until consumers migrate.

## Required resource attributes

Every collector metric includes:

| Attribute | Rule |
|---|---|
| `site_id` | ADR 0009 identifier, certificate-bound |
| `collector_id` | ADR 0009 identifier, certificate-bound |
| `service_name` | `sentinel-collector` |
| `service_version` | released collector semantic version |

Ingest rejects missing or identity-conflicting attributes.

## Label policy

Allowed common labels are enumerated values or controlled identifiers:
`target_id`, `interface`, `check`, `metric_group`, `state`, `protocol`,
`site_id`, and `collector_id`.

Forbidden labels include:

- arbitrary exception/error text;
- raw URL/path/query values;
- packet payload or OT register content;
- unhashed user identifiers;
- dynamically generated request/event IDs;
- raw SSID when it can contain customer/user data;
- unbounded IP/MAC/flow tuples outside explicitly capped flow metrics.

Cardinality budgets must be stated beside each metric family. A default collector
budget is 2,000 active series; exceeding it emits a dropped-series metric rather
than creating more labels.

## Phase 1 canonical families

| Metric | Type | Unit | Extra labels | Cardinality |
|---|---|---|---|---:|
| `sentinel_collector_heartbeat_total` | counter | `1` | none | 1/collector |
| `sentinel_collector_check_runs_total` | counter | `1` | `check`, `outcome` | <= 64/collector |
| `sentinel_collector_check_duration_seconds` | histogram | seconds | `check` | <= 32/collector |
| `sentinel_collector_export_failures_total` | counter | `1` | `reason` enum | <= 8/collector |
| `sentinel_collector_cycle_duration_seconds` | histogram | seconds | none | 1/collector |
| `sentinel_collector_event_loop_lag_seconds` | gauge | seconds | none | 1/collector |

## Site API query catalogue

The bounded range-query API accepts the exact canonical names above. For the
two histogram families it additionally accepts the Prometheus projections
ending in `_bucket`, `_count`, and `_sum`. Arbitrary MetricsQL expressions,
compatibility aliases, and metrics outside this catalogue are not accepted by
the Phase 2 API slice.

## Contract enforcement

- Collector tests verify names/types/units.
- Ingest validates required identity and rejects forbidden/unbounded attributes.
- A compatibility test queries VictoriaMetrics after an OTLP fixture export.
