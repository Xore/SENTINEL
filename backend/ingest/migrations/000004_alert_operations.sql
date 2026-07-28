-- Site-scoped alert instance lifecycle: instances, acknowledgements, and
-- time-bound silences. Alert instances deduplicate per site on dedup_key so
-- repeated raises of the same condition stay idempotent.

CREATE TABLE alert_instances (
    alert_id UUID PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    dedup_key TEXT NOT NULL CHECK (
        char_length(dedup_key) BETWEEN 1 AND 200
        AND dedup_key = btrim(dedup_key)
    ),
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    summary TEXT NOT NULL CHECK (
        char_length(summary) BETWEEN 1 AND 500
        AND summary = btrim(summary)
    ),
    source TEXT NOT NULL CHECK (
        char_length(source) BETWEEN 1 AND 100
        AND source = btrim(source)
    ),
    fired_at TIMESTAMPTZ NOT NULL,
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    created_by TEXT NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by TEXT REFERENCES users(user_id),
    silenced_until TIMESTAMPTZ,
    silenced_by TEXT REFERENCES users(user_id),
    silence_reason TEXT CHECK (
        silence_reason IS NULL
        OR (
            char_length(silence_reason) BETWEEN 1 AND 500
            AND silence_reason = btrim(silence_reason)
        )
    ),
    UNIQUE (site_id, dedup_key),
    CHECK (
        (acknowledged_at IS NULL AND acknowledged_by IS NULL)
        OR (acknowledged_at IS NOT NULL AND acknowledged_by IS NOT NULL)
    ),
    CHECK (
        (silenced_until IS NULL AND silenced_by IS NULL)
        OR (silenced_until IS NOT NULL AND silenced_by IS NOT NULL)
    )
);

CREATE INDEX alert_instances_site_fired_idx
    ON alert_instances (site_id, fired_at DESC, alert_id DESC);
CREATE INDEX alert_instances_open_idx
    ON alert_instances (site_id, silenced_until)
    WHERE acknowledged_at IS NULL;

-- Extend the append-only operational audit contract with exactly the alert
-- actions and resource type this migration implements.
ALTER TABLE operational_audit_log
    DROP CONSTRAINT operational_audit_log_action_check;
ALTER TABLE operational_audit_log
    ADD CONSTRAINT operational_audit_log_action_check
    CHECK (
        action IN (
            'maintenance.created',
            'maintenance.ended',
            'alert.raised',
            'alert.acknowledged',
            'alert.silenced'
        )
    );
ALTER TABLE operational_audit_log
    DROP CONSTRAINT operational_audit_log_resource_type_check;
ALTER TABLE operational_audit_log
    ADD CONSTRAINT operational_audit_log_resource_type_check
    CHECK (resource_type IN ('maintenance_window', 'alert_instance'));
