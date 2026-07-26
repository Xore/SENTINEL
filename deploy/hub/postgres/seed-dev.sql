-- Deterministic, dev-only enrollment identity for the Phase 1 E2E gate.
-- Token plaintext: dev-only-bootstrap-token
INSERT INTO sites (site_id, display_name)
VALUES ('site-a', 'Phase 1 development site')
ON CONFLICT (site_id) DO NOTHING;

INSERT INTO collectors (site_id, collector_id)
VALUES ('site-a', 'dev-node-1')
ON CONFLICT (site_id, collector_id) DO NOTHING;

INSERT INTO enrollment_tokens (
    token_sha256,
    site_id,
    collector_id,
    expires_at
)
VALUES (
    decode('9aa29a0009ab871ca3d3874e53b51ed427b286122bab4eef3df0009d52162222', 'hex'),
    'site-a',
    'dev-node-1',
    now() + interval '24 hours'
)
ON CONFLICT (token_sha256) DO NOTHING;

INSERT INTO users (user_id, role)
VALUES ('dev-viewer', 'viewer')
ON CONFLICT (user_id) DO UPDATE
SET role = EXCLUDED.role,
    token_not_before = '-infinity',
    disabled_at = NULL;

INSERT INTO user_site_access (user_id, site_id)
VALUES ('dev-viewer', 'site-a')
ON CONFLICT (user_id, site_id) DO NOTHING;
