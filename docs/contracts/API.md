# Site API Contract

## Versioning and transport

- REST endpoints are rooted at `/api/v1`.
- Production transport is HTTPS through the site reverse proxy.
- Responses are JSON. Timestamps use RFC 3339 UTC.
- The API is stateless; PostgreSQL is the current authorization and fleet-state
  authority.

## Authentication

`/healthz` and `/readyz` are unauthenticated. Every `/api/v1/**` endpoint
requires:

```text
Authorization: Bearer <JWT>
```

The Phase 1 deployment accepts only HS256 with a secret of at least 256 bits.
The validator requires and verifies:

- `sub`: database `users.user_id`;
- `iss`: configured issuer, default `sentinel-site`;
- `aud`: configured audience, default `sentinel-site-api`;
- `iat`, `nbf`, and `exp`; tokens must be short-lived;
- `role`: `viewer`, `operator`, `analyst`, `admin`, or `ot-operator`;
- `site_ids`: non-empty bounded array of site identifiers.

The signing algorithm is fixed by server configuration and never selected from
the token without an allow-list. The current database user must be enabled, its
role must equal the token role, `iat` must be on or after
`users.token_not_before`, and requested rows must be authorized by both the JWT
site scope and `user_site_access`. This makes user disablement, role changes,
and token revocation effective without waiting for token expiry.

The API does not issue JWTs. Production token issuance and key rotation belong
to the deployment identity provider. A later asymmetric/JWKS implementation
may replace HS256 without changing endpoint authorization semantics.

## Errors

Errors never include SQL, stack traces, token details, or internal dependency
messages:

```json
{
  "error": {
    "code": "unauthorized",
    "message": "authentication required",
    "request_id": "4eb0d0a2356042dcb3a41153a61876ef"
  }
}
```

Defined Phase 1 codes:

| HTTP | Code | Meaning |
|---:|---|---|
| 401 | `unauthorized` | Missing, malformed, invalid, expired, or unsupported token |
| 503 | `unavailable` | API dependency is not ready or a bounded query failed |

Every response includes `X-Request-ID` and `Cache-Control: no-store`.

## Health

### `GET /healthz`

Process liveness. Returns `200 {"status":"ok"}` without checking dependencies.

### `GET /readyz`

Database readiness. Returns `200 {"status":"ready"}` or the uniform `503`
error.

## Collectors

### `GET /api/v1/collectors`

Minimum role: any enabled role; data is always site-scoped.

Returns collectors in stable `(site_id, collector_id)` order:

```json
{
  "data": [
    {
      "site_id": "site-a",
      "collector_id": "dev-node-1",
      "state": "active",
      "last_seen": "2026-07-26T10:00:00Z",
      "silence_seconds": 12,
      "enrolled_at": "2026-07-26T09:00:00Z",
      "certificate_not_after": "2026-10-24T09:00:00Z",
      "cert_expires_in_days": 89
    }
  ]
}
```

`state` is one of:

- `disabled`;
- `never_seen`;
- `stale` when the most recent accepted OTLP batch is older than five minutes;
- `active`.

Unauthorized sites are indistinguishable from sites with no collectors: rows
outside the intersection of JWT and database scope are omitted.
