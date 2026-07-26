# Dev hub stack

Stands up just enough of a hub to run the Phase 1 integration test from
[`docs/guides/OPUS-AGENT-GUIDE-V2.md`](../../docs/guides/OPUS-AGENT-GUIDE-V2.md)
§4: *"collector connects, enrolls its certificate, and emits a heartbeat
metric that lands in VictoriaMetrics."* **Not the production hub** — see
[`docs/architecture/IaC-DEPLOYMENT-STRATEGY.md`](../../docs/architecture/IaC-DEPLOYMENT-STRATEGY.md)
for that. In particular:

- `stub-pki/` signs collector CSRs against a throwaway CA generated on
  first startup. It implements the same wire contract as the real hub's
  PKI endpoint (`collector/pki/enroll.py`'s `POST {collector_id, site_id,
  csr_pem} -> {certificate_pem, ca_certificate_pem}`), but has no
  bootstrap-token auth, no revocation, and is not the Go ingest service the
  design docs describe.
- `otel-collector/` (the real, off-the-shelf OpenTelemetry Collector,
  `otel/opentelemetry-collector-contrib`) terminates the collector's
  OTLP/gRPC + mTLS connection and forwards metrics to VictoriaMetrics via
  Prometheus remote-write. Stands in for the future Go ingest service.
- `postgres/init.sql` is a minimal `sites`/`collectors`/`events` schema,
  not the full production schema.

## Run it

```bash
docker compose -f deploy/hub/docker-compose.dev.yml up -d --build
```

Then run the collector against it from the repo root (adjust `COLLECTOR_ID`
per node; PKI enrollment is idempotent — rerunning with the same
`BACKEND__PKI_DIR` just reuses the existing cert):

```bash
cd collector && . .venv/bin/activate && cd ..
COLLECTOR_ID=dev-node-1 \
SITE_ID=site-a \
BACKEND__PKI_DIR=/tmp/dev-node-1-pki \
BACKEND__URL=https://localhost:4317 \
BACKEND__ENROLL_URL=http://localhost:8443/api/pki/enroll \
python3 -m collector
```

## Verify

```bash
curl -s 'http://localhost:8428/api/v1/query?query=collector_heartbeat_total' | python3 -m json.tool
```

Or open the VictoriaMetrics UI at <http://localhost:8428/vmui> and query
`collector_heartbeat_total`. Expect one series per enrolled `collector_id`,
labeled with both `collector_id` and `site_id`.

## Notes from getting this working

- **PKI file permissions:** `stub-pki` and `otel-collector` are different
  containers running as different, unrelated UIDs, sharing the `pki_data`
  volume. Private keys there are `0644`, not the usual `0600` — acceptable
  only because this is a throwaway dev CA that exists solely to unblock
  this test, never for a real CA/server key.
- **`resource_to_telemetry_conversion: enabled: true`** is required on the
  `prometheus_remote_write` exporter, or every OTLP resource attribute
  (including `collector_id`/`site_id`) is dropped — only `job`/`instance`
  (from `service.name`/`service.instance.id`) reach VictoriaMetrics by
  default.
- **Resource attribute names must be Prometheus-label-safe** (no dots).
  `collector/transport/otlp.py` originally used OTel's usual dotted
  resource-attribute style (`collector.id`, `site.id`); the remote-write
  exporter silently dropped them instead of sanitizing. Renamed to
  `collector_id`/`site_id`, matching this project's own metric-label
  convention (`COLLECTOR-V2-REFACTOR.md` §10) — fixed at the source rather
  than worked around here.
