# ADR 0007 — Production HA and Version Pinning

- **Status:** Accepted
- **Date:** 2026-07-26

## Decision

Production images are pinned to tested immutable versions or digests; `latest`
is prohibited. HA is an optional Compose profile implemented only after the
single-site baseline passes disaster-recovery tests.

HA uses:

- site vmagent dual-write to independent VictoriaMetrics nodes with query
  deduplication;
- Patroni with a quorum-capable DCS, PgBouncer, tested backups, and fencing;
- redundant stateless ingest and API instances;
- active/standby analysis protected by PostgreSQL advisory lock plus
  transaction-level ownership checks.

Placeholder Compose fragments are not deployable configuration. Every HA service
requires health/readiness checks and a documented RPO/RTO failure drill.
