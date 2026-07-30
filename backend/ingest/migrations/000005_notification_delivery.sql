-- Site-scoped durable notification outbox with claim leases, bounded retry
-- scheduling, and append-only attempt history. Payloads carry metadata only;
-- endpoint credentials and raw secrets must never be stored here. Attempt
-- history is the delivery record and is never updated or deleted.

CREATE TABLE notification_outbox (
    notification_id UUID PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    channel TEXT NOT NULL CHECK (channel IN ('webhook', 'smtp')),
    dedup_key TEXT NOT NULL CHECK (
        char_length(dedup_key) BETWEEN 1 AND 200
        AND dedup_key = btrim(dedup_key)
    ),
    payload JSONB NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND octet_length(payload::text) <= 8192
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'leased', 'delivered', 'dead')
    ),
    attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INT NOT NULL DEFAULT 8 CHECK (max_attempts BETWEEN 1 AND 32),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    leased_by TEXT CHECK (
        leased_by IS NULL
        OR (char_length(leased_by) BETWEEN 1 AND 100 AND leased_by = btrim(leased_by))
    ),
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT CHECK (
        last_error IS NULL
        OR (char_length(last_error) BETWEEN 1 AND 500 AND last_error = btrim(last_error))
    ),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    created_by TEXT NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ,
    UNIQUE (site_id, channel, dedup_key),
    CHECK ((leased_by IS NULL) = (lease_expires_at IS NULL)),
    CHECK ((status = 'delivered') = (delivered_at IS NOT NULL)),
    CHECK (status IN ('pending', 'leased') OR leased_by IS NULL)
);

-- Deterministic pending order: earliest scheduled attempt first, stable
-- notification_id tiebreak. Partial index keeps terminal rows out.
CREATE INDEX notification_outbox_pending_idx
    ON notification_outbox (next_attempt_at, notification_id)
    WHERE status IN ('pending', 'leased');
CREATE INDEX notification_outbox_site_idx
    ON notification_outbox (site_id, created_at DESC, notification_id DESC);

CREATE TABLE notification_attempts (
    attempt_id UUID PRIMARY KEY,
    notification_id UUID NOT NULL
        REFERENCES notification_outbox(notification_id) ON DELETE CASCADE,
    attempt_no INT NOT NULL CHECK (attempt_no > 0),
    outcome TEXT NOT NULL CHECK (
        outcome IN ('success', 'retryable_failure', 'permanent_failure')
    ),
    detail TEXT NOT NULL DEFAULT '' CHECK (octet_length(detail) <= 500),
    attempted_by TEXT NOT NULL CHECK (
        char_length(attempted_by) BETWEEN 1 AND 100
        AND attempted_by = btrim(attempted_by)
    ),
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (notification_id, attempt_no)
);

CREATE FUNCTION reject_notification_attempt_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'notification attempt records are append-only';
END;
$$;

CREATE TRIGGER notification_attempts_no_update
BEFORE UPDATE OR DELETE ON notification_attempts
FOR EACH ROW EXECUTE FUNCTION reject_notification_attempt_mutation();
