# SENTINEL Cross-Service Contracts

These contracts are the stable boundary between collector, ingest, analysis,
API, federation, global services, and frontends.

| Contract | Purpose |
|---|---|
| [`METRICS.md`](METRICS.md) | Metric naming, labels, units, and cardinality |
| [`EVENTS.md`](EVENTS.md) | Durable event envelope and idempotency |
| [`event-envelope.schema.json`](event-envelope.schema.json) | Machine-readable event schema |
| [`SERVICE-BOUNDARIES.md`](SERVICE-BOUNDARIES.md) | Component ownership and data flow |

Contract changes require:

1. a schema/version compatibility statement;
2. producer and consumer tests;
3. an upgrade and rollback path;
4. a coordination-ledger handoff before implementation.
