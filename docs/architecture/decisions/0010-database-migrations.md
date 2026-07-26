# ADR 0010 — Database Migration Policy

- **Status:** Accepted
- **Date:** 2026-07-26

## Decision

Use versioned SQL migrations owned by `backend/`. `init.sql` may bootstrap the
migration role/database but may not define evolving application schema.

Migrations are:

- immutable after merge;
- forward-only in production;
- transactional where PostgreSQL permits;
- protected by a global advisory migration lock;
- compatible with the previously deployed application during rolling upgrades;
- tested from empty database and from the latest released schema.

Rollback is application rollback plus a restore/forward-fix procedure, not
destructive down migrations. Destructive column/table removal requires a
multi-release expand/migrate/contract sequence.
