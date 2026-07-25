# SENTINEL v2 — Extended Features & Future Architecture
## Beyond the 50-Collector Single-Site Baseline

> **Date:** 2026-07-25  
> **Status:** Design / Proposal. These features extend `ARCHITECTURE-V2.md` (the committed baseline design for up to 50 collectors on a single server). Nothing in this document is implemented.  
> **Scope:** Multi-site federation, backend clustering, cross-site anomaly correlation, federated ML, alerting improvements, evidence collection, operational hardening, and OT-specific extensions.

---

## 1. Why Extend Beyond the Baseline?

The baseline v2 architecture (`ARCHITECTURE-V2.md`) solves the **50-collector single-site** problem cleanly. The following real-world scenarios push beyond it:

| Scenario | Baseline gap |
|---|---|
| Customer runs 3 geographically separate OT plants, each with 20 collectors | No cross-site visibility; three independent SENTINEL instances, no correlation |
| Backend VM goes down during an incident | No HA; monitoring blind during the most critical time |
| Slow attack crosses two sites simultaneously | Each site’s ML model sees only local data; cross-site pattern invisible |
| 200+ collectors across an MSP portfolio | Single VictoriaMetrics node + single PostgreSQL server becomes a bottleneck |
| OT site has air-gap: no internet, no cloud | Needs fully autonomous local analysis + optional periodic synchronisation |
| Security team wants global alert dashboard across all sites | No global query plane; must log in to each site independently |

This document designs the architecture extensions that address each scenario. Each extension is **independently deployable** — a customer starts with the baseline v2 and adds tiers as their scale grows.

---

## 2. Multi-Site Architecture (Federation Tier)

### 2.1 Three-Tier Topology

```
┌──────────────────────────────────────────────────────────────────────┐
│                    GLOBAL TIER (optional)                               │
│  global-api (Go/Gin)    global-vm (vmselect cluster)                     │
│  global-frontend (SvelteKit)   global-pg (read replica)                  │
│  Cross-site anomaly correlator (Python)                                  │
└───────────┬────────────────┬────────────────┬───────────┘
                 │                │                │
           ↓ mTLS         ↓ mTLS         ↓ mTLS
      federation agent  federation agent  federation agent
                 │                │                │
┌───────────────┴─┐  ┌───────────────┴─┐  ┌───────────────┴─┐
│   SITE TIER: Plant A  │  │   SITE TIER: Plant B  │  │   SITE TIER: MSP   │
│   (baseline v2)      │  │   (baseline v2)      │  │   customer X      │
│   • ingest (Go)       │  │   • ingest (Go)       │  │   (baseline v2)  │
│   • analyse (Python) │  │   • analyse (Python) │  │                   │
│   • api (Go)          │  │   • api (Go)          │  │                   │
│   • VictoriaMetrics   │  │   • VictoriaMetrics   │  │                   │
│   • PostgreSQL        │  │   • PostgreSQL        │  │                   │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
       ↑ collectors            ↑ collectors            ↑ collectors
```

**Design principle:** Each site is a fully autonomous, fully functional SENTINEL v2 instance. The global tier is **optional** and **additive** — a site works completely without it. The global tier adds correlation and a unified dashboard; it does not add a dependency that breaks local operation if it goes offline.

Academic basis: This mirrors the **hierarchical federation** pattern from the B5G Federated Network Intelligence Orchestration paper (Sciopen 2024) [web:83], which proved that a hierarchy of local → global intelligence orchestrators enables real-time anomaly detection without centralising raw data, and maintains local autonomy when the global tier is unreachable.

### 2.2 Federation Agent

A lightweight **Go binary** running on each site server alongside the baseline v2 services. Responsibilities:

1. **Metric forwarding (selective):** Forward a configurable subset of VictoriaMetrics data to the global vminsert via Prometheus remote-write over mTLS. Default: only aggregated anomaly scores and RCA verdicts, not raw per-collector metrics. This minimises WAN bandwidth.

2. **Event forwarding:** Forward PostgreSQL `anomalies` and `rca_results` rows to a global PostgreSQL write replica via an append-only REST endpoint (`POST /global/events/ingest`). Each row includes `site_id` as a label.

3. **Model weight export (federated ML, Section 5):** Periodically export LSTM-AE gradient updates (not raw training data) to the global ML aggregator.

4. **Heartbeat:** `POST /global/sites/{id}/heartbeat` every 60s — global tier can detect site connectivity loss.

**WAN bandwidth estimate** for selective forwarding:
- 50 collectors × 8 metric groups × 1 anomaly score/min + RCA events: ~400 samples/min = ~6 samples/s
- At 64 bytes/sample: ~400 bytes/s per site — negligible even over a narrow WAN link

The site-local API and dashboard remain fully operational if the WAN link is down. The federation agent has a local queue (PostgreSQL-backed) that replayss missed events when connectivity is restored.

### 2.3 Global Tier Components

#### Global VictoriaMetrics (vmselect cluster)

The global tier uses **VictoriaMetrics multi-regional setup** [web:74]: each site runs a `vmagent` that dual-writes anomaly score metrics to both the local VM instance and the global `vminsert`. The global `vmselect` provides a single MetricsQL query endpoint across all sites.

```yaml
# vmagent on each site server (addition to baseline docker-compose)
vmagent:
  image: victoriametrics/vmagent:latest
  command:
    - -remoteWrite.url=http://local-victoriametrics:8428/api/v1/write    # local (always)
    - -remoteWrite.url=https://global-vminsert:8480/insert/0/prometheus  # global (best-effort)
    - -remoteWrite.label=site_id=plant-a   # inject site label on all metrics
```

Metrics forwarded to global VM are **site-labelled**: every metric gets `site_id="plant-a"` injected by vmagent. This allows cross-site MetricsQL queries like:
```
analyselaptop_ml_anomaly_score{site_id=~"plant-.*", metric_group="network_latency"}
```

#### Global PostgreSQL (read replica)

A logical replication replica of the anomaly/RCA/alert rows from all site PostgreSQL instances, with an added `site_id` column. The global API queries this replica (read-only); writes go to site-local PostgreSQL first and replicate to global. This avoids write amplification.

**Schema addition:**
```sql
-- Applied to replicated tables at global tier
ALTER TABLE anomalies     ADD COLUMN site_id TEXT NOT NULL DEFAULT 'local';
ALTER TABLE rca_results   ADD COLUMN site_id TEXT NOT NULL DEFAULT 'local';
ALTER TABLE alerts        ADD COLUMN site_id TEXT NOT NULL DEFAULT 'local';
ALTER TABLE ml_model_state ADD COLUMN site_id TEXT NOT NULL DEFAULT 'local';
```

#### Global API (Go/Gin)

Identical structure to the site-level `backend/api/` but queries the global VM and global PG replica. Adds:

```
GET  /api/v1/sites                           — all registered sites + heartbeat status
GET  /api/v1/sites/:id/anomalies             — anomalies for one site (proxied from global PG)
GET  /api/v1/global/anomalies                — all sites, time-ordered (with site_id label)
GET  /api/v1/global/correlations             — cross-site correlated anomaly groups
GET  /api/v1/global/topology                 — inter-site topology (WAN links, shared targets)
WS   /api/v1/ws/global/live                  — real-time global anomaly feed
```

#### Global SvelteKit Frontend

A second SvelteKit build (`frontend-global/`) with additional views:

- **Site fleet table:** all sites with heartbeat status, last anomaly, ML model state summary
- **Global anomaly timeline:** swim-lane per site, cross-site correlation groups highlighted
- **Global topology map:** shows inter-site WAN links (RTT, loss) + intra-site topology collapsed to a single node per site
- **Cross-site correlation panel:** correlated anomaly groups with timeline and shared-cause hypothesis

---

## 3. Backend High Availability

### 3.1 The Single-Server Problem

The baseline v2 runs all backend services on one server. A server failure during an incident (precisely when monitoring is most critical) creates a blind spot. HA is not required for every deployment, but should be achievable without architectural changes.

### 3.2 VictoriaMetrics HA

VictoriaMetrics supports native HA via **dual-write from vmagent** [web:74][web:81]:

```yaml
# Collectors dual-write to two independent VM instances
# vmagent on site server
- -remoteWrite.url=http://vm-primary:8428/api/v1/write
- -remoteWrite.url=http://vm-secondary:8428/api/v1/write
```

Both instances receive all data. `vmselect` (or a simple load balancer) serves read queries from whichever instance is healthy. **No replication protocol between VM instances** — they are independent; the write duplication is done at the source. Deduplication is enabled at query time (`dedup.minScrapeInterval=30s`).

This is the VictoriaMetrics-recommended HA pattern for single-AZ deployments [web:81]. It requires no distributed consensus protocol and works on two commodity VMs.

### 3.3 PostgreSQL HA (Patroni)

For HA PostgreSQL, deploy **Patroni** (etcd-backed, automatic primary election on failure):

```
patroni-primary   ── streaming replication ──►  patroni-replica
        └──────── etcd (3-node) ───────┘
```

Application services (`backend/analyse/`, `backend/api/`, `backend/ingest/`) connect via a **PgBouncer** connection pooler that points to the current primary. On failover, Patroni updates the primary address and PgBouncer reconnects within ~30s — no application code change needed.

For deployments where 3 VMs for etcd is too much, **Patroni DCS over Consul** (2 nodes + 1 witness) is an alternative, or simply accept the baseline single-PostgreSQL with regular pg_basebackup snapshots to object storage (good enough for most single-site deployments).

### 3.4 Backend Service HA

All three backend services (`ingest`, `analyse`, `api`) are **stateless with respect to in-flight data**:
- `ingest`: stateless — if it crashes, collectors retry with exponential backoff (Phase 9 retry queue). Two instances behind HAProxy L4 load balancer.
- `api`: stateless — two instances behind Nginx upstream. WebSocket sessions reconnect; frontend uses exponential backoff reconnect.
- `analyse`: the analysis loop runs on a 60s cadence. A crash loses at most one analysis cycle. Two instances with PostgreSQL advisory lock (`SELECT pg_try_advisory_lock(42)`) so only one runs at a time, but the second is hot-standby.

### 3.5 HA Deployment (Docker Compose extension)

```yaml
# docker-compose.ha.yml (extends docker-compose.yml)
services:
  victoriametrics-primary:
    image: victoriametrics/victoria-metrics:latest
    volumes: [vm-primary:/victoria-metrics-data]

  victoriametrics-secondary:
    image: victoriametrics/victoria-metrics:latest
    volumes: [vm-secondary:/victoria-metrics-data]

  postgres-primary:
    image: patroni/patroni:latest
    environment: [PATRONI_NAME=primary, ...]

  postgres-replica:
    image: patroni/patroni:latest
    environment: [PATRONI_NAME=replica, ...]

  pgbouncer:
    image: pgbouncer/pgbouncer:latest
    # Points to Patroni primary, auto-updates on failover

  ingest-1:
    build: ./backend/ingest
  ingest-2:
    build: ./backend/ingest

  haproxy:
    image: haproxy:latest
    # TCP L4 LB for OTLP/gRPC to ingest-1/2

  api-1:
    build: ./backend/api
  api-2:
    build: ./backend/api

  analyse:
    build: ./backend/analyse
    # Advisory lock: only one runs; second is hot standby
  analyse-standby:
    build: ./backend/analyse
```

---

## 4. Cross-Site Anomaly Correlation

### 4.1 The Problem

A slow BGP route leak or a shared ISP degradation may cause RTT elevation at Plant A, Plant B, and the MSP office simultaneously — each as a minor anomaly that each site's ML model classifies as low-confidence. Viewed together, they form a high-confidence **cross-site correlated event**.

Academic basis: This is the core motivation of the Trinocular project (van Adrichem et al., TMA 2025, referenced in ROADMAP.md Phase 9): cross-probe correlated outage detection is significantly more accurate than single-probe detection for WAN-originated events.

### 4.2 Cross-Site Correlator Service

A new Python service in the global tier: `global/correlator/`.

**Algorithm:** Temporal clustering of anomaly events across sites with shared characteristics:

```python
# global/correlator/correlate.py

def correlate_across_sites(
    events: list[AnomalyEvent],  # from global PG, last 5 min
    time_window_s: int = 300,
    min_sites: int = 2
) -> list[CorrelatedGroup]:
    """
    Group anomaly events that:
    1. Occurred within time_window_s of each other
    2. Affect >= min_sites different sites
    3. Share a metric_group (e.g. all 'network_latency')
    4. Have overlapping target namespaces (e.g. all point toward the same upstream ASN)
    """
    groups = []
    # Sliding window temporal clustering
    # DBSCAN on (site_id, ts, metric_group, target_asn) feature space
    # Epsilon: 300s in time dimension, exact match on metric_group
    # Academic basis: DBSCAN for time-series event clustering
    # (Ester et al. 1996; applied to network events in Tikumporn IEEE Access 2025)
    ...
    return groups
```

**Shared-cause hypotheses for cross-site groups:**

| Pattern | Hypothesis | Confidence modifier |
|---|---|---|
| RTT ↑ at ≥2 sites toward same upstream IP | Shared upstream congestion / ISP fault | +0.3 on base confidence |
| All sites lose connectivity within 60s | WAN provider outage | +0.5 |
| RTT ↑ at sites sharing the same VPN hub | VPN hub overload / mis-route | +0.4 |
| OT register anomaly at 2+ sites same production line | Coordinated attack or shared PLC firmware bug | +0.6 (OT-specific) |
| ML anomaly only (no Tier 1) at 3+ sites | Slow coordinated intrusion — too subtle for static thresholds | +0.5 |

Correlated groups are written to `global.correlated_events` table and surfaced in the global SvelteKit dashboard with a correlation confidence score.

### 4.3 IP-to-ASN Enrichment

For WAN correlation, targets are enriched with ASN (Autonomous System Number) using a local MaxMind GeoLite2-ASN database (updated weekly, no API call required). Two anomalies pointing to RTT elevation toward the same ASN are correlated as potentially shared-upstream even if the IP addresses differ.

---

## 5. Federated ML (Cross-Site Baseline Learning)

### 5.1 The Problem

Each site trains its own LSTM-AE on local data. A new site goes through a 7–28-day learning phase with no ML alerting. A slowly evolving attack across all sites produces individual weak signals that no single site’s model detects confidently.

### 5.2 Federated Learning Architecture

**Academic basis:** The B5G Federated Network Intelligence Orchestration paper (Sciopen 2024) [web:83] applied **FedAvg** (McMahan et al., 2017) to train a shared autoencoder on network telemetry without centralising training data. The system achieved 95.6% anomaly detection accuracy with federated training vs. 97% with centralised — a small accuracy cost for a large privacy and data-minimisation gain.

For SENTINEL, federated learning serves two purposes:
1. **Cold-start acceleration:** A new site can initialise its LSTM-AE from a federated global model instead of random weights. This reduces the effective learning phase from 7 days to ~2 days before the site-specific model fine-tunes on local data.
2. **Cross-site slow-attack detection:** The global model learns patterns that appear across multiple sites simultaneously, even if each site’s contribution is individually sub-threshold.

**Protocol (FedAvg adapted for LSTM-AE):**

```
Round r (every 7 days by default):
  1. Global aggregator sends current global model weights W_global to all sites
  2. Each site trains for E local epochs (default E=5) on its clean local buffer
  3. Each site sends back gradient update ΔW_site (NOT raw data)
  4. Global aggregator computes:
     W_global_new = W_global + lr × (Σ n_site × ΔW_site) / N_total
     (weighted by n_site = number of clean training samples at each site)
  5. Global aggregator distributes W_global_new to all sites
  6. Each site uses W_global_new as starting point for next local training cycle
```

**Gradient updates only.** Raw training data never leaves the site. This implements GDPR data-minimisation for the ML pipeline: `ΔW` is a gradient tensor with no recoverable sample data (differential privacy guarantees via gradient noise injection if required).

**New site cold-start:** On enrollment, the global aggregator sends `W_global` as the initial weights for the new site’s LSTM-AE. The site fine-tunes for its local learning phase. Expected outcome: anomaly detection confidence above threshold after ~2 days instead of 7.

**Global model storage:**
```
global/ml/
  ├── global_model.pt              # Global federated model weights (PyTorch)
  ├── global_model.onnx            # ONNX export for distribution
  ├── federation_meta.json         # Round number, participating sites, n_total
  └── rounds/                      # Per-round history (last 10 rounds)
```

**Privacy note (OT sites):** OT sites may opt out of gradient sharing via `federated_ml_opt_out: true` in their site config. OT baseline data is particularly sensitive under IEC 62443 change management obligations. Opted-out sites still receive the global model for cold-start but do not contribute gradients.

---

## 6. Backend Clustering (>500 Collectors)

### 6.1 VictoriaMetrics Cluster

At >500 collectors (>>500 samples/s), VictoriaMetrics single-node is replaced by the **cluster edition** (vminsert / vmstorage / vmselect) [web:77]:

```
vmagent (per site) ──► vminsert (load balanced) ──► vmstorage ×3 (sharded)
                                                         │
                                                       vmselect (replicated)
                                                         │
                                                     backend/api/
```

- **vminsert:** stateless, horizontally scalable. HAProxy TCP L4 in front.
- **vmstorage:** sharded by metric name hash. Replication factor = 2 (survive one node failure).
- **vmselect:** stateless query tier, horizontally scalable. Returns merged results from all vmstorage shards.

**No application code change** is needed in `backend/ingest/` or `backend/api/` — the remote-write URL and MetricsQL query URL change from the single-node to the cluster endpoint; the wire protocol is identical.

**Scale reference:** VictoriaMetrics cluster edition is documented to handle >1M samples/s on modest hardware. At 500 collectors × 30 metrics × 2 samples/min = 500 samples/s, single-node handles this comfortably. Cluster is only needed above ~10,000 samples/s (~5,000 collectors).

### 6.2 PostgreSQL Horizontal Read Scaling

At high event rates (many sites × many anomaly events), the PostgreSQL read load from `backend/api/` (serving many dashboard sessions) may exceed a single primary’s capacity. Solutions in order of complexity:

1. **PgBouncer connection pooling** (always deploy — reduces connection overhead significantly)
2. **Read replicas** — route read-only API queries to streaming replicas; writes go to primary
3. **Citus (horizontal sharding)** — shard `anomalies` and `metrics_hot` tables by `collector_id` or `site_id`. Only needed at extreme scale (>50M events/day)

### 6.3 Analysis Service Horizontal Scaling

The `backend/analyse/` service is the most stateful component (ML models in memory). Horizontal scaling strategy:

- **Shard by collector_id:** Use PostgreSQL advisory locks keyed by `hash(collector_id) % N_workers`. Each `analyse` instance owns a subset of collectors.
- **N instances** behind a Kubernetes CronJob or Docker Swarm service.
- **Shared model store:** Mount the `ml/models/` volume on NFS or object storage (MinIO/S3) so all instances can read any model.
- **ML training jobs:** Submit to a **separate training worker pool** (GPU-equipped nodes if available; CPU is fine for the LSTM-AE sizes specified).

---

## 7. OT Site Isolation & Air-Gap Support

### 7.1 Fully Autonomous Air-Gapped Mode

Some OT sites have no internet connectivity and no connection to an IT WAN. The baseline v2 handles this natively (all services run locally). Additional requirements for air-gapped OT:

- **PKI bootstrap without network:** The CA private key and initial collector certs are provisioned on a USB drive (signed offline). The `backend/ingest/` service accepts the air-gap-provisioned cert without calling an enrollment endpoint.
- **Model distribution without internet:** The global federated model is carried on USB/offline transfer to the site. The `backend/analyse/` service accepts a manually-copied `global_model.onnx` as the cold-start model.
- **Evidence export:** Evidence bundles (JSON + SHA-256 hash) are exported to a mounted USB path or a dedicated evidence NAS, not to cloud storage.
- **NTP isolation:** All services use a local Stratum 1 NTP server (GPS-referenced where available) rather than internet NTP. This is critical for cross-collector timestamp alignment: 30s probe intervals require time alignment to < 1s.

### 7.2 Secure Periodic Sync for Air-Gapped Sites

For sites that have a scheduled, supervised network connection (e.g., maintenance window once/week):

```
Air-gap site ─── VPN dialled manually ──►  Global tier
  1. federation agent sends queued events (replays from local PG queue)
  2. federation agent sends gradient update (if OT opt-in)
  3. global tier sends updated global model
  4. global tier sends PKI renewal (if cert < 14 days to expiry)
  5. VPN torn down
```

All sync operations are **idempotent** — partial syncs due to a dropped VPN are safe to replay.

### 7.3 OT-Specific Alerting Rules

Beyond the standard anomaly scoring, OT sites get additional rule-based detections that run inside `backend/analyse/` regardless of ML model state:

| Detection | Trigger | IEC 62443 reference |
|---|---|---|
| Modbus write command observed | FC05, FC06, FC15, FC16 seen on passive eBPF flow (Phase 11) | SR 3.2: Malicious code protection |
| STP topology change burst | `dot1dStpTopChanges` rate > 3/min (Phase 1 SNMP) | SR 7.1: DoS protection |
| New MAC address on OT VLAN | ARP cache entry for unregistered OUI | SR 1.1: Human user identification |
| PLC reboot (sysUpTime regression) | Phase 1 SNMP sysUpTime drops | SR 7.6: Network and security configuration settings |
| WireGuard tunnel drop on OT VPN | Handshake age > 3 min for OT-segment tunnel | SR 3.3: Security functionality verification |

These rules fire with confidence=1.0 (certain) and bypass the confidence gating — they always alert via all channels, regardless of the ML model state (`ACCUMULATING`, `ACTIVE`, etc.).

---

## 8. Alerting Improvements

### 8.1 vmalert Integration

The current baseline writes anomaly events to PostgreSQL and dispatches alerts from `backend/api/`. For >100 sites, a dedicated **vmalert** instance (part of the VictoriaMetrics ecosystem) handles alerting more scalably:

```yaml
vmalert:
  image: victoriametrics/vmalert:latest
  command:
    - -rule=/config/alert-rules.yaml
    - -datasource.url=http://victoriametrics:8428
    - -notifier.url=http://alertmanager:9093
    - -remoteWrite.url=http://victoriametrics:8428/api/v1/write
```

Alert rules in MetricsQL:
```yaml
# config/alert-rules.yaml
groups:
  - name: sentinel.anomaly
    rules:
      - alert: HighConfidenceAnomaly
        expr: analyselaptop_ml_anomaly_score{} > 0.8
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "ML anomaly score {{ $value }} at {{ $labels.collector_id }}/{{ $labels.metric_group }}"

      - alert: TierOneTwoAgreement
        expr: analyselaptop_ml_anomaly_score{verdict="HIGH_CONFIDENCE_ANOMALY"} > 0.9
        for: 30s
        labels:
          severity: page
```

**Alertmanager** handles deduplication, grouping, silencing, and routing to PagerDuty / Slack / email / webhook. This replaces the bespoke alert dispatch in `backend/api/` for large deployments, while the existing Go webhook/SMTP dispatch is retained for single-site deployments that don’t want Alertmanager.

### 8.2 Alert Correlation & Deduplication

At scale, a single WAN outage could trigger hundreds of individual alerts (one per collector × target). Without deduplication, an on-call engineer is paged hundreds of times for one event.

**Alertmanager grouping** collapses alerts by `(site_id, metric_group, rca_cause)` into a single notification per group, with a count of affected collectors. This is the standard Prometheus/Alertmanager pattern but requires the `rca_cause` label to be propagated from `backend/analyse/` into the metric labels written to VictoriaMetrics — a one-line addition to the anomaly score write.

### 8.3 Maintenance Window API

The baseline v2 has a `maintenance_windows` table but no API for it. The extended alerting adds:

```
POST   /api/v1/maintenance                     — declare maintenance window
GET    /api/v1/maintenance                     — list active windows
DELETE /api/v1/maintenance/:id                 — end maintenance window early
GET    /api/v1/maintenance/history             — audit trail of all windows
```

During an active maintenance window: ML training contamination masks the period; alert routing is suppressed; the SvelteKit dashboard shows a visible "MAINTENANCE" banner over affected collectors.

---

## 9. Evidence & Compliance

### 9.1 Tamper-Evident Evidence Bundles

From ROADMAP.md Phase 6 (#47, #48), extended for multi-site:

```json
{
  "bundle_id": "evd-2026-07-25T18:00:00Z-plant-a",
  "site_id": "plant-a",
  "generated_at": "2026-07-25T18:00:00Z",
  "generator_version": "sentinel-v2.3.1",
  "scope": {
    "collectors": ["homelab-pi4", "ot-pi3"],
    "time_start": "2026-07-25T12:00:00Z",
    "time_end": "2026-07-25T18:00:00Z"
  },
  "anomaly_events": [...],
  "rca_results": [...],
  "ml_model_states": [...],
  "baseline_deviations": [...],
  "config_at_time_of_incident": {...},
  "sha256": "a3f8..."
}
```

The `sha256` field is the SHA-256 hash of the UTF-8 serialised JSON body (excluding the `sha256` field itself). This provides a tamper-evident audit record: any modification to the bundle invalidates the hash.

**Multi-site evidence:** The global tier can produce a **cross-site evidence bundle** that aggregates events from multiple sites into one document, including the cross-site correlation record.

### 9.2 Audit Log

All operator actions (retrain, rollback, maintenance window, config change, alert acknowledgement) are written to a PostgreSQL `audit_log` table:

```sql
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor       TEXT NOT NULL,  -- JWT sub claim
    action      TEXT NOT NULL,  -- e.g. 'ml.retrain', 'maintenance.create', 'alert.ack'
    target      TEXT,           -- collector_id, site_id, etc.
    payload_json JSONB,         -- full action payload
    ip_addr     INET
);
```

The audit log is **append-only** — a PostgreSQL row-level security policy denies `UPDATE` and `DELETE` to the application role. It satisfies IEC 62443 SR 2.8 (audit log generation) and GDPR Art. 5(2) accountability requirements.

---

## 10. Operational Hardening

### 10.1 Collector Auto-Update

The baseline v2 requires manual collector binary updates. The extended architecture adds a **signed binary distribution** mechanism:

1. `backend/api/` serves `GET /api/v1/collector/latest` — returns the latest collector binary version + SHA-256 hash
2. Each collector checks this endpoint at startup and every 24h
3. If a newer version is available, the collector downloads it to a staging path, verifies the SHA-256, atomically replaces the running binary, and restarts via systemd
4. The binary is signed with an Ed25519 key held by the backend CA; the collector verifies the signature before staging

This avoids manual SSH sessions to 50+ collector nodes for each update.

### 10.2 Collector Health Scoring

Beyond binary up/down, each collector gets a **health score** (0–1) computed by `backend/analyse/`:

```python
def collector_health_score(collector_id: str, last_30m: CollectorStats) -> float:
    score = 1.0
    score -= 0.3 * last_30m.heartbeat_gap_ratio          # missed heartbeats
    score -= 0.2 * last_30m.check_cycle_overrun_ratio    # cycles > 45s (overloaded)
    score -= 0.2 * last_30m.metric_gap_ratio             # missing metric streams
    score -= 0.2 * last_30m.tls_cert_expiry_penalty      # cert < 14 days
    score -= 0.1 * last_30m.ebpf_degraded                # eBPF not available (graceful degraded mode)
    return max(0.0, score)
```

Health score is written to VictoriaMetrics as `analyselaptop_collector_health_score{collector_id=...}` and displayed in the fleet overview table. A health score < 0.6 generates a `CollectorDegraded` alert.

### 10.3 Capacity Planning Metrics

The `backend/analyse/` service tracks and exposes:

```
analyselaptop_vm_disk_used_bytes
analyselaptop_pg_table_rows{table="anomalies"}
analyselaptop_pg_table_rows{table="ml_model_state"}
analyselaptop_analyse_cycle_duration_seconds{quantile="0.99"}
analyselaptop_ml_training_duration_seconds{collector_id, metric_group}
analyselaptop_ml_model_size_bytes{collector_id, metric_group}
```

These feed a **capacity planning panel** in the SvelteKit dashboard showing projected disk usage growth, estimated time to storage exhaustion, and analysis cycle latency trend.

### 10.4 Role-Based Access Control (RBAC)

The baseline v2 has a single JWT-authenticated API. The extended architecture adds roles:

| Role | Permissions |
|---|---|
| `viewer` | Read-only: anomalies, RCA, metrics, ML state, topology |
| `operator` | viewer + declare maintenance, acknowledge alerts, change alert thresholds |
| `analyst` | operator + trigger manual retrain, rollback models, export evidence |
| `admin` | analyst + manage collectors, revoke PKI certs, manage users, change RBAC assignments |
| `ot-operator` | Restricted: read-only on OT metric groups only; cannot see IT metrics; cannot modify OT ML config without second-factor approval |

Roles are stored in PostgreSQL `users` table, enforced in `backend/api/` Gin middleware. JWT claims include the role; endpoints are annotated with minimum required role.

The `ot-operator` role implements the **least-privilege principle** for OT environments (IEC 62443 SR 1.3: Account management).

---

## 11. Feature Upgrade Map (v2 Baseline → Extended)

| Feature area | v2 Baseline | v2 Extended |
|---|---|---|
| Collector scale | 50 per site | Unlimited (cluster VM + sharded analyse) |
| Site topology | Single site | Multi-site with federation agent + global tier |
| Storage | Single VM + single PG | VM HA (dual-write) / cluster + Patroni PG HA |
| Anomaly detection | Per-site ML (LSTM-AE + ADWIN) | + Cross-site correlation (DBSCAN temporal clustering) |
| ML learning | Independent per-site models | + Federated (FedAvg gradient aggregation); cold-start in 2d vs 7d |
| Alerting | Go webhook/SMTP dispatch | + vmalert + Alertmanager (dedup, group, silence, PagerDuty) |
| Frontend | Single-site SvelteKit | + Global SvelteKit view (fleet table, global timeline, correlation panel) |
| Air-gap support | Partial (all services local) | Full (USB PKI bootstrap, offline model, supervised sync) |
| OT isolation | Tier 1 only (CUSUM/EWMA) | + IEC 62443 rule-based detections (Modbus write, STP burst, new MAC) |
| Evidence | Phase 6 JSON+hash export | + Multi-site cross-site bundle; audit log (append-only) |
| Access control | Single JWT | RBAC (viewer/operator/analyst/admin/ot-operator) |
| Collector management | Manual binary updates | Signed auto-update with Ed25519 verification |
| Health monitoring | Binary up/down | Collector health score (0–1) with degraded alerts |
| Capacity planning | None | Metrics + projected storage exhaustion panel |

---

## 12. Academic References

| Reference | What it grounds |
|---|---|
| McMahan et al. (2017). Communication-Efficient Learning of Deep Networks from Decentralized Data. *AISTATS 2017*. | FedAvg algorithm for federated LSTM-AE training |
| Federated Network Intelligence Orchestration (Sciopen 2024). [web:83] | Hierarchical federation topology; FedAvg for autoencoder anomaly detection; 95.6% federated accuracy; local autonomy when global tier offline |
| VictoriaMetrics Multi-Regional Setup (docs.victoriametrics.com). [web:74] | Dual-write HA pattern; vmagent `-remoteWrite.url` duplication; vmselect deduplication |
| VictoriaMetrics Topologies Guide (docs.victoriametrics.com). [web:81] | Single-AZ HA; cluster edition scale thresholds; no distributed consensus required for dual-write HA |
| van Adrichem et al. (TMA 2025). Trinocular. | Cross-probe correlated outage detection accuracy; streaming-only baselines have 5× higher false-outage rate |
| Tikumporn et al. IEEE Access 2025. | DBSCAN temporal event clustering applied to causal RCA |
| Bifet & Gavaldà (2007). ADWIN. *SIAM ICDM*. | Site-local drift detection (retained from ML baseline doc) |
| IEC 62443-3-3 (2013). SR 1.3, SR 2.8, SR 3.2, SR 7.1. | OT RBAC (SR 1.3), audit log (SR 2.8), Modbus write detection (SR 3.2), STP burst detection (SR 7.1) |
| GDPR Art. 5(2), Art. 6(1)(b). | Accountability obligation (audit log); contractual necessity basis for eBPF flow metadata |
