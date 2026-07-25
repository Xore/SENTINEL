# Repository Roadmap
## analyseLaptop — Network Health & Anomaly Detection System

> **Updated:** 2026-07-25  
> **Scope:** Entire repository — `collector/`, `monitor/`, `dashboard/`, `config/`, `scripts/`, `tests/`  
> Phases are additive. Each builds directly on the previous. The collector roadmap (`collector/ROADMAP.md`) is the implementation detail for Phase 1–3 of this document.

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        analyseLaptop System                         │
│                                                                     │
│  ┌──────────────┐   push JSON   ┌─────────────────────────────┐    │
│  │  collector/  │ ─────────────▶│         monitor/            │    │
│  │  (Go agent)  │               │  (aggregator + analyser)    │    │
│  │              │◀───check plan─│                             │    │
│  └──────────────┘               │  ┌─────────────────────┐   │    │
│   runs on each                  │  │  Anomaly Detection  │   │    │
│   monitored node                │  │  CUSUM / EWMA / PCA │   │    │
│                                 │  └─────────────────────┘   │    │
│                                 │  ┌─────────────────────┐   │    │
│                                 │  │   Root Cause Engine │   │    │
│                                 │  │   (causal graph)    │   │    │
│                                 │  └─────────────────────┘   │    │
│                                 └──────────────┬──────────────┘    │
│                                                │                   │
│                                                ▼                   │
│                              ┌────────────────────────────────┐   │
│                              │         dashboard/             │   │
│                              │   (web UI + Grafana + alerts)  │   │
│                              └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Academic Research Basis

This roadmap is grounded in the following peer-reviewed sources. Each phase cites the specific papers that justify its design.

| Paper | Key Contribution |
|---|---|
| Sundberg et al. **"Efficient Continuous Latency Monitoring with eBPF"** PAM 2023, Springer LNCS 13882. https://doi.org/10.1007/978-3-031-28486-1_9 | ePPing eBPF design; 1 Mpps / 10 Gbps on a single core; TCP timestamp matching for passive RTT |
| Rezvani et al. **"Characterizing In-Kernel Observability of Latency-Sensitive Workloads"** ISPASS 2024. https://danielwong.org/files/eBPF-ISPASS2024.pdf | Per-request latency breakdown (kernel stack, scheduler delay, NIC queue) using eBPF kprobes |
| Red Hat / Sundberg **"netstacklat: eBPF-powered network stack latency"** 2026. https://developers.redhat.com/articles/2026/04/29/ | In-kernel per-packet latency at each network stack layer — identifies *where* latency is introduced |
| Münz, G. **"Traffic Anomaly Detection and Cause Identification Using Flow-Level Measurements"** TU Munich Dissertation, NET-2010-06-1. https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2010-06-1.pdf | CUSUM + Shewhart control charts; PCA multi-metric anomaly detection; automated cause identification algorithms for scans, port sweeps, brute-force |
| Christodoulou et al. **"A Combination of CUSUM-EWMA for Anomaly Detection in Time Series"** DSAA 2015. https://pure.ulster.ac.uk/en/publications/a-combination-of-cusum-ewma | Combined CUSUM-EWMA outperforms either alone on complex anomalies; reduces false positives |
| Tikumporn et al. **"Automated Root Cause Analysis of Network Failures in IP Networks"** IEEE Access 2025. https://doi.org/10.1109/ACCESS.2025.11053841 | Causal graph (DAG) based RCA; symptom-to-cause mapping; 92% accuracy on real failure corpus |
| Zabala et al. **"Optimality of a Network Monitoring Agent"** Mathematics 11(3):610, 2023. https://doi.org/10.3390/math11030610 | MDP optimal scheduling; adaptive intervals outperform fixed by 40–60% in detection latency |
| Amjad et al. **"Optimal Probing with Statistical Guarantees"** arXiv:2109.07743, 2021. https://doi.org/10.48550/arXiv.2109.07743 | A-optimal probe budget; Frank-Wolfe approximation; 50% probe reduction |
| Hinz et al. **"TCP's Third Eye: Leveraging eBPF for Telemetry-Powered Congestion Control"** ACM SIGCOMM Workshop 2023. https://dl.acm.org/doi/10.1145/3609021.3609295 | eBPF-extracted TCP congestion signals (cwnd, rtt_var, retransmit rate) for per-flow diagnosis |

---

## Phase 1 — Collector: Complete Check Inventory (Weeks 1–5)

**Component:** `collector/`  
**Detail:** See `collector/ROADMAP.md` Phases 0–1 for full implementation specification.

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

---

## Phase 2 — eBPF Passive Latency Layer (Weeks 5–7)

**Component:** `collector/` (Linux nodes only)  
**Academic basis:** Sundberg et al. PAM 2023; Rezvani et al. ISPASS 2024; Red Hat netstacklat 2026

### 2a. ePPing — Passive TCP RTT per Flow

ePPing attaches a BPF program to the Linux TC (traffic control) ingress hook. It matches TCP timestamp option pairs (TSval / TSecr) across both directions of each TCP flow to compute round-trip time **without injecting a single byte** of synthetic traffic.

```
Kernel TC hook (ingress)
  ├── parse TCP TSval  →  store {flow_tuple + TSval → timestamp} in BPF hash map
  └── parse TCP TSecr  →  lookup map → compute RTT = now − stored_ts → push to ring buffer

User-space goroutine reads ring buffer every collection cycle:
  → aggregate per (src_subnet, dst_subnet) → p50/p95/p99 histograms
  → emit as "passive_rtt" stream in the push envelope
```

**Proven capability (Sundberg 2023):** handles >1 Mpps (>10 Gbps) on a single CPU core with 3× lower overhead than userspace PPing. [web:86]

**Constraint:** TCP timestamps must be enabled (default on Linux, macOS, Android, iOS — not Windows). For Windows-originating flows, fall back to active ICMP probing.

### 2b. netstacklat — Per-Layer Stack Latency

The Red Hat `netstacklat` tool (2026) uses eBPF kprobes to measure **where inside the kernel** latency is added: [web:80]

| Measurement point | What it reveals |
|---|---|
| NIC driver → socket buffer arrival | NIC queue depth, interrupt coalescence delay |
| Socket buffer → `tcp_rcv` | Kernel scheduler preemption delay |
| `tcp_rcv` → `recvmsg()` return | Application wakeup latency (epoll delay) |

This breaks the "the network is slow" problem into: **is it the wire, the kernel, or the application?**

**Implementation:** vendor `netstacklat` BPF C program; load via `cilium/ebpf`; expose per-layer histograms as `stack_latency` stream.

### 2c. High-Latency Client Detection

Using the per-flow RTT data from ePPing, the collector can identify **which specific client IPs** are experiencing anomalously high latency relative to the subnet baseline:

```go
// For each observed flow:
//   if flow_rtt_p95 > subnet_baseline_p95 * threshold_multiplier (default 3.0):
//     emit high_latency_client event with: src_ip, dst_ip, rtt_p95, baseline, ratio
// Subnet baseline: rolling EMA of all flows in that /24 over last 5 minutes
```

This directly answers "which clients are degrading or experiencing degraded service" without any active probing of those clients.

---

## Phase 3 — Monitor: Time-Series Anomaly Detection (Weeks 7–11)

**Component:** `monitor/`  
**Academic basis:** Münz TU Munich 2010; Christodoulou et al. DSAA 2015

The `monitor/` process receives the JSON stream from all collectors and runs statistical change detection on every metric time series. **No ML training required** — these are parameter-light control chart methods proven on real ISP data.

### 3a. Metric Time-Series Pipeline

```
Raw JSON stream
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│  Time-Series Conversion (monitor/timeseries.go)         │
│  • bucket into fixed intervals (default: 60s)           │
│  • compute per-metric aggregates: mean, p95, rate       │
│  • 8 traffic metrics tracked per collector stream:      │
│    volume (bytes/s), packet rate, flow count,           │
│    distinct src_ips, distinct dst_ips,                  │
│    error rate, loss rate, RTT p95                       │
└─────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│  Residual Generation (monitor/residuals.go)             │
│  Remove seasonal variation and trend before detection   │
│                                                         │
│  Method: Holt-Winters exponential smoothing             │
│  • α = 0.2 (level), β = 0.1 (trend), γ = 0.3 (season) │
│  • Season period: 24h (daily pattern)                   │
│  • Residual = observed − Holt-Winters forecast          │
│  • Robust to non-stationarity (proven: Münz 2010)       │
└─────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│  Change Detection (monitor/detector.go)                 │
│  Applied to residual series, not raw values             │
│                                                         │
│  Layer 1 — Shewhart chart (fast, single-point):         │
│    alarm if |residual| > k·σ (default k=3)              │
│    detects sudden large shifts immediately              │
│                                                         │
│  Layer 2 — CUSUM chart (cumulative, drift-sensitive):   │
│    C+ = max(0, C+_prev + residual − slack)              │
│    C- = max(0, C-_prev − residual − slack)              │
│    alarm if C+ > h or C- > h (h = decision interval)   │
│    detects slow gradual degradation (e.g. memory leak)  │
│                                                         │
│  Layer 3 — EWMA chart (smoothed trend):                 │
│    Z_t = λ·x_t + (1−λ)·Z_{t-1}   (λ = 0.2)            │
│    alarm if |Z_t − μ| > L·σ·√(λ/(2−λ))                │
│    reduces false positives vs Shewhart (proven 2015)    │
│                                                         │
│  Combined: alarm only if CUSUM + EWMA both trigger      │
│  (reduces false positives significantly — Christodoulou)│
└─────────────────────────────────────────────────────────┘
```

### 3b. Multi-Metric PCA Anomaly Detection

For cases where anomalies appear across *multiple* metrics simultaneously but are individually below the Shewhart/CUSUM threshold (e.g., a slow scan that slightly increases flow count, distinct IPs, and error rate together):

```
Metric vector per interval: x = [vol, pkt_rate, flow_cnt, src_ips, dst_ips, err_rate, loss_pct, rtt_p95]

PCA:
  1. Compute covariance matrix Σ from last 7 days of stable data (training window)
  2. Decompose: Σ = VΛVᵀ (eigendecomposition)
  3. Keep top k principal components explaining 90% of variance
  4. Project residual vector onto PC space: scores = Vᵀ · residual
  5. Hotelling's T² statistic: T² = scoresᵀ · Λ⁻¹ · scores
  6. Alarm if T² > χ²(k, α=0.001) critical value

Incremental PCA update (Münz 2010):
  • Recompute Σ incrementally — no full batch retraining
  • Use M-estimators for robustness: replace mean with Huber location estimator
    to prevent anomalies in training data from biasing the baseline
```

**Why PCA here, not the collector:** PCA requires a multi-node, multi-stream view. The collector only sees its local node. The `monitor/` process aggregates all collectors and can correlate across the full network topology.

### 3c. Adaptive Control Limits

Rather than fixed σ thresholds, implement **time-varying control limits** that widen during periods of known high variance (peak hours, backup windows) and tighten during quiet periods:

```go
// Per metric, per hour-of-week slot:
//   track σ_slot = rolling stddev of residuals in that slot
// Control limit = k * σ_slot (rather than global σ)
// This eliminates the vast majority of peak-hour false positives
// while maintaining sensitivity during off-peak
```

---

## Phase 4 — Monitor: Automated Root Cause Analysis (Weeks 11–14)

**Component:** `monitor/`  
**Academic basis:** Tikumporn et al. IEEE Access 2025; Münz TU Munich 2010 (Chapter 10)

### 4a. Causal Graph (DAG) Architecture

Root cause analysis (RCA) answers: *given that anomaly detector fired on metric M at node N, what is the most probable cause?*

The Tikumporn 2025 system achieves 92% RCA accuracy on real IP network failure data using a **causal DAG** where:
- **Nodes** are observable symptoms (metric anomaly fires)
- **Edges** encode causal relationships with conditional probabilities
- **Root nodes** are actionable causes (link failure, misconfigured host, congestion, etc.)

```
monitor/rca/
├── graph.go       — DAG definition and traversal
├── symptoms.go    — maps anomaly detector outputs to symptom nodes
├── causes.go      — actionable cause definitions + remediation hints
└── engine.go      — Bayesian belief propagation
```

### 4b. Symptom → Cause Mapping Table

The following causal chains are pre-defined based on the TU Munich and IEEE Access research:

| Observed Symptoms | Most Probable Cause | Confidence |
|---|---|---|
| RTT p95 ↑ + loss_pct = 0 + bandwidth normal | Bufferbloat / AQM issue | High |
| RTT p95 ↑ + loss_pct ↑ + affects all targets in subnet | Upstream congestion / WAN link degradation | High |
| RTT p95 ↑ + loss_pct ↑ + affects ONE target only | Target host overloaded or cable issue | High |
| loss_pct = 100% + ARP entry gone | Target powered off or cable unplugged | High |
| sysUpTime regression (SNMP) | Device rebooted (planned or crash) | High |
| rx_error_rate spike on interface | Physical layer fault (cable, SFP, wireless interference) | Medium |
| distinct_src_ips ↑ anomaly + flow_count ↑ | New device on network / DHCP storm | Medium |
| dst_ip concentration → single host, high flow_count | Port scan or brute-force attack | Medium |
| DNS latency ↑ + WAN RTT normal | Local DNS resolver overloaded | High |
| WG handshake_age > 3 min | WireGuard tunnel dropped | High |
| TLS cert days_remaining < 7 | Certificate about to expire | Certain |
| CPU ratio > 0.85 sustained + high RTT | Collector node itself is the bottleneck | Medium |

### 4c. Belief Propagation Algorithm

```go
// For each triggered anomaly event:
// 1. Map to symptom node(s) in the DAG
// 2. Propagate belief upward toward root causes:
//    belief(cause) = P(cause | symptoms) using Bayes' theorem
//    P(cause | s1, s2, ...) ∝ P(s1|cause)·P(s2|cause)·P(cause)
// 3. Select cause with highest posterior belief
// 4. If belief < confidence_threshold (0.6): emit "UNKNOWN — manual review"
// 5. Include remediation hint in alert payload

type RCAResult struct {
    Cause           string
    Confidence      float64
    AffectedTargets []string
    RemediationHint string
    EvidenceChain   []string  // human-readable causal chain
}
```

### 4d. Drop Connection Root Cause (Specific)

For **dropped connections** specifically (TCP RST events, WG tunnel drops, ICMP unreachable bursts), the RCA engine runs a specialised decision tree:

```
Dropped connection detected
  │
  ├─ Is the target's ARP entry still present?
  │     No  → Physical disconnection / power loss
  │     Yes → continue
  │
  ├─ Is the DEFAULT GATEWAY reachable?
  │     No  → Routing failure (check GW, check route table)
  │     Yes → continue
  │
  ├─ Is the WAN reachable (external ping)?
  │     No  → ISP / uplink failure
  │     Yes → continue
  │
  ├─ Is the TARGET reachable from another collector?
  │     No  → Target-side failure
  │     Yes → Path-specific failure (asymmetric routing / firewall rule)
  │
  └─ RTT elevated before the drop?
        Yes → Congestion-induced timeout (not a hard failure)
        No  → Application crash / firewall session timeout
```

This multi-collector correlation requires the `monitor/` process to cross-reference observations from different agents — the key reason the collector/monitor split architecture is correct.

---

## Phase 5 — Monitor: MDP Adaptive Scheduling + Probe Budget (Weeks 14–17)

**Component:** `monitor/` → `collector/` (check plan delivery)  
**Academic basis:** Zabala et al. Mathematics 2023; Amjad et al. arXiv 2021  
**Detail:** See `collector/ROADMAP.md` Phases 4–5

The `monitor/` process computes the **optimal check plan** for each collector based on the current health state of all targets, and pushes updated plans back to the collectors. This closes the control loop:

```
monitor/ (control plane):
  1. Receive probe results from collector
  2. Update MDP state machine per target (STABLE/SUSPECT/DEGRADED/DOWN)
  3. Compute probe weight per target (proportional to RTT variance — Amjad 2021)
  4. Generate updated check_plan.json
  5. Push check_plan back to collector via /config endpoint

collector/ (data plane):
  1. Receive updated check_plan
  2. Adjust probe intervals per target state
  3. Concentrate probe budget on high-variance / degraded targets
```

The collector-side implementation detail is in `collector/ROADMAP.md`. The monitor-side is the state aggregator and plan generator.

---

## Phase 6 — Dashboard: Visualisation & Alerting (Weeks 17–20)

**Component:** `dashboard/`

### 6a. Topology Map

Real-time network graph rendered from ARP/neighbour data + routing table data collected by all agents:

- Nodes: collector hosts, gateways, OT devices, WireGuard peers
- Edges: annotated with current RTT p95 and loss % (colour-coded: green/amber/red)
- Node badges: MDP state (STABLE / SUSPECT / DEGRADED / DOWN)
- Click-through: per-node time-series charts for all metrics

### 6b. Anomaly Timeline

Horizontal swim-lane chart: one lane per collector, one marker per anomaly event, coloured by severity. RCA result shown in tooltip. Makes it easy to see correlated failures across multiple nodes (e.g., "three collectors all saw WAN RTT spike at 14:23").

### 6c. High-Latency Client Table

Live table of clients currently flagged by the eBPF high-latency detector (Phase 2c):

| Client IP | Subnet | RTT p95 (ms) | Baseline p95 (ms) | Ratio | Since |
|---|---|---|---|---|---|
| 192.168.1.42 | 192.168.1.0/24 | 87 | 3.2 | 27× | 14:21 |

Sortable by ratio. Clicking opens the full flow history for that client.

### 6d. Alert Routing

```
Anomaly event → RCA engine → RCAResult
  │
  ├─ confidence > 0.8 → auto-alert with cause + remediation hint
  ├─ confidence 0.6–0.8 → alert flagged as "probable" + manual review suggested  
  └─ confidence < 0.6 → alert flagged as "UNKNOWN — raw symptoms only"

Channels:
  • webhook (configurable URL, JSON body)
  • email (SMTP)
  • Alertmanager (for Grafana integration, Phase 7)
```

---

## Phase 7 — Prometheus + Grafana Integration (Weeks 20–21)

**Component:** `monitor/` + `dashboard/`

Both the `collector/` (see `collector/ROADMAP.md` Phase 7) and `monitor/` expose a `/metrics` Prometheus endpoint. The monitor additionally exports:

```
# Anomaly detection outputs
anomaly_events_total{collector, metric, detector}          counter
anomaly_active{collector, target, state}                   gauge
rca_cause_total{cause}                                     counter
rca_confidence_histogram                                   histogram

# Cross-collector aggregates  
network_rtt_p95_seconds{src_collector, dst_target}         gauge
network_loss_ratio{src_collector, dst_target}              gauge
high_latency_clients_total{subnet}                         gauge
```

Provide a `dashboard/grafana/` directory with pre-built dashboard JSON for import.

---

## Phase 8 — Hardening, Tests, Deployment (Weeks 21–24)

**Component:** `tests/`, `scripts/`, `config/`

### 8a. Test Coverage

```
tests/
├── unit/
│   ├── detector_cusum_test.go   — CUSUM correctness with synthetic anomaly series
│   ├── detector_ewma_test.go    — EWMA false positive rate validation
│   ├── rca_engine_test.go       — DAG traversal and belief propagation
│   └── mdp_scheduler_test.go   — State machine transitions
├── integration/
│   ├── collector_push_test.go   — Full push cycle with mock aggregator
│   └── rca_multinode_test.go   — Cross-collector RCA correlation
└── load/
    └── collector_load_test.go  — 1000-target check plan at 5s intervals, <50ms cycle time
```

### 8b. Configuration Schema

`config/` should provide validated JSON schemas for:
- `collector.json` — check plan, target list, push endpoint, eBPF enable flag
- `monitor.json` — aggregator config, detector parameters (k, h, λ), RCA confidence thresholds
- `alerts.json` — routing rules, channel credentials

### 8c. Deployment Scripts

```
scripts/
├── install-collector.sh   — systemd unit install (Linux), requests CAP_BPF if eBPF enabled
├── install-monitor.sh     — install monitor + configure reverse proxy (caddy/nginx)
├── install-dashboard.sh  — static build + serve, or Docker compose
└── update.sh             — rolling update with health check gate
```

---

## Full Timeline

| Phase | Component | Description | Start | Duration |
|---|---|---|---|---|
| **1** | `collector/` | Complete check inventory (ICMP, SNMP, Modbus, WG, TLS, OS, routes) | Now | 5 weeks |
| **2** | `collector/` | eBPF passive RTT (ePPing + netstacklat + high-latency client detection) | Wk 5 | 2 weeks |
| **3** | `monitor/` | CUSUM+EWMA+PCA anomaly detection engine with Holt-Winters residuals | Wk 7 | 4 weeks |
| **4** | `monitor/` | Automated RCA: causal DAG, belief propagation, drop connection decision tree | Wk 11 | 3 weeks |
| **5** | `monitor/`→`collector/` | MDP adaptive scheduling + Frank-Wolfe probe budget optimisation | Wk 14 | 3 weeks |
| **6** | `dashboard/` | Topology map, anomaly timeline, high-latency client table, alert routing | Wk 17 | 3 weeks |
| **7** | `monitor/`+`dashboard/` | Prometheus metrics export + Grafana dashboard JSON | Wk 20 | 1 week |
| **8** | `tests/`+`scripts/`+`config/` | Full test coverage, config schemas, deployment scripts | Wk 21 | 3 weeks |

**Total estimated duration: 24 weeks (~6 months)**

---

## What Is Deliberately Out of Scope

| Item | Reason |
|---|---|
| Mathematical anomaly detection implementation in `collector/` | The collector is a data-plane agent — lightweight, stateless. All statistical computation lives in `monitor/`. Mixing concerns breaks the architecture. |
| Full Q-learning / deep RL for MDP scheduler | Requires a failure corpus for training. The finite-state MDP approximation (Phases 1, 5) is deployable immediately without training data and achieves 80% of the theoretical optimum per Zabala 2023. |
| Packet capture / PCAP recording | Out of scope — eBPF passive monitoring provides RTT and flow metadata without recording payloads. Recording payloads creates GDPR and storage burden. |
| Custom ML model training pipeline | Not needed — CUSUM+EWMA+PCA are parameter-light statistical methods that require no labelled training data. They have been validated on real ISP networks (Münz 2010). |

---

## References

1. Sundberg, S., Brunstrom, A., Ferlin-Reiter, S., Høiland-Jørgensen, T., Brouer, J.D. "Efficient Continuous Latency Monitoring with eBPF." PAM 2023, LNCS 13882. https://doi.org/10.1007/978-3-031-28486-1_9
2. Rezvani, M. et al. "Characterizing In-Kernel Observability of Latency-Sensitive Workloads using eBPF." ISPASS 2024. https://danielwong.org/files/eBPF-ISPASS2024.pdf
3. Red Hat Engineering. "Boosting speed: Use eBPF and netstacklat to troubleshoot latency." 2026. https://developers.redhat.com/articles/2026/04/29/boosting-speed-use-ebpf-and-netstacklat-troubleshoot-latency
4. Münz, G. "Traffic Anomaly Detection and Cause Identification Using Flow-Level Measurements." TU Munich Dissertation, NET-2010-06-1. https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2010-06-1.pdf
5. Christodoulou, V. et al. "A Combination of CUSUM-EWMA for Anomaly Detection in Time Series." DSAA 2015. https://pure.ulster.ac.uk/en/publications/a-combination-of-cusum-ewma-for-anomaly-detection-in-time-series--3
6. Tikumporn, W. et al. "Automated Root Cause Analysis of Network Failures in IP Networks." IEEE Access, 2025. https://doi.org/10.1109/ACCESS.2025.11053841
7. Hinz, J.-T. et al. "TCP's Third Eye: Leveraging eBPF for Telemetry-Powered Congestion Control." ACM SIGCOMM Workshop, 2023. https://dl.acm.org/doi/10.1145/3609021.3609295
8. Zabala, L. et al. "Optimality of a Network Monitoring Agent." Mathematics 11(3):610, 2023. https://doi.org/10.3390/math11030610
9. Amjad, M.J. et al. "Optimal Probing with Statistical Guarantees for Network Monitoring at Scale." arXiv:2109.07743, 2021. https://doi.org/10.48550/arXiv.2109.07743
