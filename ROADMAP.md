# Repository Roadmap
## analyseLaptop — Network Health & Anomaly Detection System

> **Updated:** 2026-07-25  
> **Scope:** Entire repository — `collector/`, `monitor/`, `dashboard/`, `config/`, `scripts/`, `tests/`  
> Phases are additive. Each builds directly on the previous. The collector roadmap (`docs/collector/ROADMAP.md`) is the implementation detail for Phase 1–3 of this document.

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        analyseLaptop System                         │
│                                                                     │
│  ┌──────────────┐  mTLS+OTLP   ┌─────────────────────────────┐    │
│  │  collector/  │ ────────────▶│         monitor/            │    │
│  │  (Go agent)  │               │  (aggregator + analyser)    │    │
│  │              │◀───check plan─│                             │    │
│  │  Gorilla     │               │  ┌─────────────────────┐   │    │
│  │  compressed  │               │  │  Anomaly Detection  │   │    │
│  │  local store │               │  │  CUSUM / EWMA / PCA │   │    │
│  └──────────────┘               │  └─────────────────────┘   │    │
│   runs on each                  │  ┌─────────────────────┐   │    │
│   monitored node                │  │   Root Cause Engine │   │    │
│                                 │  │   (causal graph)    │   │    │
│   ┌──────────────┐              │  └─────────────────────┘   │    │
│   │ backend PKI  │              │  hot/cold Gorilla store     │    │
│   │ CA + cert    │              └──────────────┬──────────────┘    │
│   │ issuance     │                             │                   │
│   └──────────────┘                             ▼                   │
│                              ┌────────────────────────────────┐   │
│                              │         dashboard/             │   │
│                              │   (web UI + Grafana + alerts)  │   │
│                              └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Academic Research Basis

| Paper | Key Contribution | Used in Phase |
|---|---|---|
| Sundberg et al. **"Efficient Continuous Latency Monitoring with eBPF"** PAM 2023, LNCS 13882. https://doi.org/10.1007/978-3-031-28486-1_9 | ePPing eBPF design; 1 Mpps / 10 Gbps on a single core; TCP timestamp matching for passive RTT | 2 |
| Rezvani et al. **"Characterizing In-Kernel Observability of Latency-Sensitive Workloads"** ISPASS 2024. https://danielwong.org/files/eBPF-ISPASS2024.pdf | Per-request latency breakdown (kernel stack, scheduler delay, NIC queue) using eBPF kprobes | 2 |
| Red Hat / Sundberg **"netstacklat: eBPF-powered network stack latency"** 2026. https://developers.redhat.com/articles/2026/04/29/ | In-kernel per-packet latency at each network stack layer — identifies *where* latency is introduced | 2 |
| Bertrone et al. **"COP2: Continuously Observing Protocol Performance"** arXiv:1902.04280, 2019. https://arxiv.org/abs/1902.04280 | eBPF kprobes on Linux TCP stack internals; extracts `srtt_us`, retransmit count, cwnd from `tcp_sock`; negligible overhead | 2 |
| Münz, G. **"Traffic Anomaly Detection and Cause Identification Using Flow-Level Measurements"** TU Munich, NET-2010-06-1. https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2010-06-1.pdf | CUSUM + Shewhart control charts; PCA anomaly detection; automated cause identification | 3 |
| Christodoulou et al. **"A Combination of CUSUM-EWMA for Anomaly Detection in Time Series"** DSAA 2015. https://pure.ulster.ac.uk/en/publications/a-combination-of-cusum-ewma | Combined CUSUM-EWMA outperforms either alone; reduces false positives | 3 |
| Tikumporn et al. **"Automated Root Cause Analysis of Network Failures in IP Networks"** IEEE Access 2025. https://doi.org/10.1109/ACCESS.2025.11053841 | Causal DAG RCA; symptom-to-cause mapping; 92% accuracy on real failure corpus | 4 |
| Zabala et al. **"Optimality of a Network Monitoring Agent"** Mathematics 11(3):610, 2023. https://doi.org/10.3390/math11030610 | MDP optimal scheduling; adaptive intervals outperform fixed by 40–60%; finite-state MDP achieves ~80% of theoretical optimum without training data | 5, 12 |
| Amjad et al. **"Optimal Probing with Statistical Guarantees"** arXiv:2109.07743, 2021. https://doi.org/10.48550/arXiv.2109.07743 | A-optimal probe budget; Frank-Wolfe approximation; 50% probe reduction | 5 |
| Hinz et al. **"TCP's Third Eye: eBPF for Telemetry-Powered Congestion Control"** ACM SIGCOMM 2023. https://dl.acm.org/doi/10.1145/3609021.3609295 | eBPF-extracted TCP congestion signals (cwnd, rtt_var, retransmit rate) | 2, 11 |
| Zhao et al. **"Wasm-bpf: Streamlining eBPF Deployment in Cloud Environments"** arXiv:2408.04856, 2024. https://arxiv.org/abs/2408.04856 | eBPF in containerised environments; BTF CO-RE portability; minimal overhead vs native | 2 |
| Pelkonen et al. **"Gorilla: A Fast, Scalable, In-Memory Time Series Database"** VLDB 2015. https://www.vldb.org/pvldb/vol8/p1816-teller.pdf | Delta-of-delta timestamps + XOR float64; 12× compression; 96% of timestamps = 1 bit; 85% of queries hit last 26 h | 10 |
| Tagliaro et al. **"A Longitudinal View of IoT TLS Deployments"** ACM CCS 2024. | 99.84% of real-world IoT backends use insecure transport; mTLS + TLS 1.3 is an explicit design requirement | 9 |
| After et al. **"Lightweight TLS 1.3 Handshake for Constrained IoT Devices"** MDPI Sensors 2023. | Curve25519 + RSA reduces TLS 1.3 handshake latency 4× over P-256 on ARM hardware | 9 |
| Gupta et al. **"Sonata: Query-Driven Streaming Network Telemetry"** HotNets 2016. | Monitoring as a tuple pipeline; (target, metric, ts, value, tags) naturally maps to SQLite window queries | 9, 10 |
| van Adrichem et al. **"Trinocular: Understanding Internet Reliability through Adaptive Probing"** TMA 2025. | Streaming for live alerts; batch reprocessing for accurate baselines; batch-up/streaming-down false outages 5× more common | 9, 10 |

---

## Component & Reference Documentation

The detailed, per-component specifications live under `docs/`. This roadmap is the
top-level plan; the documents below are its implementation detail and research backing.

| Document | What it covers |
|---|---|
| [`docs/collector/ROADMAP.md`](docs/collector/ROADMAP.md) | Collector implementation roadmap — phase-by-phase Go agent spec (check inventory, eBPF, MDP scheduling) |
| [`docs/collector/SUGGESTIONS.md`](docs/collector/SUGGESTIONS.md) | Collector design suggestions — file layout, per-check OIDs/methods, OT safety rules, OS-support matrix |
| [`docs/theory/`](docs/theory/) | Research documents grounding each phase: anomaly detection, eBPF deployment constraints, probe scheduling, OT/segment-health theory |
| [`docs/theory/probes/probe-to-backend-transport-theory.md`](docs/theory/probes/probe-to-backend-transport-theory.md) | Secure probe-to-backend transport: mTLS, OTLP/gRPC, backend-generated PKI, streaming vs batch processing |
| [`docs/theory/probes/gorilla-compression-go-theory.md`](docs/theory/probes/gorilla-compression-go-theory.md) | Delta-of-delta / XOR compression theory; Go library comparison; `collector/compress/` reference implementation; hot/cold SQLite schema |
| [`docs/gap-analysis/`](docs/gap-analysis/) | Collector-vs-standalone parity analysis and the research guide for open gap topics |
| [`docs/guides/`](docs/guides/) | Operator guides: setup, capture & Wi-Fi, operations, research & decisions |
| [`docs/setup/00-setup.md`](docs/setup/00-setup.md) | Menu-driven installer walkthrough |

---

## Phase 1 — Collector: Complete Check Inventory (Weeks 1–5)

**Component:** `collector/`  
**Detail:** See `docs/collector/ROADMAP.md` Phases 0–1 for full implementation specification.

### What this phase delivers
- Multi-packet ICMP with RTT distribution (p50/p95/p99) and loss %
- Interface counters (rx/tx bytes, errors, drops) as rates per cycle
- Default GW + WAN checks (public IP tracking, Cloudflare/Google baseline latency)
- OS health (CPU, memory, swap, disk, load average, temperature)
- SNMP v2c/v3 GET with `sysUpTime` regression detection
- Modbus TCP read-only (FC01, FC03 only — IEC 62443 compliant)
- WireGuard peer handshake age + throughput delta
- TLS certificate expiry countdown

### Key output format for downstream analysis

Every check cycle produces a structured JSON envelope pushed to the `monitor/` aggregator:

```json
{
  "collector_id": "homelab-pi4",
  "ts": "2026-07-25T13:00:00Z",
  "cycle_ms": 312,
  "streams": {
    "icmp_targets": [ {"target": "192.168.1.1", "rtt_p50": 1.2, "rtt_p95": 3.8, "loss_pct": 0.0} ],
    "net_interfaces": [ {"name": "eth0", "rx_bps": 124000, "tx_bps": 48000, "rx_error_rate": 0.0} ],
    "os_health": {"cpu_ratio": 0.12, "mem_avail_bytes": 3221225472},
    "snmp_hosts": [ {"host": "192.168.1.254", "sysUpTime_s": 432000, "uptime_regression": false} ],
    "wireguard_peers": [ {"pubkey": "abc...", "handshake_age_s": 23, "rx_bps": 8200} ]
  }
}
```

### Folded-in tasks from the prior roadmap

- [ ] **#54 — SNMPv3 read + STP observation.** Extend the SNMP GET check to full
  SNMPv3 (authPriv, credentials from the dashboard settings store, never Git).
  Read the Bridge-MIB / RSTP objects (`dot1dStpTopChanges`, port states,
  designated root) so a topology change becomes an observable stream field.
  Emit `stp_topology_changes` and per-port state into the `snmp_hosts` envelope;
  a rising `dot1dStpTopChanges` is a symptom Phase 4 RCA can map to a cause.

---

## Phase 2 — eBPF Passive Latency Layer (Weeks 5–7)

**Component:** `collector/` (Linux nodes only)  
**Academic basis:** Sundberg PAM 2023; Rezvani ISPASS 2024; Bertrone COP2 2019; Red Hat netstacklat 2026

### 2a. eBPF Kprobes for TCP RTT — Go Implementation

The `cilium/ebpf` library provides two complementary approaches for TCP RTT extraction grounded in the COP2 paper (Bertrone 2019).

**Approach A: Kprobe on `tcp_close`** — fires when a TCP connection closes, reads `srtt_us` from the kernel `tcp_sock` struct directly. BPF C program lives in `collector/ebpf/tcprtt.c`; Go loader in `collector/ebpf/tcprtt_loader.go` using `cilium/ebpf` + `bpf2go`.

Key design notes:
- `BPF_CORE_READ` + BTF CO-RE: portable across kernel 5.10 (Pi OS Bookworm) to 6.x (Ubuntu 24.04) without recompilation
- `BPF_MAP_TYPE_RINGBUF` preferred over `perf_event_array` for kernel ≥ 5.8: lower overhead, no per-CPU buffers
- `srtt_us` kernel field stores 8× the actual value — right-shift by 3 to get µs
- Build: `go generate ./collector/ebpf/` compiles BPF C → bytecode; `.o` files embedded via `go:embed`

**Approach B: TC Hook / ePPing** — passive timestamp-based RTT on all TCP connections. Implement after Approach A.

### 2b. netstacklat — Per-Layer Stack Latency

| Measurement point | What it reveals |
|---|---|
| NIC driver → socket buffer | NIC queue depth, interrupt coalescence delay |
| Socket buffer → `tcp_rcv` | Kernel scheduler preemption delay |
| `tcp_rcv` → `recvmsg()` | Application wakeup / epoll delay |

### 2c. High-Latency Client Detection

Per-subnet rolling EMA of `srtt_us` over 5 minutes. Emit `HighLatencyClientEvent` when `ratio = event.SrttUs / subnet_baseline_us > 3.0`. Forward as `high_latency_clients` stream in push envelope.

### 2d. eBPF in Containerized and Kubernetes Environments

**Academic basis:** Zhao et al. Wasm-bpf 2024

Minimum capability set (kernel ≥ 5.8): `CAP_BPF` + `CAP_NET_ADMIN` + `CAP_PERFMON` — never use `privileged: true`.

Docker Compose requirements:
- `network_mode: host` — TC hooks and kprobes attach to the host network namespace
- `pid: host` — kprobes observe host kernel PID namespace
- Mount `/sys/kernel/btf:ro` — required for CO-RE relocation
- Mount `/sys/fs/bpf` and `/proc:ro`

**Graceful degradation:** check `GOOS != linux`, `/sys/kernel/btf/vmlinux` existence, and `rlimit.RemoveMemlock()` at startup. Fall back to active ICMP probing silently if eBPF is unavailable.

---

## Phase 3 — Monitor: Time-Series Anomaly Detection (Weeks 7–11)

**Component:** `monitor/` (Python)  
**Academic basis:** Münz TU Munich 2010; Christodoulou et al. DSAA 2015

### 3a. Metric Time-Series Pipeline

```
Raw JSON stream → timeseries.py (60s bucketing)
  → residuals.py (Holt-Winters: α=0.2, β=0.1, γ=0.3, period=24h)
  → detector.py  (Shewhart k=3 | CUSUM h=5 | EWMA λ=0.2, L=3)
  → alarm only if CUSUM + EWMA both trigger (Christodoulou 2015)
```

### 3b. CUSUM + EWMA Detector

Stateful `ControlChartState` per metric per source. Parameters: `cusum_h=5.0`, `cusum_slack=0.5`, `ewma_lambda=0.2`, `ewma_L=3.0`, `shewhart_k=3.0`. Baseline sigma updated only during stable periods (α=0.05, Welford online variance). CUSUM resets to 0 after alarm (Page 1954).

### 3c. Multi-Metric PCA Anomaly Detection

Hotelling T² on 8-dimensional metric vector using `IncrementalPCA(n_components=3)`. Chi-squared threshold at α=0.001. Baseline updated only on non-anomalous samples. Requires 100 samples before detection begins.

### 3d. Adaptive Per-Slot Control Limits

168-bucket hour-of-week keyed control limits: `(metric, subnet_segment, hour_of_week, production_state)`. Eliminates peak-hour false positives. Falls back to coarser bucket when fine-grained slot has insufficient samples.

### Folded-in tasks from the prior roadmap

- [x] **#50 — TCP retransmission/reset + DNS failure trends.** *(v1 shipped, commit `33c798b`.)* `/proc/net/{snmp,netstat}` TCP counters + DNS series → EWMA sustained-vs-spike classifier → `/api/monitor/{tcp,dns}`. Still to layer on: swap /proc sampler for eBPF `retransmits`/`lost` counters (Phase 2) and feed into shared CUSUM+EWMA detectors as Phase 4 RCA symptoms.
- [ ] **#51 — Baselines by segment / hour / production state.** Generalise the 168-bucket adaptive control limits so residual sigma is keyed by `(metric, subnet_segment, hour_of_week, production_state)`. Fall back to coarser bucket when fine-grained slot has too few samples.

---

## Phase 4 — Monitor: Automated Root Cause Analysis (Weeks 11–14)

**Component:** `monitor/` (Python)  
**Academic basis:** Tikumporn et al. IEEE Access 2025; Münz TU Munich 2010 Chapter 10

### 4a. Causal DAG Architecture

`monitor/rca/` — `networkx` DiGraph with 12 cause nodes and 13 symptom nodes. Naive Bayes belief propagation: `P(cause | symptoms) ∝ P(cause) × ∏ P(symptom | cause)`. Posteriors normalised; fires if best-cause confidence > 0.6.

### 4b. Symptom → Cause Mapping

| Observed Symptoms | Most Probable Cause | Confidence |
|---|---|---|
| RTT p95 ↑ + loss = 0 + BW normal | Bufferbloat / AQM | High |
| RTT p95 ↑ + loss ↑ + all targets | WAN congestion | High |
| RTT p95 ↑ + loss ↑ + one target | Host overload / cable | High |
| loss = 100% + ARP gone | Power loss / cable pull | High |
| sysUpTime regression | Device reboot | High |
| rx_error spike | Physical layer fault | Medium |
| new src_ips + flow count ↑ | New/rogue device | Medium |
| dst_ip concentration + high flows | Port scan | Medium |
| DNS latency ↑ + WAN RTT normal | DNS resolver failure | High |
| WG handshake_age > 3 min | WireGuard tunnel drop | High |
| TLS days_remaining < 7 | Certificate expiry | Certain |
| GW unreachable + loss ↑ | Routing failure | High |

### 4c. Dropped Connection Decision Tree

```
Dropped connection detected
  ├─ ARP entry still present?              No  → POWER_LOSS
  ├─ Default GW reachable?                 No  → ROUTING_FAILURE
  ├─ WAN reachable?                        No  → WAN_CONGESTION / ISP failure
  ├─ Target reachable from other collector? No  → HOST failure
  │                                        Yes → PATH_SPECIFIC (asymmetric routing)
  └─ RTT elevated before drop?    Yes → Congestion-induced timeout
                                   No  → Application crash / FW session timeout
```

---

## Phase 5 — Monitor: MDP Adaptive Scheduling + Probe Budget (Weeks 14–17)

**Component:** `monitor/` → `collector/` (check plan delivery)  
**Academic basis:** Zabala et al. Mathematics 2023; Amjad et al. arXiv 2021

The `monitor/` control plane computes the optimal check plan and pushes it back to each collector:

```
1. Receive probe results → update MDP state per target: STABLE → SUSPECT → DEGRADED → DOWN
2. Compute probe weight ∝ RTT variance (Welford online, Amjad 2021)
3. Generate updated check_plan.json
4. POST check_plan to collector /config endpoint

Probe interval by state:
  STABLE    → 30s (base)
  SUSPECT   → 5s  (accelerated)
  DEGRADED  → 10s (sustained)
  DOWN      → 30s (heartbeat only)
```

---

## Phase 6 — Dashboard: Visualisation & Alerting (Weeks 17–20)

**Component:** `dashboard/`

- **Topology map:** NetworkX graph → SVG/D3; nodes colour-coded by MDP state; edges annotated with RTT p95 + loss %
- **Anomaly timeline:** swim-lane chart per collector; one marker per anomaly event; RCA result in tooltip
- **High-latency client table:** live table from eBPF kprobe events (Phase 2c); sortable by RTT ratio
- **Alert routing:** webhook / email / Alertmanager; confidence-gated: >0.8 auto-alert, 0.6–0.8 flagged probable, <0.6 raw symptoms only

### Folded-in tasks from the prior roadmap

- [x] **#53 — Webhook/email alerting on sustained state changes.** *(v1 shipped.)* Edge-triggered on #50 sustained-vs-spike classifier; webhook+SMTP delivery; Settings panel; `/api/alerts*`; 34 tests.
- [x] **#48 — Session/acceptance report (JSON/CSV/HTML + SHA-256 hashes).** *v1 shipped.* Pure assembler + renderers in `dashboard/report.py` (`build_report` → per-target uptime/loss/RTT p50·p95, per-service reliability, outage events with failed-target context, TCP/DNS trend verdicts, redacted config-in-effect, roll-up acceptance verdict pass/attention/insufficient_data). Three renderers (canonical JSON, multi-section CSV, self-contained HTML) each stamped with a SHA-256 `meta.digest` computed over the report's canonical JSON (digest slot blanked, so it is recomputable/verifiable — `report.verify()`). Endpoint `GET /api/report/session?format=json|csv|html&minutes=|since=&until=` returns the artefact with `X-Report-SHA256` + `Content-Disposition`. One-click export panel in Settings (HTML/JSON/CSV + window selector). 29 tests in `tests/test_report.py` (pure assembly, digest stability/tamper-detection, renderer escaping/self-containment, endpoint formats + 400/no-DB paths). Full suite 220 OK.
- [ ] **#47 (trigger) — Freeze-evidence action.** Dashboard button snapshots current stream buffers + active anomaly/RCA context into timestamped, hashed evidence bundle. JSON telemetry only — no full PCAP.

---

## Phase 7 — Prometheus + Grafana Integration (Weeks 20–21)

**Component:** `monitor/` + `dashboard/`

Prometheus metrics from `monitor/`:

```
anomaly_events_total{collector, metric, detector}    counter
anomaly_active{collector, target, state}             gauge
rca_cause_total{cause}                               counter
rca_confidence_histogram                             histogram
network_rtt_p95_seconds{src_collector, dst_target}  gauge
network_loss_ratio{src_collector, dst_target}        gauge
high_latency_clients_total{subnet}                   gauge
```

Pre-built Grafana dashboard JSON in `dashboard/grafana/`.

---

## Phase 8 — Hardening, Tests, Deployment (Weeks 21–24)

**Component:** `tests/`, `scripts/`, `config/`

```
tests/
├── unit/
│   ├── test_detector_cusum.py
│   ├── test_detector_ewma.py
│   ├── test_pca_detector.py
│   ├── test_rca_engine.py
│   ├── test_rca_graph.py
│   └── collector/mdp_scheduler_test.go
├── integration/
│   ├── test_collector_push.py
│   └── test_rca_multinode.py
└── load/
    └── collector_load_test.go   — 1000 targets, 5s intervals, <50ms cycle time

scripts/
├── install-collector.sh    — systemd unit; grants CAP_BPF/NET_ADMIN/PERFMON if eBPF enabled
├── install-monitor.sh      — Python venv + systemd unit + reverse proxy
├── install-dashboard.sh    — static build or Docker Compose
└── update.sh               — rolling update with health check gate
```

### Folded-in tasks from the prior roadmap

- [ ] **#47 (policy) — Disk reserve / capture policy.** Config schema for reserved evidence partition/quota; retention and rotation of evidence bundles; hard floor that refuses a snapshot when free space would drop below the reserve.

---

## Phase 9 — Secure Probe Transport + Backend PKI (Weeks 24–27)

**Component:** `collector/` (exporter) + `monitor/` (PKI endpoint)  
**Academic basis:** Tagliaro et al. ACM CCS 2024; After et al. MDPI Sensors 2023; Gupta et al. HotNets 2016 (Sonata); Trinocular TMA 2025  
**Theory doc:** [`docs/theory/probes/probe-to-backend-transport-theory.md`](docs/theory/probes/probe-to-backend-transport-theory.md)

### What this phase delivers

- [ ] **Backend CA + cert issuance endpoint.** The `monitor/` backend generates and hosts a self-signed CA. New collectors enroll via `POST /api/pki/enroll` (JSON body: `{collector_id, csr_pem}`). Backend signs a 90-day leaf cert and returns `{cert_pem, ca_pem}`. Cert renewal is automatic: collector re-enrolls when `days_remaining < 14`.
  - CA private key stored in `config/pki/ca.key` (mode 0600, never committed to Git)
  - Issued certs stored in `config/pki/issued/<collector_id>.crt`
  - Revocation: DELETE `/api/pki/revoke/<collector_id>` removes cert from trusted set
  - Curve25519 key exchange + RSA-2048 leaf cert (After et al. 2023: 4× lower handshake latency on ARM vs P-256)

- [ ] **TLS 1.3 + mTLS on all collector→backend connections.** Both sides present certificates. The backend rejects any connection without a valid collector cert signed by its CA. Implemented in `monitor/tls.py` using Python `ssl` module with `PROTOCOL_TLS_SERVER` + `CERT_REQUIRED`.

- [ ] **OTLP/gRPC exporter in `collector/exporter.go`.** Replaces plain JSON push. Each batch is a `ExportMetricsServiceRequest` protobuf with gzip compression. TLS config loaded from cert files issued in enrollment.
  - Retry queue: exponential backoff (base 1s, max 60s, jitter ±20%), in-memory ring buffer of last 500 batches
  - Batch size: configurable, default 60 s window
  - Metric tuple: `(collector_id, target, metric_name, ts_unix_ms, value_float64, tags_map)`

- [ ] **Streaming vs batch processing at backend.** SQLite WAL writes for the streaming (live alert) path. Periodic window-function jobs for accurate baselines (Trinocular TMA 2025: batch reprocessing is required for correct reliability statistics; streaming-only baselines have 5× higher false-outage rate).

- [ ] **`scripts/enroll-collector.sh`.** One-shot enrollment script: generates keypair + CSR, POSTs to backend, writes cert + CA bundle to `config/pki/`. Run once at collector install time.

### Open research questions

- Optimal batch size under lossy Wi-Fi (no directly applicable measurements in literature for this probe rate + packet size)
- EST (RFC 7030) vs custom `/enroll` for air-gapped OT deployments — EST adds HTTPS dependency; custom endpoint is simpler but non-standard
- TLS 1.3 full handshake overhead on ARMv7 (Pi 3B) — Curve25519 vs P-256 ARM-specific benchmark needed

---

## Phase 10 — Gorilla Compression + Hot/Cold Store (Weeks 27–29)

**Component:** `collector/compress/` + `monitor/` (compaction job)  
**Academic basis:** Pelkonen et al. VLDB 2015 (Gorilla)  
**Theory doc:** [`docs/theory/probes/gorilla-compression-go-theory.md`](docs/theory/probes/gorilla-compression-go-theory.md)

### What this phase delivers

- [ ] **`collector/compress/` package.** `Series` type wrapping `github.com/tsenart/go-tsz` (MIT). Each metric stream is compressed into a Gorilla block per flush interval. `ToBlock()` returns a `CompressedBlock{GorillaB64, PointCount, StartTime, Tags}` for inclusion in the OTLP payload or local SQLite write.
  - Expected compression ratio: ~12× over raw `(int64, float64)` pairs (Pelkonen 2015)
  - Local store: at 100 metrics/s, 14-day retention fits in < 100 MB after compression

- [ ] **Hot/cold SQLite schema in `collector/` local store.**
  - `metrics_hot`: raw rows, indexed by `(target, metric, ts)`, covers < 26 h window
  - `metrics_cold`: Gorilla BLOB rows, one per 2 h block per series, covers 2 h–14 d window
  - Compaction job (hourly): move rows older than 26 h from hot to cold; purge cold rows older than 14 days
  - 26 h hot window from Pelkonen 2015 §5: 85% of monitoring queries hit the most recent 26 h

- [ ] **Same hot/cold schema mirrored in `monitor/` backend.** Backend receives OTLP → decodes to `(ts, value)` tuples → writes to hot table → hourly compaction to cold Gorilla blocks.

- [ ] **`/api/decompress` endpoint on `collector/`.** Accepts a base64 Gorilla block, returns decoded points as JSON. Allows the Python `monitor/` to avoid reimplementing the go-tsz bit-stream decoder.

- [ ] **Compression ratio measurement.** Instrument `Series.Flush()` to log `uncompressed_bytes / compressed_bytes` per series. Capture 24 h of real probe data and record actual ratio — required to validate block sizing and inform the 2-hour vs 15-minute block boundary decision (open question in theory doc §8.2).

### Open research questions

- Actual compression ratio on probe-specific distributions (loss events, Wi-Fi roaming drops, NTP corrections may have higher XOR entropy than Facebook production fleet baseline)
- `go-tsz` vs `prometheus/chunkenc` benchmark at 10 000 points/block — confirm sub-millisecond encode/decode for the compaction job
- 2-hour vs 15-minute cold block boundary — larger blocks compress better but waste decode work for sub-5-minute dashboard queries

---

## Phase 11 — eBPF Flow Telemetry (Weeks 29–31)

**Component:** `collector/` (Linux nodes only)  
**Academic basis:** Sundberg PAM 2023 (ePPing); Hinz et al. ACM SIGCOMM 2023; Bertrone COP2 2019

> **Rationale:** Full PCAP (payload recording) was previously excluded due to GDPR
> data-minimisation obligations and prohibitive storage cost. That exclusion no
> longer applies to **eBPF-based flow metadata**: packet payloads are never
> copied to user space, so no personal data is recorded. Probing is performed
> exclusively on contracted internal networks (GDPR Art. 6(1)(b) — contractual
> necessity). Only connection-level metadata (IPs, ports, RTT, byte counts,
> TCP flags) is exported. This is the same data model used by NetFlow/IPFIX, which
> is standard practice in network operations.

### What this phase delivers

- [ ] **eBPF TC egress/ingress hook for flow metadata.** Attach a `BPF_PROG_TYPE_SCHED_CLS` program to each monitored interface. Extract per-flow 5-tuple (src_ip, dst_ip, src_port, dst_port, proto), byte count, packet count, and TCP flags into a `BPF_MAP_TYPE_LRU_HASH` keyed by flow 5-tuple. No payload bytes are ever read.

- [ ] **Per-flow RTT via TCP timestamp option (ePPing approach).** Parse TCP timestamp option (RFC 7323) in the TC hook. Match outgoing TSval → incoming TSecr to compute RTT passively for every TCP flow without active probing. Complements the kprobe `srtt_us` approach from Phase 2.

- [ ] **Flow export to `monitor/`.** Aggregate flow records every 30 s into `FlowRecord{SrcIP, DstIP, SrcPort, DstPort, Proto, Bytes, Packets, RTT_us, TCPFlags, FirstSeen, LastSeen}`. Include in the OTLP push envelope as `ebpf_flows` stream.

- [ ] **Flow-based anomaly inputs for Phase 4 RCA.**
  - `flow_count` per subnet/hour → feeds new/rogue device + port scan symptoms
  - `byte_rate` per flow → bandwidth anomaly detection
  - TCP RST/FIN ratio → connection failure indicator
  - All inputs join the existing CUSUM+EWMA pipeline as additional symptom streams

- [ ] **Graceful degradation.** If TC hook attachment fails (missing `CAP_NET_ADMIN`, container without `network_mode: host`, or kernel < 4.8), fall back to kprobe-only RTT (Phase 2) and log reason. No crash, no data loss.

- [ ] **No payload capture gate.** `BPF_F_NO_PREALLOC` maps only. Compile-time `static_assert` that no `bpf_skb_load_bytes()` call beyond L4 header offset is present in any BPF C source. CI check validates this at build time.

### Scope boundary

| Captured | Not captured |
|---|---|
| 5-tuple (IP, port, proto) | Payload bytes |
| Byte / packet counts | DNS query names |
| TCP RTT (timestamp option) | HTTP URLs / headers |
| TCP flags (SYN, RST, FIN) | TLS SNI (after handshake) |
| Flow start / end time | Any application-layer content |

---

## Phase 12 — Deep RL / Q-Learning MDP Scheduler (Weeks 31–35)

**Component:** `monitor/` (Python) → `collector/` (check plan delivery)  
**Academic basis:** Zabala et al. Mathematics 2023

> **Rationale:** Deep RL for MDP scheduling was previously excluded because it
> requires a labelled failure corpus for training. That prerequisite is now
> solvable: Phases 1–11 produce a continuous stream of labelled probe
> observations (RTT, loss, state transitions, RCA verdicts) against real
> contracted infrastructure. After ~3 months of Phase 5 (finite-state MDP)
> operation, sufficient failure episodes will exist to bootstrap a Q-network.
> The finite-state MDP (Phase 5) achieves ~80% of theoretical optimum
> (Zabala 2023) and remains the production scheduler until the Q-network
> reaches parity on held-out validation data.

### Prerequisite

- Phase 5 (finite-state MDP) must be running in production for ≥ 90 days
- Failure corpus: ≥ 500 labelled state-transition episodes (STABLE→SUSPECT→DEGRADED→DOWN + recovery) across ≥ 3 distinct target types
- Corpus is accumulated automatically from MDP state logs written by Phase 5

### What this phase delivers

- [ ] **Failure corpus schema.** `monitor/rl/corpus.py` — SQLite table `mdp_episodes(target_id, ts, state_from, state_to, rtt_p95, loss_pct, probe_interval_s, reward)`. Reward function: `r = -probe_cost + detection_speed_bonus - false_alarm_penalty` (Zabala 2023 §4.2).

- [ ] **DQN implementation.** `monitor/rl/dqn.py` — 3-layer MLP (input: 8-dim state vector, hidden: 64×64, output: 4 actions = probe intervals). `experience_replay` buffer (capacity 10 000). `epsilon`-greedy exploration (ε decay 1.0 → 0.05 over 50 000 steps). Target network updated every 1 000 steps.

- [ ] **State vector.** `[rtt_p50, rtt_p95, rtt_p99, loss_pct, rtt_variance, time_since_last_change, hour_of_week_sin, hour_of_week_cos]` — same 8 dimensions as the Phase 3 PCA detector, enabling direct comparison.

- [ ] **Offline training pipeline.** `scripts/train_dqn.sh` — loads corpus from SQLite, trains for 100 epochs, saves model to `config/rl/dqn_weights.pt`. CI job validates that episode reward on held-out 20% split exceeds finite-state MDP baseline by ≥ 5%.

- [ ] **Shadow mode evaluation.** Run DQN alongside finite-state MDP for 14 days. Compare: probe budget consumed, mean detection latency (STABLE→DEGRADED recognition time), false alarm rate. Only promote DQN to production if all three metrics improve.

- [ ] **Corpus privacy.** Corpus rows contain only `(target_id, ts, rtt, loss, state)` — no IP addresses, no payload, no personal data. `target_id` is an opaque hash of `collector_id + target_ip` (SHA-256, first 8 bytes). Compliant with GDPR data-minimisation under the same contractual basis as Phase 11.

- [ ] **Fallback.** If DQN inference latency exceeds 5 ms (p99) or model file is absent, revert to finite-state MDP transparently. Log reason.

### Training data requirement summary

| Metric | Minimum | Target |
|---|---|---|
| Labelled episodes | 500 | 2 000 |
| Distinct target types | 3 | 8 |
| Failure event types | DOWN + DEGRADED | All 4 state transitions |
| Collection period | 90 days | 180 days |

---

## Full Timeline

| Phase | Component | Description | Start | Duration |
|---|---|---|---|---|
| **1** | `collector/` | Complete check inventory (ICMP, SNMP, Modbus, WG, TLS, OS, routes) | Now | 5 weeks |
| **2** | `collector/` | eBPF: kprobe TCP RTT, netstacklat, high-latency client detection, container deployment | Wk 5 | 2 weeks |
| **3** | `monitor/` | CUSUM+EWMA+PCA anomaly detection; Holt-Winters residuals; adaptive slots | Wk 7 | 4 weeks |
| **4** | `monitor/` | Causal DAG RCA (networkx + naive Bayes); dropped connection decision tree | Wk 11 | 3 weeks |
| **5** | `monitor/`→`collector/` | MDP adaptive scheduling + Frank-Wolfe probe budget | Wk 14 | 3 weeks |
| **6** | `dashboard/` | Topology map, anomaly timeline, high-latency client table, alert routing | Wk 17 | 3 weeks |
| **7** | `monitor/`+`dashboard/` | Prometheus metrics + Grafana dashboard JSON | Wk 20 | 1 week |
| **8** | `tests/`+`scripts/`+`config/` | Full test suite, config schemas, systemd + Docker deployment | Wk 21 | 3 weeks |
| **9** | `collector/`+`monitor/` | mTLS + backend PKI (CA, `/enroll`, cert renewal, revocation) + OTLP/gRPC exporter | Wk 24 | 3 weeks |
| **10** | `collector/`+`monitor/` | Gorilla delta-of-delta compression + hot/cold SQLite store + compaction job | Wk 27 | 2 weeks |
| **11** | `collector/` | eBPF flow telemetry: TC hook, per-flow RTT, flow export, no-payload gate | Wk 29 | 2 weeks |
| **12** | `monitor/` | Deep RL / DQN scheduler: corpus accumulation, offline training, shadow eval | Wk 31 | 4 weeks |

**Total: 35 weeks (~9 months)**

---

## Prior-Roadmap Reconciliation

| Prior item | Folded into | Rationale |
|---|---|---|
| **#54** SNMPv3 read + STP observation | Phase 1 | Collector-side data acquisition; STP change becomes a stream field |
| **#50** TCP retransmission/reset + DNS failure trends | Phase 3 | ✅ v1 shipped (`33c798b`): /proc TCP counters + DNS trends, EWMA sustained-vs-spike, `/api/monitor/{tcp,dns}`; eBPF+shared-detector wiring still to layer on |
| **#51** Baselines by segment / hour / production state | Phase 3 | Generalises the 168-bucket adaptive control limits |
| **#53** Webhook/email alerting on sustained state changes | Phase 6 | ✅ v1 shipped: edge-triggered on #50 classifier, webhook+SMTP, Settings panel, `/api/alerts*`, 34 tests |
| **#48** Session/acceptance report (JSON/CSV/HTML) + hashes | Phase 6 | ✅ shipped — `dashboard/report.py` + `/api/report/session` + Settings export panel; SHA-256 digest, tamper-evident |
| **#47** Freeze-evidence action + disk reserve/capture policy | Phase 6 (trigger) + Phase 8 (policy) | Dashboard action snapshots JSON telemetry; disk-reserve is config/hardening |
| **PCAP / full packet capture** | Phase 11 | Moved from out-of-scope: eBPF TC hook captures flow metadata only (no payload). GDPR-compliant on contracted internal networks. |
| **Full Q-learning / deep RL for MDP** | Phase 12 | Moved from out-of-scope: failure corpus accumulates automatically from Phase 5 MDP logs. Finite-state MDP remains production scheduler until DQN reaches parity. |

---

## What Is Deliberately Out of Scope

| Item | Reason |
|---|---|
| Anomaly detection in `collector/` | Collector is stateless data-plane only. All maths lives in `monitor/`. |
| Custom ML training pipeline (general) | CUSUM+EWMA+PCA are parameter-light; validated on real ISP data (Münz 2010); no labelled training data needed. Phase 12 covers the specific RL use case. |
| eBPF on Windows nodes | Not supported by the Linux kernel eBPF subsystem. Windows nodes use active ICMP probing (graceful fallback). |
| External PKI / Let's Encrypt | Backend-generated CA is sufficient for a closed probe fleet. External PKI adds ACME dependency with no security benefit for internal-only collectors. |
| Payload / application-layer capture | eBPF TC hook is compile-time gated to L4 header only. No DNS names, HTTP URLs, TLS content, or any application payload is ever recorded. |

---

## References

1. Sundberg et al. PAM 2023. https://doi.org/10.1007/978-3-031-28486-1_9
2. Rezvani et al. ISPASS 2024. https://danielwong.org/files/eBPF-ISPASS2024.pdf
3. Bertrone et al. COP2, arXiv:1902.04280, 2019.
4. Red Hat / netstacklat 2026. https://developers.redhat.com/articles/2026/04/29/
5. Münz, G. TU Munich, NET-2010-06-1. https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2010-06-1.pdf
6. Christodoulou et al. DSAA 2015. https://pure.ulster.ac.uk/en/publications/a-combination-of-cusum-ewma-for-anomaly-detection-in-time-series--3
7. Tikumporn et al. IEEE Access 2025. https://doi.org/10.1109/ACCESS.2025.11053841
8. Hinz et al. ACM SIGCOMM 2023. https://dl.acm.org/doi/10.1145/3609021.3609295
9. Zabala et al. Mathematics 11(3):610, 2023. https://doi.org/10.3390/math11030610
10. Amjad et al. arXiv:2109.07743, 2021.
11. Zhao et al. arXiv:2408.04856, 2024.
12. Pelkonen et al. VLDB 2015. https://www.vldb.org/pvldb/vol8/p1816-teller.pdf
13. Tagliaro et al. ACM CCS 2024.
14. After et al. MDPI Sensors 2023.
15. Gupta et al. (Sonata) HotNets 2016.
16. van Adrichem et al. (Trinocular) TMA 2025.
17. cilium/ebpf tcp_close example. https://github.com/cilium/ebpf/blob/main/examples/tcprtt/
18. tsenart/go-tsz. https://pkg.go.dev/github.com/tsenart/go-tsz

---

### P5 — excluded-by-default capability gate

A governance surface (Dashboard → **Dangerous Actions**), NOT an attack toolkit.
Each excluded behaviour is registered, shown with its risk, and gated behind an
explicit master switch plus per-item acknowledgement, with every attempt written
to the audit trail. The checkbox marks that the item is **surfaced and gated** —
the destructive technique itself is deliberately **not implemented**.

- [x] Automatic subnet expansion — gated, refused by design
- [x] Vulnerability / exploit scanning — gated, refused by design
- [x] Credential guessing, default-password checks — gated, refused by design
- [x] SNMP community sweeps — gated, refused by design
- [x] Wi-Fi deauthentication — gated, refused by design
- [x] Wi-Fi frame injection — gated, refused by design
- [x] Wi-Fi AP impersonation (rogue/evil-twin) — gated, refused by design
- [x] S7 / OPC UA writes — gated, refused by design
- [x] PLC mode changes / program operations — gated, refused by design
- [x] Arbitrary OPC UA node browsing — gated, refused by design
- [x] Inline blocking / automatic production changes — gated, refused by design
- [x] Internet dashboard exposure — gated, refused by design
