# ADR 0009 — Identity, Tenancy, and Time Invariants

- **Status:** Accepted
- **Date:** 2026-07-26

## Decision

- `site_id` and `collector_id` are lower-case DNS-label-compatible identifiers,
  1–63 characters each.
- Collector identity is the tuple `(site_id, collector_id)` and must be unique.
- A certificate binds both values; payload attributes cannot override them.
- Global data additionally carries `tenant_id`; it is derived from authenticated
  server-side enrollment, never accepted from an untrusted query/body as scope.
- Durable IDs use UUIDv7 where the runtime has a vetted implementation;
  otherwise UUIDv4 plus a separate UTC timestamp.
- Records use UTC RFC 3339 timestamps. Durations and scheduler decisions use
  monotonic clocks.
- Services expose clock-offset health. Correlation uses event time plus recorded
  clock uncertainty and ingestion time.

## Consequences

Every database key, API authorization query, metric validation path, and
federation envelope applies the same identity rules.
