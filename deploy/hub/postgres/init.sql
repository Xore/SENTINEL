-- Dev-only hub schema bootstrap for the Phase 1 integration test. Minimal
-- collector registry — not the full production schema (docs/architecture/
-- ARCHITECTURE-V2.md), which also covers RBAC, PKI records, and evidence
-- bundles.

CREATE TABLE IF NOT EXISTS sites (
    site_id TEXT PRIMARY KEY,
    display_name TEXT
);

INSERT INTO sites (site_id, display_name)
VALUES ('default', 'Default site')
ON CONFLICT (site_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS collectors (
    collector_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen TIMESTAMPTZ,
    health_score DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    collector_id TEXT NOT NULL REFERENCES collectors(collector_id),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    details JSONB
);
