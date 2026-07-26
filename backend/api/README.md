# SENTINEL site API

The site API is a stateless Go/Gin service. Its first vertical slice exposes
unauthenticated liveness/readiness and an authenticated, site-scoped collector
fleet view backed by PostgreSQL.

Required environment variables:

- `SENTINEL_DATABASE_URL`
- `SENTINEL_API_JWT_SECRET` (at least 32 bytes)

Optional settings:

- `SENTINEL_API_ADDRESS` (default `:8080`)
- `SENTINEL_API_JWT_ISSUER` (default `sentinel-site`)
- `SENTINEL_API_JWT_AUDIENCE` (default `sentinel-site-api`)
- `SENTINEL_API_VM_QUERY_URL` (default `http://victoriametrics:8428`)

The API never issues tokens. An identity provider or the deployment's
authentication boundary issues short-lived tokens according to
`docs/contracts/API.md`.
