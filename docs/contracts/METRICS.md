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
`record_type`, `site_id`, and `collector_id`. `record_type` is restricted to
the configured DNS allow-list; it is never arbitrary response data.

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

## Phase 2 core network families

All target-bearing families use the operator-assigned `target_id`; raw hosts,
IP addresses, ports, URLs, paths, queries, and credentials are forbidden as
metric attributes. Cardinality below is expressed as logical instrument series
before any backend histogram projection.

| Metric | Type | Unit | Extra labels | Cardinality |
|---|---|---|---|---:|
| `sentinel_collector_icmp_rtt_seconds` | histogram | seconds | `target_id` | <= 32/collector |
| `sentinel_collector_icmp_loss_ratio` | gauge | `1` | `target_id` | <= 32/collector |
| `sentinel_collector_tcp_connect_seconds` | histogram | seconds | `target_id` | <= 32/collector |
| `sentinel_collector_http_response_seconds` | histogram | seconds | `target_id`, `state` (`ok`/`error`) | <= 64/collector |
| `sentinel_collector_dns_resolve_seconds` | histogram | seconds | `target_id`, `record_type` | <= 256/collector |
| `sentinel_collector_latency_rtt_seconds` | gauge | seconds | `target_id` | <= 32/collector |
| `sentinel_collector_latency_jitter_seconds` | gauge | seconds | `target_id` | <= 32/collector |
| `sentinel_collector_latency_loss_ratio` | gauge | `1` | `target_id` | <= 32/collector |

The target configuration contract is:

- at most 32 targets per check family and unique `target_id` values within that
  family;
- `target_id` is an explicit DNS-label-style identifier and is never derived
  from target content;
- ICMP, TCP, HTTP, DNS, and latency use structured targets containing
  `target_id` plus the operational host/port/URL fields;
- DNS `record_type` is one of `A`, `AAAA`, `CNAME`, `MX`, `NS`, `PTR`, `SRV`,
  or `TXT`;
- HTTP `state` is exactly `ok` or `error`; status codes remain in structured
  logs/results, not metric labels;
- millisecond and percentage probe results are converted to seconds and ratios
  before recording.

Latency probing has a separate configuration section, is disabled by default,
and runs in addition to the lightweight ICMP check only when explicitly
enabled with its own targets. This avoids multiplying packet volume silently.
Each per-type `enabled` flag gates construction in the collector entry point;
scan level remains the independent scheduler eligibility gate.

## Site API query catalogue

The bounded range-query API accepts the exact canonical names above. For every
histogram family it additionally accepts the Prometheus projections ending in
`_bucket`, `_count`, and `_sum`. Arbitrary MetricsQL expressions, compatibility
aliases, and metrics outside this catalogue are not accepted.

## Contract enforcement

- Collector tests verify names/types/units.
- Ingest validates required identity and rejects forbidden/unbounded attributes.
- A compatibility test queries VictoriaMetrics after an OTLP fixture export.
