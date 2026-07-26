# Dev hub stack

This disposable stack runs the production Go migration, enrollment, mTLS
identity, PostgreSQL authorization, and OTLP ingest code for the Phase 1 gate:
a collector enrolls and its heartbeat lands in VictoriaMetrics.

The `pki-init` container only generates a throwaway development CA and server
certificate. It does not expose the old stub enrollment server. The Go
`ingest` service owns both `POST /api/pki/enroll` and OTLP authorization.

## Start

```bash
docker compose -f deploy/hub/docker-compose.dev.yml up -d --build
docker compose -f deploy/hub/docker-compose.dev.yml ps
```

The deterministic development identity is:

- site: `site-a`
- collector: `dev-node-1`
- one-time token: `dev-only-bootstrap-token`

Never use this identity or token outside the disposable dev stack.

## Run a collector

Enrollment itself is HTTPS. Copy the throwaway CA out of the named volume so
Python can authenticate the enrollment server before it has a client
certificate:

```bash
docker compose -f deploy/hub/docker-compose.dev.yml \
  cp pki-init:/pki/ca.crt /tmp/sentinel-dev-ca.crt

cd collector
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cd ..

SSL_CERT_FILE=/tmp/sentinel-dev-ca.crt \
COLLECTOR_ID=dev-node-1 \
SITE_ID=site-a \
BACKEND__PKI_DIR=/tmp/dev-node-1-pki \
BACKEND__URL=https://localhost:4317 \
BACKEND__ENROLL_URL=https://localhost:8443/api/pki/enroll \
BACKEND__BOOTSTRAP_TOKEN=dev-only-bootstrap-token \
python3 -m collector
```

The token is consumed once. Remove the three files under
`/tmp/dev-node-1-pki` only together with a fresh `docker compose down -v`;
otherwise reenrollment correctly fails.

## Verify

```bash
curl -fsS \
  'http://localhost:8428/api/v1/query?query=sentinel_collector_heartbeat_total' \
  | python3 -m json.tool
```

Expect one series labeled `collector_id="dev-node-1"` and `site_id="site-a"`.
The ingest logs must show no unauthenticated fallback:

```bash
docker compose -f deploy/hub/docker-compose.dev.yml logs ingest
```

## Tear down

```bash
docker compose -f deploy/hub/docker-compose.dev.yml down -v
rm -rf /tmp/dev-node-1-pki /tmp/sentinel-dev-ca.crt
```

The CA key is deliberately shared between the one-shot initializer and Go
ingest inside a private throwaway volume. Production uses an external secret
provider/HSM boundary and the deployment strategy in
`docs/architecture/IaC-DEPLOYMENT-STRATEGY.md`.
