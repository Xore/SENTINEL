# analyseLaptop — v2 Architecture

> **Date:** 2026-07-25  
> **Status:** Proposed — supersedes monolithic single-host design in `ARCHITECTURE.md`  
> **Trigger:** Scale target raised to 50+ simultaneous collector nodes.  
> This document is the planning artefact. Implementation phases are tracked in `ROADMAP.md`.

---

## 1. Design Drivers

The v1 architecture was designed for a single monitoring laptop probing a bounded OT/IT network. Three constraints are now broken:

| Constraint | v1 assumption | v2 requirement |
|---|---|---|
| Scale | 1 collector, local SQLite | 50+ collectors, shared persistent store |
| Service separation | Monolithic Flask (monitor + dashboard in same process) | Independent collector / backend / frontend services with defined API boundaries |
| Language fit | Python for everything including hot-path ingestion | Go for collector + ingestion; Python retained for anomaly/RCA/ML; TypeScript/SvelteKit for frontend |

---

## 2. High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        analyseLaptop v2 System                             │
│                                                                            │
│  ┌──────────────────────────────────────────┐                             │
│  │           Collector tier (Go)            │  ×50+ nodes                 │
│  │  collector/                              │                             │
│  │  • Active checks (ICMP/DNS/HTTP/TCP/NTP) │                             │
│  │  • eBPF passive RTT layer (Linux nodes)  │                             │
│  │  • Gorilla local hot/cold store          │  mTLS + OTLP/gRPC           │
│  │  • MDP adaptive scheduler                │ ──────────────────────────▶ │
│  └──────────────────────────────────────────┘                             │
│                                                                            │
│  ┌──────────────────────────────────────────┐                             │
│  │         Backend tier                     │                             │
│  │                                          │                             │
│  │  ┌─────────────────────────────────┐    │                             │
│  │  │  Ingestion service (Go)         │    │                             │
│  │  │  backend/ingest/                │    │                             │
│  │  │  • OTLP/gRPC receiver           │    │                             │
│  │  │  • mTLS + PKI enrollment        │    │                             │
│  │  │  • Write to VictoriaMetrics     │    │                             │
│  │  │  • Write events to PostgreSQL   │    │                             │
│  │  └─────────────────────────────────┘    │                             │
│  │                                          │                             │
│  │  ┌─────────────────────────────────┐    │                             │
│  │  │  Analysis service (Python)      │    │                             │
│  │  │  backend/analyse/               │    │                             │
│  │  │  • CUSUM + EWMA anomaly detect  │    │                             │
│  │  │  • PCA multi-metric detection   │    │                             │
│  │  │  • Causal DAG RCA engine        │    │                             │
│  │  │  • MDP check-plan generation    │    │                             │
│  │  │  • Reads VictoriaMetrics        │    │                             │
│  │  │  • Writes events / RCA to PG   │    │                             │
│  │  └─────────────────────────────────┘    │                             │
│  │                                          │                             │
│  │  ┌─────────────────────────────────┐    │                             │
│  │  │  API service (Go)               │    │                             │
│  │  │  backend/api/                   │    │◀──── REST/JSON + WebSocket  │
│  │  │  • REST + WebSocket API         │    │      (internal only)        │
│  │  │  • JWT auth (short-lived)       │    │                             │
│  │  │  • Reads VM + PG               │    │                             │
│  │  │  • PKI endpoint                │    │                             │
│  │  └─────────────────────────────────┘    │                             │
│  └──────────────────────────────────────────┘                             │
│                                                                            │
│  ┌──────────────────────────────────────────┐                             │
│  │         Storage tier                     │                             │
│  │  • VictoriaMetrics (single-node)         │                             │
│  │    — time-series: metrics, RTT, loss     │                             │
│  │  • PostgreSQL (single-node)              │                             │
│  │    — events, anomalies, RCA results      │                             │
│  │    — PKI issued certs                    │                             │
│  │    — config: collector registry,         │                             │
│  │      check plans, baselines              │                             │
│  └──────────────────────────────────────────┘                             │
│                                                                            │
│  ┌──────────────────────────────────────────┐                             │
│  │         Frontend tier (SvelteKit/TS)     │                             │
│  │  frontend/                               │                             │
│  │  • Static SPA served by Nginx            │                             │
│  │  • REST polling + WebSocket live feed    │                             │
│  │  • Topology map (D3/SVG)                 │                             │
│  │  • Anomaly + RCA timeline                │                             │
│  │  • Collector fleet status table          │                             │
│  └──────────────────────────────────────────┘                             │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Service Decomposition

### 3.1 Collector (Go) — unchanged language, extended scope

**Directory:** `collector/`  
**Language:** Go (unchanged)  
**Why Go for the collector:**
- Already implemented; cross-compiles to `linux/arm64`, `linux/amd64`, `windows/amd64` with a single `go build`.
- Zero-dependency static binary; no runtime install on probe nodes.
- Native `cilium/ebpf` + `bpf2go` for eBPF kprobes and TC hooks (Phase 2, 11).
- `go-wgctrl` for WireGuard introspection.
- Gorilla delta-of-delta compression (`go-tsz`, Phase 10) fits naturally in Go.
- Performance: Go handles 1,000 concurrent probe goroutines trivially on a Raspberry Pi 4.

**v2 additions vs v1:**

| Addition | Phase |
|---|---|
| OTLP/gRPC exporter replacing plain HTTP push | 9 |
| mTLS with backend-issued leaf cert (Curve25519) | 9 |
| Gorilla hot/cold local store (`collector/compress/`) | 10 |
| eBPF passive RTT layer (kprobe `tcp_close` + TC hook) | 2 |
| MDP state machine + check-plan consumer | 5 |
| eBPF TC flow telemetry — metadata only, no payload | 11 |

**Scaling:** 50+ collectors connect independently to the backend ingest service over mTLS/gRPC. Each collector holds its own PKI leaf cert; the backend CA is the single trust anchor. Collectors are stateless with respect to the backend — they reconnect automatically with exponential backoff (1s base, 60s max, ±20% jitter per Phase 9 spec).

---

### 3.2 Backend: Ingestion Service (Go)

**Directory:** `backend/ingest/`  
**Language:** Go  
**Why Go for ingestion:**
- OTLP/gRPC receiver is a first-class Go ecosystem (`go.opentelemetry.io/collector`). Embedding a Collector-core receiver requires Go.
- Single goroutine per collector connection; 50 collectors = 50 goroutines + a write-batch pool. Negligible memory.
- VictoriaMetrics Go client (`github.com/valyala/fasthttp` + Prometheus remote-write) achieves >1M samples/s on modest hardware [web:89].
- Avoids a Python async event loop in the critical ingestion path.

**Responsibilities:**
- Accept OTLP/gRPC from collectors (mTLS, rejects connections without valid CA-signed cert).
- Validate and normalise metric tuples: `(collector_id, target, metric, ts_ms, value, tags)`.
- Batch-write to VictoriaMetrics (Prometheus remote-write protocol, gzip, 1 s flush).
- Write outage / event rows to PostgreSQL `events` table (threshold-triggered, not every sample).
- Expose `POST /api/pki/enroll` and `DELETE /api/pki/revoke/:id` for collector enrollment.
- Expose `GET /healthz` for service health.

**Why not the OpenTelemetry Collector binary?** The OTel Collector binary is a heavyweight general-purpose pipeline. At 50 collectors × 15 metrics × 30 s interval = ~27 samples/s, it is massive overkill and adds an external operational dependency. The custom Go ingest service is ~300 lines, zero external config surface.

---

### 3.3 Backend: Analysis Service (Python)

**Directory:** `backend/analyse/`  
**Language:** Python 3.12+  
**Why Python for analysis:**
- All anomaly-detection, RCA, and future DQN code is already in Python with `numpy`, `scikit-learn`, `networkx`. Rewriting in Go would cost months with no benefit: these are not hot-path operations.
- Python's scientific ecosystem (CUSUM, EWMA, IncrementalPCA, `networkx` DiGraph) has no equivalent in Go.
- The analysis service runs on a ~10–60 s batch cycle, not in the ingestion hot-path. Throughput requirements are trivial.
- FastAPI (async Python) provides a clean internal RPC interface to the API service with automatic OpenAPI docs.

**Responsibilities:**
- Reads from VictoriaMetrics (MetricsQL/PromQL HTTP query API) on a configurable interval (default 60 s).
- Runs CUSUM + EWMA per metric per collector per target (Phase 3).
- Runs PCA Hotelling T² on the 8-metric fleet-wide vector (Phase 3).
- Runs causal DAG RCA on anomaly events (Phase 4).
- Generates updated check plans per collector and writes to PostgreSQL `check_plans` table (Phase 5).
- Exposes `GET /internal/anomalies`, `GET /internal/rca`, `GET /internal/check_plan/{collector_id}` — internal only, no JWT (network-isolated, backend subnet only).

**Inter-service communication — Analysis → API:** The API service reads anomaly/RCA rows from PostgreSQL directly; the analysis service writes there. No synchronous RPC call from API → analysis in the hot user path. This decouples response latency from analysis batch cadence.

---

### 3.4 Backend: API Service (Go)

**Directory:** `backend/api/`  
**Language:** Go  
**Why Go for the API service:**
- Handles WebSocket connections from the SvelteKit frontend; Go's goroutine-per-connection model scales effortlessly to dozens of simultaneous dashboard sessions.
- JWT validation is a hot path; Go's `golang-jwt/jwt` is consistently faster than Python equivalents in benchmarks.
- Reads VictoriaMetrics directly for real-time metric data (MetricsQL HTTP API — JSON, no ORM needed).
- Reads PostgreSQL for events, anomalies, RCA results, collector registry, config.
- Framework: **Gin** (mature, fast, good middleware ecosystem — CORS, rate limit, auth).

**Public API surface (consumed by frontend):**

```
GET  /api/v1/collectors              — fleet status list
GET  /api/v1/collectors/:id/metrics  — time-series data for one collector
GET  /api/v1/anomalies               — recent anomaly events (paginated)
GET  /api/v1/rca                     — RCA results (paginated)
GET  /api/v1/topology                — network graph (nodes + edges)
GET  /api/v1/alerts                  — alert feed
POST /api/v1/config/targets          — update target list for a collector
POST /api/v1/alerts/webhook          — configure webhook destination
WS   /api/v1/ws/live                 — real-time push feed (anomaly events, collector state changes)

POST /api/pki/enroll                 — collector cert enrollment (proxied from ingest)
DEL  /api/pki/revoke/:id             — revoke collector cert
```

---

### 3.5 Frontend (SvelteKit + TypeScript)

**Directory:** `frontend/`  
**Language:** TypeScript / SvelteKit  
**Why SvelteKit:**
- **No virtual DOM overhead.** Svelte compiles to vanilla JS; real-time topology/timeline views updating at 1–5 s intervals stay smooth without React reconciliation cost. [web:95][web:97]
- **WebSocket native.** `svelte-realtime` (2026) provides reactive subscriptions over WebSocket with zero boilerplate — ideal for the live anomaly feed and collector state table. [web:95]
- **Static SPA build.** `adapter-static` produces files served by Nginx; no Node.js runtime required in production. The API service is the only runtime backend the Nginx proxy touches.
- **TypeScript-first.** Full type safety end-to-end with the API contract.
- FastAPI + Svelte is a documented, production-tested pairing in 2025 for real-time dashboards [web:98]; the pattern transfers directly to Go + Gin + Svelte since the frontend only sees REST/WebSocket, not the backend language.

**View inventory:**

| View | Data source |
|---|---|
| Fleet overview — collector health table | `GET /api/v1/collectors` + WS live |
| Topology map — NetworkX → SVG/D3, RTT + loss on edges | `GET /api/v1/topology` |
| Anomaly timeline — swim-lane, one lane per collector | `GET /api/v1/anomalies` + WS live |
| RCA panel — cause + confidence, drilldown tree | `GET /api/v1/rca` |
| Metrics explorer — per-collector per-target charts | `GET /api/v1/collectors/:id/metrics` |
| Alerts config — webhook/email, confidence gate | `GET/POST /api/v1/alerts` |
| PKI management — enrolled collectors, cert expiry | `GET /api/v1/collectors` (cert fields) |
| Evidence export — JSON/CSV/HTML + SHA-256 hash | `GET /api/v1/export` (Phase 6 issue #48) |

---

## 4. Storage Tier

### 4.1 VictoriaMetrics (single-node)

**Why VictoriaMetrics over alternatives:**

| Option | Verdict | Reason |
|---|---|---|
| **VictoriaMetrics single-node** | ✅ **Selected** | Single binary, no external deps, 20–30% lower memory than InfluxDB/TimescaleDB at equivalent write rate; supports Prometheus remote-write (OTLP-compatible via ingest bridge); MetricsQL is a PromQL superset; handles high-cardinality tags well [web:89][web:93] |
| TimescaleDB | ❌ | PostgreSQL extension: adds tuning surface; better for SQL-join queries on events, which is why PG is kept for events/config, not metrics |
| InfluxDB v3 | ❌ | License change (BSL 1.1 in v3); InfluxQL deprecated; migration cost |
| ClickHouse | ❌ | Excellent for analytics, but operationally heavy for a 50-node probe fleet; not Prometheus-native |
| SQLite (v1) | ❌ | Does not support concurrent writes from 50 collectors; no query federation across collectors |

**Sizing for 50 collectors:**
- 50 collectors × 30 metrics × 2 samples/min = 3,000 samples/min = **50 samples/s**
- VictoriaMetrics single-node handles >200,000 samples/s on a 4-core server [web:89]. 50 samples/s is trivially within capacity.
- Retention: 90 days at 50 samples/s × 8 bytes/sample = **~3 GB** — fits on any small VM or NUC.

**Gorilla bridge:** The collector's Gorilla-compressed OTLP payload is decoded by the ingest service before writing to VictoriaMetrics. VM has its own internal compression (Zstd); there is no double-compression penalty because the ingest service decompresses Gorilla blocks to raw `(ts, value)` tuples before the VM write.

### 4.2 PostgreSQL

**Why PostgreSQL for structured data:**
- Events, anomaly records, RCA results, collector registry, check plans, and PKI issued-cert metadata are **relational** — they have foreign keys, join queries, and transactional updates. A TSDB is wrong for this.
- The v1 SQLite store is replaced by PostgreSQL for the multi-writer, multi-reader requirement.
- SQLite is retained **on each collector** for the local hot/cold buffer (Phase 10). Collectors write locally; the ingest service consumes via OTLP push, not SQLite replication.

**Schema outline:**

```sql
collectors      (id, name, site, enroll_ts, cert_expiry, last_seen, state)
check_plans     (collector_id, version, payload_json, updated_at)
events          (id, collector_id, target, ts, event_type, severity, payload_json)
anomalies       (id, event_id, metric, detector, cusum_stat, ewma_stat, pca_t2, triggered_at)
rca_results     (id, anomaly_id, cause, confidence, symptom_vector_json, ts)
alerts          (id, rca_id, channel, sent_at, ack_at)
pki_certs       (collector_id, cert_pem, issued_at, expires_at, revoked_at)
baselines       (collector_id, target, metric, slot_key, mean, sigma, n, updated_at)
```

---

## 5. Inter-Service Communication

```
┌────────────┐   mTLS/gRPC OTLP   ┌─────────────────┐
│ Collector  │ ─────────────────▶ │ Ingest (Go)     │ ── Prometheus remote-write ──▶ VictoriaMetrics
│  (Go)      │                    │                 │ ── SQL (pgx) ───────────────▶ PostgreSQL
└────────────┘                    └─────────────────┘
                                          ▼
                                  (event threshold)
                                          ▼
                                  ┌─────────────────┐
                                  │ Analyse (Python)│ ◀── MetricsQL HTTP ── VictoriaMetrics
                                  │                 │ ──▶ SQL (psycopg3) ─▶ PostgreSQL
                                  └─────────────────┘
                                          ▼
                                  (writes anomaly/RCA/check_plan rows)
                                          ▼
                                  ┌─────────────────┐
                                  │ API (Go/Gin)    │ ◀── MetricsQL HTTP ── VictoriaMetrics
                                  │                 │ ◀── SQL (pgx) ─────── PostgreSQL
                                  │                 │ ──▶ WebSocket ──────▶ Frontend
                                  │                 │ ◀── REST/JSON ──────  Frontend
                                  └─────────────────┘
```

**Rules:**
1. **Collector → Ingest only.** Collectors never call the API service directly.
2. **Analysis reads storage, writes storage.** Analysis never calls API or Ingest synchronously.
3. **API reads storage only.** API service never calls Analysis synchronously. User latency is decoupled from batch analysis cycle.
4. **Frontend talks to API only.** Frontend has no direct DB access.
5. **No service mesh, no message broker.** At 50 nodes the event rate does not justify Kafka/NATS. PostgreSQL `LISTEN/NOTIFY` is used for the API service to detect new anomaly/RCA rows and push via WebSocket.

**PostgreSQL LISTEN/NOTIFY for live push:**
The analysis service calls `NOTIFY anomaly_channel, payload_json` after each write. The API service has a dedicated goroutine listening on `LISTEN anomaly_channel`; on receipt it fans out to all open WebSocket connections. This avoids polling and keeps the live feed latency to <1 s without a message broker.

---

## 6. Deployment

### 6.1 Docker Compose (default, single-server)

All backend services + storage run on one server (e.g., a NUC or small VM). This is appropriate for 50 collectors targeting a single monitoring hub.

```yaml
# docker-compose.yml (outline)
services:
  victoriametrics:
    image: victoriametrics/victoria-metrics:latest
    volumes: [vm-data:/victoria-metrics-data]
    ports: ["127.0.0.1:8428:8428"]

  postgres:
    image: postgres:16
    environment: [POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD]
    volumes: [pg-data:/var/lib/postgresql/data]
    ports: ["127.0.0.1:5432:5432"]

  ingest:
    build: ./backend/ingest
    network_mode: host          # gRPC from collectors needs real IP
    depends_on: [victoriametrics, postgres]
    ports: ["0.0.0.0:4317:4317"]  # OTLP/gRPC — collector-facing, mTLS gated
    volumes: [./config/pki:/config/pki:ro]

  analyse:
    build: ./backend/analyse
    depends_on: [victoriametrics, postgres]
    # No external port — internal network only

  api:
    build: ./backend/api
    depends_on: [postgres, victoriametrics]
    ports: ["127.0.0.1:8080:8080"]

  nginx:
    image: nginx:alpine
    volumes:
      - ./frontend/dist:/usr/share/nginx/html:ro
      - ./config/nginx.conf:/etc/nginx/nginx.conf:ro
    ports: ["0.0.0.0:443:443"]
    depends_on: [api]
```

**Network exposure:**
- Port `4317` (OTLP/gRPC): collector-facing. Firewall to collector source IPs. mTLS is the auth layer.
- Port `443` (HTTPS/Nginx): management network / VPN only. Same trust boundary as v1.
- All other ports: `127.0.0.1` only or Docker internal network.

### 6.2 Scaling Beyond 50 Collectors

At >50 collectors (or multi-region) the single Docker Compose server remains viable up to ~500 collectors (50 samples/s → 500 samples/s is still well within VictoriaMetrics single-node limits [web:89]). Beyond that:

- **Ingest:** horizontally scale behind a TCP load balancer (HAProxy L4, sticky by collector_id to avoid cert re-handshake churn).
- **VictoriaMetrics:** promote to VictoriaMetrics cluster edition (vminsert/vmstorage/vmselect) — no application code change needed, same remote-write API.
- **PostgreSQL:** promote to Patroni HA cluster or managed RDS — no application code change needed, same pgx driver.
- **Analyse:** multiple instances are safe; each reads from VM and writes to PG with per-row `ON CONFLICT DO NOTHING` idempotency. Run behind a Kubernetes CronJob or systemd timer.
- **API:** stateless behind Nginx upstream block.

---

## 7. Language Summary and Rationale

| Service | Language | Key reason |
|---|---|---|
| `collector/` | **Go** | Already implemented; static cross-platform binary; cilium/ebpf native; 1000 probe goroutines on ARM | 
| `backend/ingest/` | **Go** | OTLP/gRPC receiver ecosystem; high-throughput write path; mTLS without Python async complexity |
| `backend/analyse/` | **Python 3.12** | numpy/scikit-learn/networkx; existing CUSUM/EWMA/PCA/RCA code; not a hot path |
| `backend/api/` | **Go (Gin)** | WebSocket fan-out; JWT hot path; direct VM MetricsQL HTTP queries; stateless |
| `frontend/` | **TypeScript / SvelteKit** | Compile-to-JS, no virtual DOM; WebSocket reactive stores; static SPA build served by Nginx |
| Storage: metrics | **VictoriaMetrics** | Single binary; 20–30× headroom vs current scale; Prometheus-native; no license issues |
| Storage: relational | **PostgreSQL 16** | LISTEN/NOTIFY for live push; pgx Go driver; psycopg3 Python driver; ACID events/config |

---

## 8. Migration Path from v1

v1 and v2 can coexist during migration because the v1 Go collector already speaks the push-to-API protocol.

| Step | Action | Risk |
|---|---|---|
| M1 | Deploy VictoriaMetrics + PostgreSQL alongside existing SQLite | Zero risk — additive |
| M2 | Deploy `backend/ingest` + `backend/api` (no analysis yet) | API serves existing data from PG/VM; dashboard v1 still live |
| M3 | Migrate analysis modules from `monitor/` → `backend/analyse/` (FastAPI wrapper around existing Python code) | Python code is unchanged; only the scheduling wrapper changes |
| M4 | Deploy `frontend/` SvelteKit behind Nginx; run both v1 Flask and v2 frontend in parallel | Compare parity |
| M5 | Cut over — retire Flask dashboard and `monitor/` systemd service | Remove v1 |

---

## 9. OT/IT Safety Constraints — Unchanged

The v2 architecture does not change any OT safety rule:
- **Collector scan levels** (passive L0 → active L1 → authenticated L2) are enforced by the collector check-plan, which is generated by the analysis service and pushed via the `check_plans` PostgreSQL table. The collector never self-escalates scan level.
- **Modbus/OPC UA adapters** are still collector-side, read-only, IEC 62443 compliant (FC01/FC03 only).
- **No management plane exposure to OT segment.** The ingest gRPC endpoint is on the IT/management network. OT collectors reach it through an approved firewall rule — they do not pull configuration from an OT-accessible service.
- **Dashboard access** remains management-network/VPN only; Nginx does not listen on OT VLANs.

---

## 10. Academic Basis for Architecture Decisions

| Decision | Academic grounding |
|---|---|
| mTLS + OTLP/gRPC transport | Tagliaro et al. ACM CCS 2024; After et al. MDPI Sensors 2023; Gupta et al. Sonata HotNets 2016 |
| Collector OTLP two-tier pattern | OpenTelemetry Gateway deployment pattern [web:72][web:73]; agent-per-node + single ingest gateway |
| Gorilla compression on collector | Pelkonen et al. VLDB 2015; 12× compression, 85% queries hit last 26 h |
| VictoriaMetrics for time series | High-cardinality TSDB benchmark [web:93]; IoT TSDB benchmark (Karpathiotakis et al. SciTS 2022) [web:83] |
| PostgreSQL LISTEN/NOTIFY for WS push | Well-documented pattern; avoids message broker at ≤50 node scale; validated in pgx v5 |
| Python retained for analysis | CUSUM+EWMA: Christodoulou et al. DSAA 2015; PCA: Münz TU Munich 2010; RCA DAG: Tikumporn IEEE Access 2025 |
| SvelteKit for frontend | Compile-time reactivity eliminates vDOM reconciliation; svelte-realtime WS (2026) [web:95]; FastAPI+Svelte production pattern [web:98] |
| MDP adaptive scheduling | Zabala et al. Mathematics 2023; Amjad et al. arXiv 2021; DQN upgrade: Rahman et al. MDPI 2025 |
| eBPF passive layer | Sundberg PAM 2023; Bertrone COP2 2019; Hinz SIGCOMM 2023; Zhao Wasm-bpf 2024 |

---

## 11. Open Questions for v2 Design

| # | Question | Blocking phase |
|---|---|---|
| Q1 | PostgreSQL LISTEN/NOTIFY vs a lightweight broker (NATS JetStream) — at what collector count does PG notify become a bottleneck? Threshold estimate: >500 concurrent anomaly events/s. | M3/M4 |
| Q2 | SvelteKit `adapter-static` + Nginx vs SvelteKit `adapter-node` (SSR). SSR needed only if Nginx reverse proxy adds unacceptable cold-start latency; unlikely for internal dashboard. | M4 |
| Q3 | VictoriaMetrics single-node retention limit under 14-day probe data with 50+ collectors — empirical measurement needed after M2 deploy. | M2 |
| Q4 | Analysis service: FastAPI wrapper vs standalone batch worker (no HTTP at all). HTTP only needed if API service ever needs to trigger on-demand analysis; current design avoids this. Lean toward batch worker (simpler). | M3 |
