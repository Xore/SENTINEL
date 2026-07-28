-- Site-local operational maintenance and append-only audit foundation.

CREATE TABLE maintenance_windows (
    window_id UUID PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    reason TEXT NOT NULL CHECK (
        char_length(reason) BETWEEN 1 AND 500
        AND reason = btrim(reason)
    ),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    created_by TEXT NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    ended_by TEXT REFERENCES users(user_id),
    CHECK (ends_at > starts_at),
    CHECK (ends_at <= starts_at + interval '31 days'),
    CHECK (
        (ended_at IS NULL AND ended_by IS NULL)
        OR (ended_at IS NOT NULL AND ended_by IS NOT NULL)
    )
);

CREATE INDEX maintenance_windows_site_time_idx
    ON maintenance_windows (site_id, starts_at DESC, window_id DESC);
CREATE INDEX maintenance_windows_open_idx
    ON maintenance_windows (site_id, ends_at)
    WHERE ended_at IS NULL;

CREATE TABLE operational_audit_log (
    audit_id UUID PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    actor_user_id TEXT NOT NULL REFERENCES users(user_id),
    action TEXT NOT NULL CHECK (
        action IN ('maintenance.created', 'maintenance.ended')
    ),
    resource_type TEXT NOT NULL CHECK (
        resource_type IN ('maintenance_window')
    ),
    resource_id UUID NOT NULL,
    resource_version BIGINT NOT NULL CHECK (resource_version > 0),
    details JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(details) = 'object'),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX operational_audit_site_time_idx
    ON operational_audit_log (site_id, occurred_at DESC, audit_id DESC);
CREATE INDEX operational_audit_resource_idx
    ON operational_audit_log (resource_type, resource_id, resource_version);

CREATE FUNCTION reject_operational_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'operational audit records are append-only';
END;
$$;

CREATE TRIGGER operational_audit_no_update
BEFORE UPDATE OR DELETE ON operational_audit_log
FOR EACH ROW EXECUTE FUNCTION reject_operational_audit_mutation();
