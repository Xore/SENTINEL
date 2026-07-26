# Durable Event Contract

Events include anomalies, RCA results, alerts, audit-derived exports, federation
heartbeats, and model-round messages. Metrics are not wrapped as events.

## Delivery semantics

- Producers create the event ID once and retain it across retries.
- Delivery is at least once.
- Consumers enforce uniqueness by `(tenant_id, site_id, event_id)`.
- A duplicate with the same content hash returns the original acknowledgement.
- A duplicate ID with a different hash is rejected and audited.
- Producers keep an event until a durable acknowledgement is received.

## Envelope rules

The machine-readable schema is `event-envelope.schema.json`.

- `schema_version` uses an integer major version.
- `event_type` is a stable dotted identifier such as `anomaly.detected`.
- `occurred_at` is producer event time; `observed_at` is first site ingestion
  time.
- `site_id`/`collector_id` follow ADR 0009.
- `idempotency_key` normally equals `event_id`.
- `payload` is typed by `(schema_version, event_type)`.
- `content_sha256` is lowercase hex SHA-256 of RFC 8785-canonicalized `payload`.
- Sensitive values are excluded or redacted before envelope creation.

## Compatibility

Consumers:

- accept unknown additive payload fields;
- reject unsupported major envelope versions;
- quarantine unknown event types instead of discarding them;
- never reinterpret an existing field;
- record validation rejection metrics without putting raw payloads in logs.
