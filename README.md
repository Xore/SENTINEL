# SENTINEL
### Scalable Edge Network Telemetry and Intelligent Network ELement

> **v1 (current):** A single-host IT/OT network probe — passive capture, active checks, anomaly detection, and a Python/Flask dashboard.  
> **v2 (in design):** A distributed multi-site monitoring platform: Go collector fleet → Go ingest + Python analysis + Go API → VictoriaMetrics + PostgreSQL → SvelteKit frontend, with multi-site federation, backend HA, federated ML, and cross-site anomaly correlation. **v2 is not yet implemented.** See [`docs/architecture/ARCHITECTURE-V2-EXTENDED.md`](docs/architecture/ARCHITECTURE-V2-EXTENDED.md) for the full design.

---

## What is SENTINEL?

SENTINEL is a **lightweight, passive-first IT/OT network monitoring system** designed for environments where visibility matters and false positives cost operational time. It runs on commodity hardware — a laptop, a Raspberry Pi, or a small VM — and requires no external SIEM, no Elasticsearch stack, and no container platform.

The probe is **passive by default**. It observes mirrored traffic from a managed-switch SPAN port or a network TAP. Active checks are deliberately separate, target allow-listed, low-rate, and require approval from the OT system owner. Never connect this device inline with a control path.

---

## v1 — Current Implementation

v1 is a **monolithic single-host probe** built around a Python analysis stack and a Flask web dashboard. It is operational today.

### Architecture

```text
                          management VLAN / VPN
 Analyst browser  <-------------------------------->  NIC 1 (IP, firewall)
                                                        Probe host
 Switch TAP/SPAN  --------------------------------->  NIC 2 (no IP)
                                              Passive capture + optional services
 Optional Wi-Fi adapter  -------------------------->  monitor-mode capture
```

- **Management NIC:** built-in Ethernet or USB NIC on DHCP. Dashboard and SSH live here.
- **Capture NIC:** separate Intel-based wired adapter with no IP address. Fed from a TAP or SPAN port.
- **Wi-Fi capture:** separate Linux-compatible USB adapter in monitor mode. One radio/channel cannot provide a complete view; capturing encrypted Wi-Fi payloads requires authorisation and appropriate keys.
- **Do not use a laptop connection as an inline bridge.** A probe failure must not interrupt production.

### Hardware target

| Component | Recommended | Minimum |
|---|---:|---:|
| CPU | x86-64, 6–8 modern cores | 4 cores |
| RAM | 16–32 GB | 8 GB |
| Storage | 1–2 TB NVMe TLC | 512 GB SSD |
| Networking | 2 independent Ethernet NICs; Intel preferred | 2 NICs |
| Other | TPM 2.0, full-disk encryption, wired power | — |

### Install sequence

> **In a hurry?** [`scripts/setup.sh`](scripts/setup.sh) is a unified, menu-driven installer. Preview with `./scripts/setup.sh --standalone --dry-run`, then apply with `sudo ./scripts/setup.sh --standalone --apply`. Full guide: [docs/guides/00-setup.md](docs/guides/00-setup.md).

1. Read [docs/guides/01-design-and-safety.md](docs/guides/01-design-and-safety.md) and obtain written authorisation and network scope.
2. Install **Ubuntu Desktop 24.04 LTS** with full-disk encryption.
3. Patch Ubuntu, create a non-root administrator, enable Secure Boot if supported.
4. Copy this repository to the probe, run `sudo ./scripts/preflight.sh`, then `sudo ./scripts/install-lightweight.sh`.
5. Follow [docs/guides/02-install-lightweight.md](docs/guides/02-install-lightweight.md) for optional ntopng, Zeek, and Suricata layers.
6. Install the dashboard service:
   ```bash
   sudo cp -r ~/analyseLaptop /opt/analyseLaptop
   sudo chmod -R a+rX /opt/analyseLaptop
   sudo /opt/analyseLaptop/scripts/install-dashboard-service.sh --apply
   sudo /opt/analyseLaptop/scripts/install-outage-monitor.sh --apply
   ```
7. (Optional) Passive signature IDS: `sudo ./scripts/install-ids.sh --apply [capture-interface]`
8. (Optional) LLDP/CDP neighbour discovery: `sudo ./scripts/install-neighbors.sh --apply`
9. (Optional) Live flow analysis: `sudo ./scripts/install-ntopng.sh --apply [capture-interface]`
10. Configure the SPAN/TAP per [docs/guides/03-capture-and-wifi.md](docs/guides/03-capture-and-wifi.md).
11. Enter known assets in `config/assets.csv`.
12. After authorisation: copy `config/targets.example.csv` to `config/targets.csv` for active checks.
13. Routine operation: [docs/guides/04-operations.md](docs/guides/04-operations.md).

### Core components (v1)

| Component | Language | Role |
|---|---|---|
| `monitor/outage_monitor.py` | Python | Continuous per-path ping/Wi-Fi recorder, outage events, service checks, route tracking |
| `monitor/discovery.py` | Python | LAN host inventory — IP, MAC, vendor, reverse DNS |
| `monitor/wifi_survey.py` | Python | Wi-Fi AP/channel survey (nmcli/iw) |
| `monitor/ids_reader.py` | Python | Read-only Suricata `eve.json` alert reader |
| `monitor/snmp_probe.py` | Python | Read-only single-host SNMP (v2c/v3) |
| `dashboard/` | Python/Flask | Local web UI + API; SQLite backend |
| `collector/` | Go | Active-check agent (ICMP, DNS, HTTP/S, TCP, NTP); cross-platform |
| `scripts/` | Bash | Install, capture, verification, and operator tools |

### What v1 detects

- Suricata signature alerts (Security tab)
- New or unexpected devices, services, DHCP/DNS behaviour, TLS certificates, communication pairs
- Traffic volume, top talkers, failed connections, retransmission clues, broadcast/multicast behaviour
- Passive S7comm, S7comm Plus, PROFINET, and OPC UA operations visible at the monitored point
- Unexpected engineering-station/PLC relationships, programming/upload/download, unusual OPC UA connections
- Wi-Fi RF issues: retransmissions, beacon loss, channel congestion
- Per-hop route changes and latency degradation via `mtr`

**What it cannot see:** traffic that does not cross the monitored link, encrypted application content without keys, radio traffic on channels not currently monitored, or attacks that leave no observable network trace.

### Dashboard exposure

By default the dashboard binds to `127.0.0.1` (access via SSH tunnel). To expose on the management LAN:

```bash
sudo PROBE_EXPOSE=lan /opt/analyseLaptop/scripts/install-dashboard-service.sh --apply
```

Default login: **admin / admin** — change immediately under **Settings → Account**. Transport is plain HTTP; acceptable on a trusted management network, never through a public port-forward.

### Continuous outage monitor

The primary live instrument is `monitor/outage_monitor.py`:

- One `ping -O` stream per (target, interface) pair, one sample per second. Probing the same destinations via Wi-Fi *and* wired NIC separates radio problems from network problems.
- Wi-Fi link telemetry every 5 s (signal, bitrate, tx retries/failures, beacon loss).
- Everything lands in SQLite (`/var/lib/network-probe/monitor.db`, 14-day retention). Outage events open after 3 consecutive misses, close after 5 consecutive replies.
- Service-health profiles every 60 s: DNS query time, HTTP/HTTPS with connect/TLS/response timings, TCP connect, NTP sync offset.
- Route quality: `mtr -n -j` every 5 min per target — full hop chain with per-hop loss %, last/avg/best/worst RTT, and jitter.
- Plots, route tables, and event timeline live at `/monitor` — including an internal path map (SVG topology) and hop-quality cards.

### Collector (Go, cross-platform)

The `collector/` directory contains a **Go-based active-check agent** that runs on any host (Linux, Windows, macOS) and reports to the probe API.

Checks: ICMP ping, DNS resolution, HTTP/HTTPS timing, TCP connect, NTP offset, port health.

Scheduled on a 30 s tick. Results go to the dashboard API or local SQLite. Pre-built binaries in `collector/dist/`.

```bash
cd collector && go build -o collector-linux-amd64 ./...
./collector-linux-amd64 --standalone --config config/collector.example.yaml
```

---

## v2 — Planned Architecture (not yet implemented)

> **Status:** Design complete. Implementation not started.  
> **Primary document:** [`docs/architecture/ARCHITECTURE-V2-EXTENDED.md`](docs/architecture/ARCHITECTURE-V2-EXTENDED.md)  
> **Implementation phases:** [`ROADMAP.md`](ROADMAP.md)

v1 was designed for a single monitoring probe on a bounded network. The v2 design addresses four structural constraints that v1 cannot meet:

| Constraint | v1 | v2 |
|---|---|---|
| Scale | 1 collector, local SQLite | 50–500+ collectors, VictoriaMetrics + PostgreSQL |
| Multi-site | No cross-site visibility | Federation tier: global API, cross-site correlation |
| Availability | Single server; monitoring stops if server fails | VictoriaMetrics dual-write HA + Patroni PostgreSQL HA |
| ML cold-start | 7-day learning phase per site | Federated ML (FedAvg): new site learns in ~2 days from global model |

### v2 Service Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                      SENTINEL v2 — Single Site                       │
│                                                                      │
│  Collector tier (Go) ×50+ nodes                                      │
│  • Active checks: ICMP / DNS / HTTP / TCP / NTP                      │
│  • eBPF passive RTT (kprobe tcp_close + TC hook)                     │
│  • Gorilla local hot/cold store                                      │
│  • MDP adaptive scheduler                                            │
│  • SNMP v2c/v3, Modbus FC01/FC03, WireGuard, TLS expiry             │
│           │ mTLS + OTLP/gRPC                                         │
│           ▼                                                          │
│  backend/ingest/   (Go)   — OTLP receiver, writes VM + PG           │
│  backend/analyse/  (Python) — CUSUM/EWMA/PCA, RCA DAG, MDP, ML     │
│  backend/api/      (Go/Gin) — REST + WebSocket, JWT/RBAC auth        │
│           │                                                          │
│  VictoriaMetrics  — time-series (metrics, RTT, loss, anomaly scores) │
│  PostgreSQL       — events, anomalies, RCA, config, PKI, audit log   │
│           │                                                          │
│  frontend/ (SvelteKit/TypeScript) — static SPA via Nginx             │
│  • Fleet overview, topology map (D3/SVG)                             │
│  • Anomaly + RCA timeline                                            │
│  • ML baseline status and model management                           │
└──────────────────────────────────────────────────────────────────────┘
           │ federation agent (mTLS, selective metric + event forward)
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│              SENTINEL v2 — Global Tier (optional)                    │
│                                                                      │
│  global-api (Go/Gin)      global-vm (vmselect cluster)              │
│  global-frontend (SvelteKit)  global-pg (read replica, site_id col) │
│  Cross-site correlator (Python — DBSCAN temporal clustering)         │
│  Federated ML aggregator (Python — FedAvg gradient aggregation)      │
└──────────────────────────────────────────────────────────────────────┘
```

### v2 Capability summary

**Single-site baseline (Docker Compose, one server):**
- 50+ collectors connecting over mTLS/OTLP/gRPC to a Go ingest service
- Python analysis service: CUSUM + EWMA + PCA anomaly detection; causal DAG RCA; MDP adaptive scheduling
- ML baseline learning: LSTM Autoencoder with ADWIN concept drift detection — learns normal behaviour per collector × metric group; raises anomaly scores instead of static thresholds
- SvelteKit frontend: fleet table, topology map, anomaly timeline, RCA panel, ML management view
- RBAC: viewer / operator / analyst / admin / ot-operator roles
- vmalert + Alertmanager: alert deduplication, grouping by `(site_id, metric_group, rca_cause)`, Slack/PagerDuty routing
- Gorilla delta-of-delta compression on collector (12× vs raw `(ts, value)`)
- Tamper-evident SHA-256 evidence bundles; append-only audit log (IEC 62443 SR 2.8)
- Signed Ed25519 collector auto-update

**Multi-site federation (optional global tier):**
- Federation agent on each site server forwards only anomaly scores and RCA events to the global tier (~400 bytes/s per site)
- Global VictoriaMetrics vmselect cluster with `site_id` label injected by vmagent
- Cross-site anomaly correlator: DBSCAN temporal clustering on events across sites; shared-cause hypotheses (shared ISP fault, coordinated OT attack)
- IP-to-ASN enrichment (MaxMind GeoLite2-ASN, local, no API call) for WAN-origin correlation
- Global SvelteKit view: site fleet table, global anomaly timeline, inter-site topology, correlation panel

**Backend HA:**
- VictoriaMetrics HA: dual-write from vmagent to two independent VM nodes; deduplication at query time
- PostgreSQL HA: Patroni (etcd-backed primary election) + PgBouncer connection pooler
- All backend services stateless or advisory-lock-guarded — two instances per service behind HAProxy/Nginx

**Federated ML:**
- FedAvg gradient aggregation: sites send gradient updates only, never raw training data
- New site cold-starts from global model: effective learning phase ~2 days instead of 7
- OT sites can opt out of gradient sharing under IEC 62443 change management obligations

**Backend clustering (>500 collectors):**
- VictoriaMetrics cluster edition (vminsert/vmstorage/vmselect) — no application code change
- PostgreSQL read replicas for API query load; Citus sharding at extreme scale
- `backend/analyse/` shards by `collector_id` with PostgreSQL advisory locks

**OT-specific extensions:**
- IEC 62443 rule-based detections at confidence=1.0 (bypass ML confidence gating): Modbus FC write observed, STP topology change burst, new MAC on OT VLAN, PLC reboot (sysUpTime regression), WireGuard OT tunnel drop
- Air-gap support: USB PKI bootstrap, offline model distribution, supervised periodic VPN sync
- Deep RL / DQN scheduler (Phase 12): Q-network trained on corpus accumulated from MDP operation; shadow-mode evaluation before promotion

### v2 Design documents

| Document | Contents |
|---|---|
| [`docs/architecture/ARCHITECTURE-V2-EXTENDED.md`](docs/architecture/ARCHITECTURE-V2-EXTENDED.md) | **Primary v2 design document.** Single-site baseline, multi-site federation, HA, cross-site correlation, federated ML, backend clustering, OT isolation, alerting, RBAC, evidence, operational hardening |
| [`docs/architecture/COLLECTOR-FLEET-MONITORING.md`](docs/architecture/COLLECTOR-FLEET-MONITORING.md) | Per-collector health: heartbeat, systemd layer, host vitals, vmalert rules, Ansible ad-hoc checks, fleet status API |
| [`docs/architecture/IaC-DEPLOYMENT-STRATEGY.md`](docs/architecture/IaC-DEPLOYMENT-STRATEGY.md) | Infrastructure-as-Code strategy: Ansible, Docker Compose, Terraform, environment-specific config |
| [`docs/ml/ML_BASELINE_LEARNING.md`](docs/ml/ML_BASELINE_LEARNING.md) | ML baseline learning design: LSTM-AE architecture, ADWIN drift detection, learning phase lifecycle, PostgreSQL schema, SvelteKit ML view |
| [`ROADMAP.md`](ROADMAP.md) | Phased implementation plan (12 phases, ~35 weeks) with per-phase academic grounding |

---

## Repository map

```
collector/          Go active-check agent (v1 + v2 collector)
dashboard/          Python/Flask web UI (v1 only)
monitor/            Python monitoring stack (v1 only)
scripts/            Bash install, capture, and operator tools (v1)
config/             Example scope, asset, and target files
docs/
  architecture/     v2 design documents
    ARCHITECTURE-V2-EXTENDED.md   Primary v2 architecture (single-site + multi-site)
    COLLECTOR-FLEET-MONITORING.md Per-collector health monitoring
    IaC-DEPLOYMENT-STRATEGY.md    Infrastructure-as-Code strategy
  ml/               ML_BASELINE_LEARNING.md (v2 ML design)
  guides/           Design, install, capture, operations, research notes
  theory/           Academic background and references
  setup/            Hardware and OS setup guides
  collector/        Collector architecture and integration notes
  gap-analysis/     Feature parity gap analysis
tests/              Python integration and regression tests (pytest ≥ 8.4)
```

---

## Important safety boundary

Passive capture is the default. Do not run generic vulnerability scanners, unauthenticated SNMP sweeps, Nmap version detection, NSE scripts, S7 reads/writes, OPC UA browsing, fuzzing, or high-rate discovery against production OT **without a change window and vendor/site approval**.

A successful TCP connection proves only that a listener accepted a connection — not application health or operational safety. The probe's scan levels (passive L0 → active L1 → authenticated L2) are enforced by the collector check-plan and require explicit escalation.

---

## Sources

Research refreshed 2026-07-25. Primary references: [docs/guides/05-research-and-decisions.md](docs/guides/05-research-and-decisions.md).
