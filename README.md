# SENTINEL
### Scalable Edge Network Telemetry and Intelligent Network ELement

> **This branch (`main`) is the v2 greenfield rewrite — a distributed, multi-site
> IT/OT network-monitoring platform.** It is under active development and is not
> yet operational end-to-end.

---

## What is SENTINEL?

SENTINEL is a **passive-first IT/OT network monitoring system** for environments
where visibility matters and false positives cost operational time. It observes
mirrored traffic from a managed-switch SPAN port or a network TAP and runs active
checks that are deliberately separate, allow-listed, low-rate, and gated behind
explicit escalation. Never connect a probe inline with a control path.

v1 proved the monitoring on a single host. **v2 rebuilds it as a fleet:** many
lightweight collectors → a hub that ingests, analyses, and correlates → a web
frontend, with multi-site federation, HA, and federated ML.

---

## v2 architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                      SENTINEL v2 — Single Site                       │
│                                                                      │
│  collector/ (Python 3.12 asyncio) ×50+ nodes                        │
│  • Active checks: ICMP / DNS / HTTP / TCP / NTP                      │
│  • eBPF passive RTT, Wi-Fi / mtr / bcast-mcast, SNMP, Modbus        │
│  • lmdb hot + sqlite cold local store; MDP adaptive scheduler       │
│  • PKI auto-enroll/renew; graceful degradation over hard failure    │
│           │ mTLS + OTLP/gRPC                                         │
│           ▼                                                          │
│  hub/ingest   (Go)      — OTLP receiver, writes VM + PG             │
│  hub/analyse  (Python)  — CUSUM/EWMA/PCA, RCA DAG, MDP, ML         │
│  hub/api      (Go)      — REST + WebSocket, JWT/RBAC                 │
│  VictoriaMetrics (metrics)   PostgreSQL (events, RCA, PKI, audit)   │
│  frontend/ (SvelteKit static SPA) via Nginx                         │
└──────────────────────────────────────────────────────────────────────┘
           │ federation agent (mTLS, selective forward)
           ▼
   Global tier (optional): cross-site correlation + federated ML (FedAvg)
```

Everything runs under Docker Compose. Target NFRs: collector ≤ 80 MB RSS and
≤ 5 % CPU on a Pi 3B, ≤ 25 MB PyInstaller binary, ≤ 30 s scan cycle.

### Design documents

| Document | Contents |
|---|---|
| [`docs/architecture/ARCHITECTURE-V2-EXTENDED.md`](docs/architecture/ARCHITECTURE-V2-EXTENDED.md) | **Primary v2 design.** Single-site baseline, federation, HA, cross-site correlation, federated ML, OT isolation, RBAC, evidence |
| [`docs/collector/COLLECTOR-V2-REFACTOR.md`](docs/collector/COLLECTOR-V2-REFACTOR.md) | Collector design spec (config schema, check model, transport, PKI) |
| [`docs/guides/OPUS-AGENT-GUIDE-V2.md`](docs/guides/OPUS-AGENT-GUIDE-V2.md) | Phased implementation guide, patterns, NFRs, common mistakes |
| [`docs/collector/ROADMAP.md`](docs/collector/ROADMAP.md) | Phased collector implementation plan |
| [`docs/ml/ML_BASELINE_LEARNING.md`](docs/ml/ML_BASELINE_LEARNING.md) | LSTM-AE baseline learning + ADWIN drift design |

---

## Repository map

```
collector/          v2 Python asyncio collector (in progress)
deploy/             deployment config (.env.example)
docs/
  architecture/     v2 architecture (single-site + multi-site)
  collector/        collector design spec + roadmap
  guides/           implementation guide, research, decisions
  ml/               ML baseline-learning design
  theory/           academic background and references
  gap-analysis/     v1→v2 feature-parity analysis
```

---

## Collector development

The collector targets **Linux, Python 3.12**. Its runtime probes (raw ICMP,
eBPF/bcc, `iw`, scapy) are Linux-only, so develop and test on Linux — not Windows.

```bash
cd collector
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Config resolves in precedence order (highest wins): explicit kwargs → process env
/ `.env` → optional YAML file (`COLLECTOR_CONFIG`) → defaults. See
[`collector/README.md`](collector/README.md).

CI runs ruff, mypy, and pytest on every collector change — see
[`.github/workflows/collector.yml`](.github/workflows/collector.yml).

---

## Important safety boundary

Passive capture is the default. Do not run generic vulnerability scanners,
unauthenticated SNMP sweeps, Nmap version detection, NSE scripts, S7 reads/writes,
OPC UA browsing, fuzzing, or high-rate discovery against production OT **without a
change window and vendor/site approval**. A successful TCP connection proves only
that a listener accepted a connection — not application health or operational
safety. Scan levels (passive L1 → active L2 → authenticated L3) require explicit
escalation.

---

## Sources

Research refreshed 2026-07-25. Primary references:
[docs/guides/05-research-and-decisions.md](docs/guides/05-research-and-decisions.md).
