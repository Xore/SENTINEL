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
| 400 | `invalid_request` | Query parameters are missing, malformed, unsupported, or exceed a bound |
| 401 | `unauthorized` | Missing, malformed, invalid, expired, or unsupported token |
| 403 | `forbidden` | The authenticated role cannot perform the requested mutation |
| 404 | `not_found` | The requested site does not exist or is outside current authorization |
| 409 | `conflict` | The supplied optimistic-concurrency version is stale |
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

## Metrics

### `GET /api/v1/metrics/range`

Returns a bounded Prometheus matrix for one canonical metric family. This
endpoint does not accept arbitrary MetricsQL. Required parameters:

| Parameter | Contract |
|---|---|
| `metric` | Exact API query name from the Metrics Contract catalogue |
| `site_id` | One ADR 0009 site identifier authorized by both JWT and database |
| `start`, `end` | RFC 3339 timestamps; increasing range of at most 24 hours |
| `step` | Integer seconds from 10 through 3,600; at most 2,000 evaluation points |

`collector_id` is optional and, when supplied, must be one ADR 0009 collector
identifier. Unknown or duplicate parameters are rejected.

The API injects `site_id` (and optional `collector_id`) through
VictoriaMetrics `extra_label`; it never interpolates identifiers into query
text. It denies partial results, uses a finite upstream timeout, and rejects
responses larger than 4 MiB, 500 series, or 50,000 samples. It also verifies
the requested identity on every returned series before responding.

Example response:

```json
{
  "data": {
    "result_type": "matrix",
    "result": [
      {
        "metric": {
          "__name__": "sentinel_collector_heartbeat_total",
          "site_id": "site-a",
          "collector_id": "dev-node-1"
        },
        "values": [[1785067200, "1"]]
      }
    ]
  }
}
```

An unauthorized site returns the same `404 not_found` response whether the site
does not exist, is absent from the JWT, or is absent from current database
access. VictoriaMetrics is not queried in those cases.

## Maintenance windows

Maintenance windows are site-wide operational records. They suppress or
annotate alerting and provide contamination masks to future analysis/training
jobs; the API does not directly control those consumers.

`viewer` may list windows. Creating or ending a window requires `operator`,
`analyst`, `admin`, or `ot-operator`. Every query revalidates the current user,
role, token-not-before boundary, JWT site scope, and database site access.
Missing and unauthorized resources are indistinguishable.

A window has:

- server-generated UUID `id`;
- `site_id`;
- RFC 3339 UTC `starts_at` and `ends_at`, with a positive duration no longer
  than 31 days;
- a trimmed, non-empty `reason` of at most 500 UTF-8 bytes;
- derived state `scheduled`, `active`, or `ended`;
- positive optimistic-concurrency `version`;
- creator and creation timestamp; and
- optional explicit end actor and timestamp.

Creating and explicitly ending a window atomically append an immutable
operational audit record. Non-ended windows for the same site may not overlap;
concurrent creates are serialized per site and an overlap returns
`409 conflict`. Adjacent half-open intervals are allowed.

### `GET /api/v1/maintenance-windows`

Required `site_id`; optional `state` (`all`, `scheduled`, `active`, or `ended`)
and `limit` (1–200, default 50). Unknown or duplicate parameters are rejected.
Results use stable `(starts_at DESC, id DESC)` order.

### `POST /api/v1/maintenance-windows`

Request:

```json
{
  "site_id": "site-a",
  "starts_at": "2026-07-28T18:00:00Z",
  "ends_at": "2026-07-28T20:00:00Z",
  "reason": "PLC firmware maintenance"
}
```

Returns `201`, a `Location` header, and the created resource.

### `POST /api/v1/maintenance-windows/{id}/end`

Request:

```json
{"expected_version": 1}
```

Returns the ended resource with an incremented version. Repeating the mutation
or supplying a stale version returns `409 conflict`; malformed identifiers and
versions return `400 invalid_request`.
