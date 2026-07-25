# SENTINEL
### Scalable Edge Network Telemetry and Intelligent Network ELement

> **v1 (current):** A single-host IT/OT network probe — passive capture, active checks, anomaly detection, and a Python/Flask dashboard.  
> **v2 (in design):** A distributed fleet of Go collectors reporting to a multi-service backend (Go ingestion + Python analysis + Go API) with a SvelteKit frontend, VictoriaMetrics time-series storage, PostgreSQL, and an ML-based baseline learning engine. **v2 is not yet implemented.** See [docs/architecture/ARCHITECTURE-V2.md](docs/architecture/ARCHITECTURE-V2.md) for the full design.

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

> **Status:** Design complete. Implementation not started. All v2 design documents are in [`docs/architecture/`](docs/architecture/) and [`docs/ml/`](docs/ml/).

v1 was designed for a single monitoring probe on a bounded network. Three constraints are now broken:

| Constraint | v1 | v2 target |
|---|---|---|
| Scale | 1 collector, local SQLite | 50+ simultaneous collector nodes |
| Service separation | Monolithic Flask process | Independent services with defined API boundaries |
| Language fit | Python for everything | Go for hot-path ingestion/API; Python for analysis/ML; TypeScript/SvelteKit for frontend |

### v2 Service Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     SENTINEL v2 System                      │
│                                                             │
│  Collector tier (Go) ×50+ nodes                             │
│  • Active checks: ICMP / DNS / HTTP / TCP / NTP             │
│  • eBPF passive RTT layer                                    │
│  • WireGuard introspection                                   │
│  • SNMP GET / Modbus FC01/FC03                               │
│  • Gorilla local hot/cold store                              │
│  • MDP adaptive scheduler                                    │
│                │ mTLS + OTLP/gRPC                            │
│                ▼                                             │
│  backend/ingest/   (Go)   — OTLP receiver, writes VM + PG   │
│  backend/analyse/  (Python) — CUSUM/EWMA, PCA, RCA, ML      │
│  backend/api/      (Go/Gin) — REST + WebSocket, JWT auth     │
│                │                                             │
│                ▼                                             │
│  VictoriaMetrics  — time-series (metrics, RTT, loss, scores) │
│  PostgreSQL       — events, anomalies, RCA, config, PKI      │
│                │                                             │
│                ▼                                             │
│  frontend/ (SvelteKit/TypeScript) — static SPA via Nginx     │
│  • Fleet overview, topology map (D3/SVG)                     │
│  • Anomaly + RCA timeline                                    │
│  • ML baseline status and model management                   │
└─────────────────────────────────────────────────────────────┘
```

### v2 Key capabilities

**Fleet scale:** 50+ independent collector nodes connect over mutual TLS (mTLS) with backend-issued PKI leaf certificates. Each collector is a zero-dependency Go static binary that cross-compiles to `linux/arm64`, `linux/amd64`, and `windows/amd64`.

**Time-series storage:** VictoriaMetrics replaces SQLite. Single binary, no external dependencies, Prometheus remote-write compatible, 20–30% lower memory than InfluxDB at equivalent write rate. 50 collectors × 30 metrics × 2 samples/min = ~50 samples/s — well within single-node capacity.

**Structured event storage:** PostgreSQL replaces SQLite for events, anomalies, RCA results, collector registry, check plans, and PKI cert metadata. PostgreSQL `LISTEN/NOTIFY` drives real-time WebSocket push to the SvelteKit frontend without a message broker.

**ML baseline learning:** The `backend/analyse/` service learns normal network behaviour for each collector × metric group during a configurable learning phase (default: 7 days), then raises anomaly scores instead of static threshold breaches. Based on LSTM Autoencoder with ADWIN concept drift detection. See [`docs/ml/ML_BASELINE_LEARNING.md`](docs/ml/ML_BASELINE_LEARNING.md) for the full design.

**SvelteKit frontend:** Replaces the Flask/Jinja2 dashboard. Compiled to a static SPA served by Nginx. Real-time WebSocket feed for anomaly events and collector state. Topology map, anomaly timeline, RCA panel, ML model management view.

**Deployment:** Docker Compose on a single server (NUC or small VM) for the default 50-node case. Scales to VictoriaMetrics cluster + HAProxy for larger deployments without application code changes.

### v2 Design documents

| Document | Contents |
|---|---|
| [`docs/architecture/ARCHITECTURE-V2.md`](docs/architecture/ARCHITECTURE-V2.md) | Full service decomposition, storage decisions, inter-service communication, deployment, migration path from v1 |
| [`docs/ml/ML_BASELINE_LEARNING.md`](docs/ml/ML_BASELINE_LEARNING.md) | ML baseline learning design: LSTM-AE architecture, ADWIN drift detection, data storage strategy, learning phase lifecycle, PostgreSQL schema, SvelteKit ML view |
| [`ROADMAP.md`](ROADMAP.md) | Phased implementation plan with per-phase tracking |

---

## Repository map

```
collector/          Go active-check agent (v1 + v2 collector)
dashboard/          Python/Flask web UI (v1 only)
monitor/            Python monitoring stack (v1 only)
scripts/            Bash install, capture, and operator tools (v1)
config/             Example scope, asset, and target files
docs/
  architecture/     ARCHITECTURE.md (v1), ARCHITECTURE-V2.md (v2 design)
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
