-- SENTINEL site foundation schema.
-- Applied by the migration runner under a PostgreSQL advisory lock.

CREATE TABLE sites (
    site_id TEXT PRIMARY KEY
        CHECK (site_id ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'),
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE collectors (
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    collector_id TEXT NOT NULL
        CHECK (collector_id ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'),
    certificate_serial TEXT,
    certificate_not_after TIMESTAMPTZ,
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at TIMESTAMPTZ,
    last_seen TIMESTAMPTZ,
    PRIMARY KEY (site_id, collector_id),
    UNIQUE (certificate_serial)
);

CREATE TABLE enrollment_tokens (
    token_sha256 BYTEA PRIMARY KEY CHECK (octet_length(token_sha256) = 32),
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    collector_id TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (site_id, collector_id)
        REFERENCES collectors(site_id, collector_id)
);

CREATE TABLE durable_events (
    tenant_id TEXT NOT NULL DEFAULT 'local',
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    event_id UUID NOT NULL,
    collector_id TEXT,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    event_type TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    idempotency_key TEXT NOT NULL,
    content_sha256 BYTEA NOT NULL CHECK (octet_length(content_sha256) = 32),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, site_id, event_id),
    UNIQUE (tenant_id, site_id, idempotency_key),
    FOREIGN KEY (site_id, collector_id)
        REFERENCES collectors(site_id, collector_id)
);

CREATE INDEX durable_events_site_time_idx
    ON durable_events (site_id, occurred_at DESC);
CREATE INDEX durable_events_type_time_idx
    ON durable_events (event_type, occurred_at DESC);

CREATE TABLE federation_outbox (
    tenant_id TEXT NOT NULL DEFAULT 'local',
    site_id TEXT NOT NULL,
    event_id UUID NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at TIMESTAMPTZ,
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, site_id, event_id),
    FOREIGN KEY (tenant_id, site_id, event_id)
        REFERENCES durable_events(tenant_id, site_id, event_id)
        ON DELETE CASCADE
);

CREATE INDEX federation_outbox_pending_idx
    ON federation_outbox (next_attempt_at)
    WHERE acknowledged_at IS NULL;
