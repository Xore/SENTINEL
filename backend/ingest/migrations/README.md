# Ingest Database Migrations

Migrations follow ADR 0010.

- Files are named `<six-digit-version>_<description>.sql`.
- Applied files are immutable.
- The production runner holds a PostgreSQL advisory lock and records the file
  SHA-256 before committing the version.
- `deploy/hub/postgres/init.sql` only creates/bootstrap roles and invokes the
  migration process; it is not the evolving schema authority.

The first migration establishes certificate-bound `(site_id, collector_id)`
identity, consumed enrollment tokens, idempotent durable events, and the
federation outbox.
