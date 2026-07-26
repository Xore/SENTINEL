-- Site API users and site-scoped authorization.
-- Token issuance remains outside the API; these rows are the current
-- authorization authority used to reject disabled users and stale role/token
-- assignments.

CREATE TABLE users (
    user_id TEXT PRIMARY KEY
        CHECK (user_id ~ '^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$'),
    role TEXT NOT NULL
        CHECK (role IN ('viewer', 'operator', 'analyst', 'admin', 'ot-operator')),
    token_not_before TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    disabled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_site_access (
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    site_id TEXT NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, site_id)
);

CREATE INDEX user_site_access_site_idx ON user_site_access (site_id, user_id);
