# ADR 0003 — Federation Transport and Event Replication

- **Status:** Accepted
- **Date:** 2026-07-26

## Decision

The default federation agent is a Go service. It forwards:

1. an allow-listed aggregate metric subset through site `vmagent`;
2. versioned event envelopes to an idempotent global HTTPS ingestion API over
   mTLS;
3. site heartbeats every 60 seconds;
4. model updates through the federated-learning protocol.

Application-level event replication is the portable default. PostgreSQL logical
replication is an optional trusted-network deployment profile and must never be
required for normal federation.

The federation queue is site-PostgreSQL-backed. Global acknowledgements are by
event ID. At-least-once delivery plus global uniqueness provides effective
exactly-once storage.

## Consequences

- Site-local tables remain authoritative for site events.
- Global outage does not block local writes.
- Replication is observable through queue depth, oldest age, retry count,
  rejected count, and acknowledged throughput.
