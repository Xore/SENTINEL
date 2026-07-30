# Claude Opus Agent Guide — analyseLaptop v2 Implementation

> **Audience:** Claude Opus 4.8 (or equivalent capable model) acting as the primary coding agent for this repository.
> **Purpose:** All context, constraints, patterns, and implementation order needed to build and configure the full v2 stack from scratch — no prior conversation history required.
> **Date:** 2026-07-26
> **Status:** Living document — update when design decisions change.

---

## 0. How to Use This Guide

Read sections 1–3 first (context, constraints, repository map). Then follow section 4 (implementation order) strictly — each phase depends on the previous. For each file you create, check section 5 (patterns and conventions) before writing any code. For deployment questions, read section 6. For testing questions, read section 7.

**Never skip a phase.** The dependency chain is intentional: `transport/` depends on `pki/`, `checks/` depends on `transport/`, `scheduler.py` depends on `checks/`. Building out of order creates circular imports and broken mocks.

**Never build the collector without the backend, or the backend without the collector.** Every phase in §4 delivers a working slice of *both* sides simultaneously. The end-to-end integration test at the close of each phase is mandatory — if metrics do not appear in VictoriaMetrics you do not move to the next phase. The SvelteKit frontend is built last, after the full collector + backend stack is verified end-to-end.

**When in doubt, read the source design doc first.** Every design decision is explained in one of the docs listed in section 2. Do not invent architecture — implement what is specified.

---

## 1. Project Context

### 1.1 What This System Does

**analyseLaptop / SENTINEL v2** is a network monitoring and anomaly detection system for OT (operational technology) and IT networks. It consists of:

- A **collector fleet** (50+ nodes, Raspberry Pi / Ubuntu / OT edge devices) running a Python agent that probes the local network and ships metrics via OTLP/gRPC with mTLS to the hub.
- A **backend hub** (single VM) running: ingest (Go), analyse (Python + ML), api (Go), federation-agent (Python), VictoriaMetrics, PostgreSQL, Nginx.
- A **SvelteKit frontend** served as a static bundle by Nginx.

The collector is the primary focus of this guide because it is the most complex component and the one most likely to need active coding work.

### 1.2 Language and Technology Choices — Rationale

| Component | Language | Why |
|---|---|---|
| Collector | Python 3.12 | bcc (eBPF), scapy, pysnmp, pymodbus all have mature Python bindings; single language across the whole stack |
| Ingest | Go | High-throughput gRPC receiver; stateless; performance-critical hot path |
| Analyse | Python | scikit-learn, PyTorch, ADWIN (river library) — ML ecosystem is Python-native |
| API | Go | JSON REST + WebSocket; low-latency; stateless |
| Federation agent | Python | Lightweight scheduler + PostgreSQL + HTTP — Python asyncio is sufficient |
| Frontend | SvelteKit | Static build; no SSR needed; fast to build |

### 1.3 Key Design Principles

1. **Graceful degradation over hard failure.** If eBPF (`bcc`) is unavailable, skip eBPF checks and continue. If Wi-Fi is disabled, skip Wi-Fi checks. If the backend is unreachable, buffer locally up to 24h. Never crash the collector because one optional check fails.
2. **Minimal capabilities.** The collector requests only the Linux capabilities it actually uses. `NET_ADMIN` is added only on Wi-Fi nodes (via `docker-compose.wifi.yml`), never in the base compose.
3. **Secrets are never in environment variables for sensitive values.** Hub uses Docker Compose `secrets:` (file-based). Collector uses `chmod 600` `.env` on the node.
4. **Single language stack.** Do not introduce Go into the collector or Python into the ingest service. If you need a Go library equivalent, find the Python equivalent.
5. **Everything is async.** The collector runs an `asyncio` event loop. All check coroutines must be `async def`. No `time.sleep()` — use `await asyncio.sleep()`.
6. **Pydantic for all config and data models.** No raw dicts passed between modules. Define a `pydantic.BaseModel` for every data structure that crosses a module boundary.

---

## 2. Source Design Documents — Required Reading

All of these are committed to the repository. Read them before implementing the relevant section.

| Document | Path | Read before implementing |
|---|---|---|
| Collector v2 full refactor design | `docs/collector/COLLECTOR-V2-REFACTOR.md` | **Everything in the collector.** This is the primary spec. |
| v2 Architecture (baseline) | `docs/architecture/ARCHITECTURE-V2.md` | Hub services, PostgreSQL schema, API endpoints |
| v2 Architecture (extended) | `docs/architecture/ARCHITECTURE-V2-EXTENDED.md` | Federation, HA, federated ML, RBAC, evidence bundles |
| IaC & Deployment Strategy | `docs/architecture/IaC-DEPLOYMENT-STRATEGY.md` | **All Docker Compose files, GitHub Actions workflows, Wi-Fi override.** |
| Collector Fleet Monitoring | `docs/architecture/COLLECTOR-FLEET-MONITORING.md` | Health score metrics, vmalert rules, fleet ops |
| Research guide | `docs/research-guide-for-gap-topics.md` | Academic basis for ML and broadcast detection |
| Gap analysis | `docs/gap-analysis-collector-vs-standalone.md` | Feature gaps between v1 and v2; migration notes |

> **Critical:** `IaC-DEPLOYMENT-STRATEGY.md` §5.4 documents the Wi-Fi Docker Compose configuration in detail (NET_ADMIN rationale, docker-compose.wifi.yml, iw package, per-node .env, inventory JSON). Always reference it when touching deployment config.

---

## 3. Repository Layout — Files to Create

This is the complete file tree for the collector. Files marked `[EXISTS]` are already committed. Files marked `[CREATE]` need to be written.

```
collector/
├── __main__.py               [CREATE]  Entry point
├── __init__.py               [EXISTS]  Package marker + __version__
├── config.py                 [EXISTS]  pydantic Settings + YAML loader + SIGHUP
├── scheduler.py              [CREATE]  asyncio.TaskGroup-based priority scheduler (see §5.8)
├── requirements.txt          [EXISTS]  pinned deps (see §4.1)
├── requirements-dev.txt      [EXISTS]  pinned dev deps incl. pylint, ruff, mypy, pytest
├── pyproject.toml            [EXISTS]  project metadata + ruff/mypy/pylint config
├── Dockerfile                [CREATE]  multi-stage; iw + iproute2 installed
│
├── transport/
│   ├── __init__.py           [CREATE]
│   ├── otlp.py               [CREATE]  OTLP/gRPC exporter
│   ├── mtls.py               [CREATE]  grpc.ssl_channel_credentials()
│   └── retry.py              [CREATE]  Exponential backoff + lmdb buffer
│
├── pki/
│   ├── __init__.py           [CREATE]
│   ├── enroll.py             [CREATE]  POST /pki/enroll → write cert/key
│   └── renew.py              [CREATE]  Check expiry; auto-renew < 14 days
│
├── checks/
│   ├── __init__.py           [CREATE]  Check registry + base class
│   ├── net_icmp.py           [CREATE]  Raw ICMP; CAP_NET_RAW
│   ├── net_tcp.py            [CREATE]  TCP connect probe
│   ├── net_http.py           [CREATE]  HTTP/HTTPS probe (aiohttp)
│   ├── net_dns.py            [CREATE]  DNS probe (dnspython)
│   ├── net_snmp.py           [CREATE]  SNMP GET/WALK (pysnmp)
│   ├── net_modbus.py         [CREATE]  Modbus TCP passive (pymodbus)
│   ├── net_latency.py        [CREATE]  RTT histogram + jitter
│   ├── net_arp_watch.py      [CREATE]  ARP cache change /proc/net/arp
│   ├── net_mtr.py            [CREATE]  MTR TTL-exceeded tracing
│   ├── net_wifi_linux.py     [CREATE]  iw link + iw scan (Linux)
│   ├── net_wifi_windows.py   [CREATE]  netsh wlan show (Windows)
│   ├── net_bcast.py          [CREATE]  Broadcast/multicast top-talker (scapy)
│   └── ebpf/
│       ├── __init__.py       [CREATE]
│       ├── flow_tracker.py   [CREATE]  bcc eBPF flow tracking
│       └── programs/
│           └── flow_track.c  [CREATE]  BPF C program
│
├── os_health/
│   ├── __init__.py           [CREATE]
│   ├── linux.py              [CREATE]  /proc/ reads
│   ├── windows.py            [CREATE]  psutil / WMI
│   └── processes.py          [CREATE]  systemctl / win32service
│
├── store/
│   ├── __init__.py           [CREATE]
│   ├── hot.py                [CREATE]  lmdb ring buffer (last 30 min)
│   └── cold.py               [CREATE]  sqlite3 WAL historical
│
├── health/
│   ├── __init__.py           [CREATE]
│   └── score.py              [CREATE]  Health score 0–1
│
└── tests/
    ├── __init__.py           [EXISTS]
    ├── conftest.py           [EXISTS]  Env isolation + settings fixture
    └── test_config.py        [EXISTS]  Config schema, layered loader, SIGHUP

deploy/
├── collector/
│   ├── docker-compose.yml         [EXISTS — IaC-DEPLOYMENT-STRATEGY.md §5.2]
│   ├── docker-compose.wifi.yml    [EXISTS — IaC-DEPLOYMENT-STRATEGY.md §5.4]
│   ├── docker-compose.prod.yml    [EXISTS — IaC-DEPLOYMENT-STRATEGY.md §5.3]
│   └── .env.example               [CREATE]
├── hub/
│   ├── docker-compose.yml         [EXISTS — IaC-DEPLOYMENT-STRATEGY.md §4]
│   ├── docker-compose.prod.yml    [EXISTS — IaC-DEPLOYMENT-STRATEGY.md §4]
│   ├── docker-compose.dev.yml     [CREATE]
│   ├── nginx/nginx.conf           [CREATE]
│   ├── postgres/init.sql          [CREATE]
│   └── .env.example               [CREATE]
└── scripts/
    ├── bootstrap-hub.sh           [EXISTS — IaC-DEPLOYMENT-STRATEGY.md §3]
    ├── bootstrap-collector.sh     [EXISTS — IaC-DEPLOYMENT-STRATEGY.md §5.1]
    └── rotate-secrets.sh          [EXISTS — IaC-DEPLOYMENT-STRATEGY.md §4]

deploy/collector-inventory.json    [CREATE]  Wi-Fi-aware node inventory

.github/
├── dependabot.yml            [EXISTS — see §13 for current config]
└── workflows/
    ├── collector.yml         [EXISTS]  ruff + mypy + pytest on collector/**
    ├── pylint.yml            [EXISTS]  pylint on collector package + tests
    ├── codeql.yml            [EXISTS]  CodeQL (continue-on-error — no GHAS)
    └── dependabot-auto-merge.yml  [EXISTS]  auto-merge patch/minor; label major
```

---

## 4. Implementation Order (Phases)

Follow this order strictly. **Each phase builds collector and backend together** — never implement one side without the other. The integration test at the end of each phase is mandatory before proceeding.

The SvelteKit frontend is deferred to Phase 10, after the full collector + backend stack is verified end-to-end.

---

### Phase 1 — Hub Skeleton + Collector Scaffold (Weeks 1–2)

**Goal:** Hub is running locally (ingest + VictoriaMetrics + PostgreSQL). Collector can connect, enroll its certificate, and emit a heartbeat metric that lands in VictoriaMetrics. Both sides are useless without the other — build them together.

#### Hub (backend) files to create first:

1. `deploy/hub/docker-compose.dev.yml` — dev-only compose: ingest + VictoriaMetrics + PostgreSQL + stub PKI endpoint; no resource limits, no Nginx TLS yet
2. `deploy/hub/postgres/init.sql` — schema bootstrap (collectors table, sites table, events table — see `ARCHITECTURE-V2.md`)
3. `deploy/hub/.env.example` — documented env vars with dummy values

#### Collector files to create next (in order):

4. `collector/pyproject.toml` — project metadata, ruff config, mypy config, pylint config
5. `collector/requirements.txt` — pinned deps (see §4.1)
6. `collector/requirements-dev.txt` — dev-only: pyinstaller, pytest, mypy, ruff, pylint
7. `collector/config.py` — `CollectorSettings` pydantic model (see §5.1 for pattern)
8. `collector/pki/enroll.py` — HTTP POST to `/pki/enroll`; write `collector.key` and `collector.crt`
9. `collector/transport/mtls.py` — load cert/key from PKI dir; return `grpc.ssl_channel_credentials()`
10. `collector/transport/otlp.py` — OTLP/gRPC exporter wrapping `opentelemetry-exporter-otlp-proto-grpc`
11. `collector/transport/retry.py` — exponential backoff queue; lmdb buffer on failure
12. `collector/health/score.py` — `CollectorStats` model + `collector_health_score()` function
13. `collector/scheduler.py` — `CheckTask` dataclass + `run_scheduler()` using `asyncio.TaskGroup` (see §5.8)
14. `collector/__main__.py` — wire everything together; emit `collector_heartbeat_total` on each cycle

**Integration test:** `docker compose -f deploy/hub/docker-compose.dev.yml up` then `docker compose -f deploy/collector/docker-compose.yml up` on the same dev machine. Verify `collector_heartbeat_total` appears in VictoriaMetrics at `http://localhost:8428/vmui`. **Do not proceed to Phase 2 until this passes.**

---

### Phase 2 — Core Network Probes + Ingest Validation (Weeks 3–4)

**Goal:** Feature parity with v1 collector for network probes. Backend ingest must accept and store all emitted metrics — verify each new metric in VictoriaMetrics before moving on.

#### Collector files to create (in order):

1. `collector/checks/__init__.py` — `BaseCheck` abstract class (see §5.2)
2. `collector/checks/net_icmp.py` — raw ICMP echo, `CAP_NET_RAW`
3. `collector/checks/net_tcp.py` — TCP connect via `asyncio.open_connection`
4. `collector/checks/net_http.py` — aiohttp GET/HEAD probe; TLS verification configurable
5. `collector/checks/net_dns.py` — dnspython A/AAAA/CNAME resolve probe
6. `collector/checks/net_latency.py` — wraps net_icmp; computes RTT histogram + jitter

#### Backend validation required after each check:

After implementing each check, confirm the metric appears in VictoriaMetrics with correct labels (`collector_id`, `site_id`). If a metric is missing, debug the ingest pipeline before adding the next check.

**Integration test:** `pytest collector/tests/checks/` green + all 6 metrics visible in VictoriaMetrics with live data.

---

### Phase 3 — OS Health + Hub PostgreSQL Write Path (Week 5)

**Goal:** Host metrics flowing end-to-end — collector emits them, ingest writes them to both VictoriaMetrics (time series) and PostgreSQL (collector registry / last-seen table).

#### Collector files to create:

1. `collector/os_health/__init__.py`
2. `collector/os_health/linux.py` — pure `/proc/` reads; zero external deps
3. `collector/os_health/windows.py` — `psutil` + WMI; guarded behind `sys.platform == 'win32'`
4. `collector/os_health/processes.py` — `systemctl show` (Linux) / `win32service` (Windows)

#### Backend work required in parallel:

- Ingest must write `host_cpu_usage_pct`, `host_mem_available_bytes`, `host_disk_free_bytes` to VictoriaMetrics.
- Ingest must upsert the collector's `last_seen` timestamp in the `collectors` PostgreSQL table on every heartbeat.

**Integration test:** Run on a Pi. Verify all three host metrics appear in VictoriaMetrics **and** `SELECT * FROM collectors` in PostgreSQL shows the node's `last_seen` updating.

---

### Phase 4 — Offline Store + Retry Buffer + Hub Reconnect Handling (Week 6)

**Goal:** 24h of metric buffering when the backend is unreachable. Hub ingest must handle replay batches without duplicates.

#### Collector files to create:

1. `collector/store/__init__.py`
2. `collector/store/hot.py` — lmdb ring buffer; last 30 min; LRU eviction by timestamp
3. `collector/store/cold.py` — sqlite3; WAL mode; `PRAGMA journal_mode=WAL`; historical trend
4. Update `collector/transport/retry.py` — write to `hot.py` on send failure; replay on reconnect

#### Backend work required in parallel:

- Ingest must deduplicate replayed OTLP batches by timestamp + collector_id (idempotent write to VictoriaMetrics is fine; PostgreSQL upsert on primary key).
- Ingest must respond `200 OK` to a replayed batch it has already seen (not `409 Conflict`) so the collector does not retry indefinitely.

**Integration test:** Stop the hub; generate 10 min of metrics on the collector; restart the hub; verify all buffered metrics appear in VictoriaMetrics with no duplicates. Check PostgreSQL `last_seen` catches up correctly.

---

### Phase 5 — PKI Auto-Renew + Hub PKI Endpoint + Health Score (Week 7)

**Goal:** Collector certificates renew automatically. Hub PKI endpoint signs renewal CSRs. Health score metric flows end-to-end.

#### Collector files:

1. `collector/pki/renew.py` — check `collector_cert_days_left`; POST `/pki/renew` when < 14 days
2. Update `collector/health/score.py` — incorporate cert expiry penalty into `collector_health_score`

#### Backend work required in parallel:

- Hub PKI service must implement `POST /pki/renew` — validate the existing cert, sign the new CSR, return the new cert.
- Ingest must accept metrics signed with the newly issued cert without requiring a collector restart.

**Integration test:** Set cert expiry to 10 days in test env. Verify collector auto-renews, new cert is used for subsequent OTLP sends, and `collector_cert_days_left` gauge in VictoriaMetrics resets to ~365.

---

### Phase 6 — Wi-Fi Check + Hub Wi-Fi Metrics (Week 8)

**Goal:** Wi-Fi metrics flowing end-to-end on Wi-Fi nodes.

#### Collector files:

1. `collector/checks/net_wifi_linux.py` — `iw dev {iface} link` + `iw dev {iface} scan`
2. `collector/checks/net_wifi_windows.py` — `netsh wlan show interfaces`

#### Backend work required in parallel:

- Ingest must accept and forward `wifi_rssi_dbm`, `wifi_link_speed_mbps`, `wifi_ap_changes_total`, `wifi_scan_aps_visible` to VictoriaMetrics.
- Hub API must expose a `/api/v1/nodes/{collector_id}/wifi` endpoint returning current Wi-Fi state (for the future frontend).

**Deployment note:** Wi-Fi nodes require `docker-compose.wifi.yml`. See `IaC-DEPLOYMENT-STRATEGY.md §5.4` for the complete configuration including `NET_ADMIN`, `WIFI_INTERFACE`, and the inventory `wifi_iface` field.

**Integration test:** On a Wi-Fi Pi, verify `wifi_rssi_dbm` appears in VictoriaMetrics with `bssid` and `ssid` labels. Verify `/api/v1/nodes/{id}/wifi` returns current RSSI.

---

### Phase 7 — Advanced Network Checks + Hub API Endpoints (Weeks 9–12)

**Goal:** Full advanced probe suite. For each check added, the hub API must expose the corresponding read endpoint so the frontend has something to query.

Implement collector checks and their corresponding hub API endpoints together, in this order:

| Week | Collector check | Hub API endpoint to add alongside |
|---|---|---|
| 9 | `net_mtr.py` — TTL-exceeded tracing | `GET /api/v1/nodes/{id}/mtr` |
| 10 | `net_snmp.py` — pysnmp async GET/WALK | `GET /api/v1/nodes/{id}/snmp` |
| 10 | `net_arp_watch.py` — `/proc/net/arp` change detection | `GET /api/v1/nodes/{id}/arp-changes` |
| 11 | `net_modbus.py` — pymodbus TCP passive | `GET /api/v1/nodes/{id}/modbus` |
| 12 | `net_bcast.py` — scapy AsyncSniffer broadcast/multicast | `GET /api/v1/nodes/{id}/broadcast-talkers` |

**Integration test per check:** Metric visible in VictoriaMetrics **and** corresponding API endpoint returns non-empty JSON before moving to the next check.

---

### Phase 8 — eBPF Flow Tracking + Hub Flow Analysis (Weeks 13–14)

#### Collector files:

1. `collector/checks/ebpf/programs/flow_track.c` — BPF C program
2. `collector/checks/ebpf/flow_tracker.py` — bcc Python bindings; `BPF_AVAILABLE` import guard

#### Backend work required in parallel:

- Analyse service must ingest `ebpf_flow_bytes_total` and feed it to the ADWIN anomaly detector (see `ARCHITECTURE-V2-EXTENDED.md §5`).
- Hub API must expose `GET /api/v1/nodes/{id}/flows` with top-N flow aggregation by byte count.

**Note:** `bcc` is NOT installed via pip. It is installed on the host via `apt install python3-bpfcc`. The import guard handles absence gracefully — the collector continues without eBPF if bcc is unavailable.

**Integration test:** On a node with bcc installed, verify `ebpf_flow_bytes_total` appears in VictoriaMetrics with `src_ip`, `dst_ip`, `proto`, `port` labels, and `/api/v1/nodes/{id}/flows` returns the top-N aggregation.

---

### Phase 9 — PyInstaller Build + Docker Images + Full Stack CI (Week 14)

**Goal:** Both collector and hub images build and pass integration tests in CI.

#### Collector files:

1. `collector/Dockerfile` — multi-stage; installs `iw`, `iproute2`, `iputils-ping`; see §5.5
2. Update `collector/pyproject.toml` with PyInstaller build spec

#### Backend / CI work in parallel:

- Verify `build-images.yml` workflow builds **both** collector and hub images and pushes to GHCR.
- Add a `integration-test.yml` workflow that spins up `docker-compose.dev.yml` (hub) + collector, runs a 2-minute smoke test, and asserts `collector_heartbeat_total > 0` in VictoriaMetrics.

**Integration test:** Full CI green on a PR that touches both `collector/**` and `deploy/hub/**`.

---

### Phase 10 — SvelteKit Frontend (Weeks 15–16)

**Goal:** A minimal but functional read-only dashboard over the hub API. Build this only after Phase 9 is complete and the full stack is verified end-to-end.

The frontend is served as a static SvelteKit bundle by Nginx (see `IaC-DEPLOYMENT-STRATEGY.md §4`). It queries the hub API over HTTPS — it has no direct access to VictoriaMetrics or PostgreSQL.

**Minimum viable pages:**

1. `/` — Fleet overview: table of all collectors, last-seen, health score, site
2. `/nodes/{id}` — Node detail: current check results, Wi-Fi state, OS health gauges
3. `/nodes/{id}/flows` — eBPF top-N flow table (if collector supports eBPF)
4. `/alerts` — Active anomaly alerts from the analyse service

**Integration test:** Static bundle served by Nginx (`deploy/hub/nginx/nginx.conf`). All four pages load without errors. API calls use the correct JWT auth headers (RBAC — see `ARCHITECTURE-V2-EXTENDED.md §10.4`).

---

## 5. Patterns and Conventions

### 5.1 Config Pattern — Always Use pydantic

Every config model inherits from `pydantic.BaseModel`. The top-level settings class inherits from `pydantic_settings.BaseSettings` and reads from `.env` + environment variables.

```python
# collector/config.py — canonical pattern
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import Literal
import yaml

class WifiConfig(BaseModel):
    enabled: bool = False              # WIFI_ENABLED env var (via WIFI__ENABLED)
    interface: str = "wlan0"           # WIFI_INTERFACE env var
    scan_interval_s: int = 60
    ap_change_alert: bool = True
    rssi_warn_dbm: int = -75           # Emit warning log when rssi < this threshold

class CollectorSettings(BaseSettings):
    collector_id: str                  # Required — no default
    site_id: str = "default"
    scan_level_max: Literal[1, 2, 3] = 2
    wifi: WifiConfig = WifiConfig()
    # ... other sub-configs ...

    model_config = {
        "env_file": ".env",
        "env_nested_delimiter": "__",  # WIFI__ENABLED=true maps to wifi.enabled
    }
```

**Rule:** `WIFI_ENABLED` in `.env` maps to `CollectorSettings.wifi.enabled` via the `__` delimiter. `WIFI__ENABLED=true` works. Never access `os.environ` directly — always go through `CollectorSettings`.

### 5.2 Check Base Class Pattern

Every check module must implement `BaseCheck`:

```python
# collector/checks/__init__.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from opentelemetry.sdk.metrics import MeterProvider

@dataclass
class CheckResult:
    ok: bool
    metrics: dict[str, float | int]   # metric_name -> value
    labels: dict[str, str]            # label_name -> label_value
    error: str | None = None

class BaseCheck(ABC):
    name: str                          # e.g. "net_icmp"
    scan_level: int                    # 1, 2, or 3 — matches SCAN_LEVEL_MAX gating

    def __init__(self, config: CollectorSettings, meter: MeterProvider):
        self.config = config
        self.meter = meter

    @abstractmethod
    async def run(self) -> CheckResult:
        """
        Execute the check. Must be non-blocking (async). Must not raise —
        catch all exceptions internally and return CheckResult(ok=False, error=str(e)).
        """
        ...

    def is_enabled(self) -> bool:
        """Return False if this check should be skipped on this node."""
        return self.config.scan_level_max >= self.scan_level
```

**Rule:** `run()` must **never raise**. Wrap the entire implementation in `try/except Exception as e: return CheckResult(ok=False, error=str(e))`. The scheduler calls `run()` without a try/except — an unhandled exception in a check would kill the scheduler task.

### 5.3 Graceful Degradation Pattern

Use this pattern for all optional capabilities (eBPF, Wi-Fi, scapy):

```python
# collector/checks/ebpf/flow_tracker.py
try:
    from bcc import BPF
    BPF_AVAILABLE = True
except ImportError:
    BPF = None  # type: ignore[assignment]
    BPF_AVAILABLE = False

import structlog
log = structlog.get_logger()

class FlowTrackerCheck(BaseCheck):
    name = "ebpf_flow_tracker"
    scan_level = 3

    def is_enabled(self) -> bool:
        if not BPF_AVAILABLE:
            log.warning("ebpf.flow_tracker.unavailable",
                        reason="bcc not installed — run: apt install python3-bpfcc")
            return False
        return super().is_enabled()

    async def run(self) -> CheckResult:
        if not BPF_AVAILABLE:
            return CheckResult(ok=False, error="bcc not available")
        try:
            # ... actual eBPF work ...
            return CheckResult(ok=True, metrics={...}, labels={...})
        except Exception as e:
            return CheckResult(ok=False, error=str(e))
```

Apply the same pattern for `scapy` in `net_bcast.py` and `iw` in `net_wifi_linux.py`.

### 5.4 Async Subprocess Pattern

For checks that call external binaries (`iw`, `wg`, `ip`):

```python
# Standard async subprocess call — use this pattern everywhere
import asyncio

async def run_command(cmd: list[str], timeout_s: float = 5.0) -> str:
    """Run a subprocess and return stdout. Raises on non-zero exit or timeout."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Command {cmd[0]} timed out after {timeout_s}s")
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command {cmd} exited {proc.returncode}: {stderr.decode().strip()}"
        )
    return stdout.decode()
```

**Never use `subprocess.run()` or `subprocess.Popen()` in async code** — they block the event loop. Always use `asyncio.create_subprocess_exec()`.

### 5.5 Dockerfile Pattern

```dockerfile
# collector/Dockerfile
FROM python:3.12-slim AS base

# System tools — install unconditionally (iw is tiny; nodes without Wi-Fi never call it)
RUN apt-get update && apt-get install -y --no-install-recommends \
      iw            \
      iproute2      \
      iputils-ping  \
      libcap2-bin   \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Drop to non-root user (capabilities are still granted by compose cap_add)
RUN useradd -r -s /bin/false collector
USER collector

ENTRYPOINT ["python3", "-m", "collector"]
```

**Rule:** `iw` must always be installed regardless of `WIFI_ENABLED`. The `NET_ADMIN` capability controls whether `iw scan` can actually run — the binary just needs to be present in the image.

### 5.6 Structured Logging Pattern

```python
import structlog

log = structlog.get_logger()

# Bind context at module level
log = log.bind(collector_id=settings.collector_id, site_id=settings.site_id)

# Use throughout the module
log.info("check.complete", check="net_icmp", target="8.8.8.8", rtt_ms=12.4)
log.warning("check.degraded", check="net_wifi_linux", reason="iw scan timeout")
log.error("transport.send_failed", error=str(e), retry_in_s=backoff)
```

**Rule:** All log events use snake_case dot-separated names (`check.complete`, `transport.send_failed`). All log entries include `collector_id` and `site_id` bound at startup. No f-string messages — use keyword arguments so logs are structured JSON.

### 5.7 Metric Naming Convention

All metrics use the pattern: `{domain}_{name}_{unit}` where unit is the OpenMetrics standard suffix.

```
# Network probes
icmp_rtt_ms                 # gauge — RTT in milliseconds
tcp_connect_ms              # gauge
http_response_ms            # gauge
dns_resolve_ms              # gauge
wifi_rssi_dbm               # gauge — negative value (e.g. -65.0)
wifi_link_speed_mbps        # gauge
wifi_ap_changes_total       # counter — always _total suffix for counters

# Host
host_cpu_usage_pct          # gauge — 0–100
host_mem_available_bytes    # gauge — always bytes, never MB/GB
host_disk_free_bytes        # gauge
host_uptime_s               # gauge — seconds

# Collector self-metrics
collector_heartbeat_total   # counter
collector_cycle_duration_ms # gauge
collector_cert_days_left    # gauge
collector_health_score      # gauge — 0.0 to 1.0
```

**Rule:** Counters always end in `_total`. Gauges never use `_total`. Memory/disk sizes always in bytes. Times always in milliseconds for probe RTTs; seconds for durations > 60s.

### 5.8 Scheduler Pattern — asyncio.TaskGroup (Python 3.11+)

Use `asyncio.TaskGroup` (PEP 654, stdlib since Python 3.11) instead of raw `asyncio.create_task()` for all concurrent check execution. TaskGroup gives you **structured concurrency**: if any child task raises an unhandled exception, the group cancels all siblings and re-raises as `ExceptionGroup`, making failures visible rather than silently swallowed.

> **Why not trio?** trio's nurseries inspired TaskGroup, but our entire dependency stack
> (grpcio, aiohttp, dnspython, pysnmp, pymodbus) is asyncio-only. TaskGroup gives us the
> same structured-concurrency safety guarantee at zero ecosystem cost.

#### Canonical Scheduler Pattern

```python
# collector/scheduler.py
import asyncio
import time
from dataclasses import dataclass, field
from typing import Sequence

import structlog

from collector.checks import BaseCheck, CheckResult

log = structlog.get_logger()

@dataclass(order=True)
class CheckTask:
    """Priority-queue entry: lower next_run_at = higher urgency."""
    next_run_at: float              # monotonic timestamp
    priority: int                   # tiebreaker: lower = higher priority
    check: BaseCheck = field(compare=False)
    interval_s: float = field(compare=False)


async def _run_one(task: CheckTask) -> CheckResult:
    """Run a single check; all exceptions are caught inside BaseCheck.run()."""
    result = await task.check.run()
    if not result.ok:
        log.warning(
            "scheduler.check_failed",
            check=task.check.name,
            error=result.error,
        )
    return result


async def run_scheduler(
    checks: Sequence[BaseCheck],
    *,
    cycle_s: float = 30.0,
    stop_event: asyncio.Event | None = None,
) -> None:
    """
    Main scheduler loop.

    Each cycle:
      1. Collect all checks whose next_run_at <= now.
      2. Run them concurrently inside a TaskGroup.
      3. Sleep for the remainder of cycle_s.

    Uses asyncio.TaskGroup so that an unexpected exception in any check
    (i.e. a bug that bypasses the BaseCheck.run() try/except) is surfaced
    immediately as an ExceptionGroup rather than silently dropped.
    """
    import heapq

    now = time.monotonic()
    heap: list[CheckTask] = [
        CheckTask(
            next_run_at=now,
            priority=i,
            check=c,
            interval_s=getattr(c, "interval_s", cycle_s),
        )
        for i, c in enumerate(checks)
        if c.is_enabled()
    ]
    heapq.heapify(heap)

    while stop_event is None or not stop_event.is_set():
        cycle_start = time.monotonic()
        due: list[CheckTask] = []

        # Drain all due tasks
        while heap and heap[0].next_run_at <= cycle_start:
            due.append(heapq.heappop(heap))

        if due:
            # --- structured concurrency: all or nothing ---
            async with asyncio.TaskGroup() as tg:
                futures = {
                    task: tg.create_task(_run_one(task), name=task.check.name)
                    for task in due
                }
            # Re-schedule completed tasks
            for task in due:
                task.next_run_at = cycle_start + task.interval_s
                heapq.heappush(heap, task)

        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, cycle_s - elapsed)
        log.debug("scheduler.cycle", checks_run=len(due), elapsed_ms=round(elapsed * 1000, 1))
        await asyncio.sleep(sleep_for)
```

#### Key Rules

- **Always use `asyncio.TaskGroup`** for concurrent check execution — never bare `asyncio.gather()` or `asyncio.create_task()` in the scheduler.
- **`BaseCheck.run()` must never raise** (see §5.2). TaskGroup is a safety net, not the primary error boundary. A bug that escapes `run()` will cancel all sibling checks in that cycle.
- **Per-check `interval_s`** can differ from `cycle_s`. Set `check.interval_s = 60` on expensive checks (SNMP WALK, eBPF flush) and `check.interval_s = 10` on fast checks (ICMP, TCP). The heap scheduler handles mixed intervals correctly.
- **`stop_event`** is an `asyncio.Event` set by the `SIGTERM` handler in `__main__.py` to allow graceful shutdown without `sys.exit()`.
- **Do not use `asyncio.wait_for()` around the TaskGroup** — each individual check is responsible for its own timeout (use `asyncio.wait_for` inside `run()` or in the subprocess helper §5.4).

#### Testing the Scheduler

```python
# tests/test_scheduler.py
import asyncio
import pytest
from unittest.mock import AsyncMock
from collector.checks import BaseCheck, CheckResult
from collector.scheduler import run_scheduler

class FakeCheck(BaseCheck):
    name = "fake"
    scan_level = 1
    interval_s = 1.0

    def __init__(self):
        self.call_count = 0

    def is_enabled(self):
        return True

    async def run(self) -> CheckResult:
        self.call_count += 1
        return CheckResult(ok=True, metrics={}, labels={})


@pytest.mark.asyncio
async def test_scheduler_runs_checks():
    check = FakeCheck()
    stop = asyncio.Event()

    async def stop_after_two_cycles():
        await asyncio.sleep(0.1)  # let one cycle complete
        stop.set()

    await asyncio.gather(
        run_scheduler([check], cycle_s=0.05, stop_event=stop),
        stop_after_two_cycles(),
    )
    assert check.call_count >= 1


@pytest.mark.asyncio
async def test_scheduler_isolates_exception():
    """A check that raises (bypassing BaseCheck contract) causes ExceptionGroup."""
    class BrokenCheck(BaseCheck):
        name = "broken"
        scan_level = 1
        interval_s = 1.0
        def is_enabled(self): return True
        async def run(self) -> CheckResult:
            raise RuntimeError("unexpected")

    stop = asyncio.Event()
    stop.set()  # run exactly one cycle

    with pytest.raises(ExceptionGroup):
        await run_scheduler([BrokenCheck()], cycle_s=0.0, stop_event=stop)
```

---

## 6. Docker Compose and Deployment

### 6.1 Files That Already Exist (Do Not Recreate)

The following Docker Compose files are fully specified in `IaC-DEPLOYMENT-STRATEGY.md` and are considered committed. Do not overwrite them — reference them:

- `deploy/collector/docker-compose.yml` — base collector service (§5.2)
- `deploy/collector/docker-compose.wifi.yml` — Wi-Fi override with `NET_ADMIN` (§5.4)
- `deploy/collector/docker-compose.prod.yml` — resource limits (§5.3)
- `deploy/hub/docker-compose.yml` — full hub stack (§4)
- `deploy/hub/docker-compose.prod.yml` — hub resource limits (§4)
- `deploy/scripts/bootstrap-hub.sh` — hub bootstrap (§3)
- `deploy/scripts/bootstrap-collector.sh` — node bootstrap (§5.1)
- `deploy/scripts/rotate-secrets.sh` — secret rotation (§4)
- `.github/workflows/ci.yml` — CI (§6)
- `.github/workflows/build-images.yml` — build + push (§6)
- `.github/workflows/deploy-hub.yml` — hub deploy (§6)
- `.github/workflows/deploy-collectors.yml` — collector fleet deploy with Wi-Fi awareness (§5.4)

### 6.2 Wi-Fi Node Deployment — The Complete Flow

This is the most common deployment question. The complete flow for a Wi-Fi-capable node:

1. **Bootstrap:** `bash deploy/scripts/bootstrap-collector.sh probe-site-a https://hub:4317 site-a wlan0`
   - Creates `/var/lib/analyselaptop/.env` with `WIFI_ENABLED=true`, `WIFI_INTERFACE=wlan0`

2. **Verify interface name:** On the node, run `iw dev` to confirm the interface name. Common values: `wlan0` (Pi built-in), `wlan1` (USB dongle).

3. **Deploy:** The `deploy-collectors.yml` GitHub Actions workflow reads `wifi_iface` from `deploy/collector-inventory.json`. If non-null, it includes `-f docker-compose.wifi.yml` in the compose command.

4. **Verify capabilities:** On the node after deploy, run:
   ```bash
   docker inspect $(docker compose ps -q collector) | jq '.[0].HostConfig.CapAdd'
   # Should include: "NET_ADMIN" (wifi nodes) or be null/empty (wired nodes)
   ```

5. **Verify Wi-Fi scan works:** `docker exec <container> iw dev wlan0 scan | head -20`
   - If `Operation not permitted`: `NET_ADMIN` was not added — check compose command includes wifi override.
   - If `No such device`: interface name is wrong — update `WIFI_INTERFACE` in `.env`.

### 6.3 The Collector Inventory JSON

Maintain `deploy/collector-inventory.json`. The `deploy-collectors.yml` workflow iterates this file:

```json
[
  { "id": "probe-site-a",    "host": "192.168.1.50", "user": "pi",        "arch": "arm64", "wifi_iface": "wlan0"  },
  { "id": "probe-ot-floor1", "host": "10.10.0.20",   "user": "collector", "arch": "arm64", "wifi_iface": null    }
]
```

- `wifi_iface: null` → wired-only node → `docker-compose.wifi.yml` NOT included → `NET_ADMIN` NOT granted
- `wifi_iface: "wlan0"` → Wi-Fi node → `docker-compose.wifi.yml` included → `NET_ADMIN` granted

### 6.4 Hub Secrets

Hub secrets are never in `.env` or in Git. They live at `/run/analyselaptop/secrets/` on the hub VM. The bootstrap script creates them:

```
/run/analyselaptop/secrets/
  pg_password        # 32-byte base64
  jwt_secret         # 64-byte base64
  pg_db              # database name
  pg_user            # database user
  tls.crt            # TLS certificate for Nginx
  tls.key            # TLS private key
  pki/
    ca.key           # PKI CA private key (used by ingest to sign collector certs)
    ca.crt           # PKI CA certificate
```

Docker Compose mounts these as `secrets:` — they appear inside containers at `/run/secrets/<name>`.

---

## 7. Testing

### 7.1 Test Structure

```
collector/tests/
├── __init__.py              # Package marker (empty)
├── conftest.py              # pytest fixtures: env isolation, settings fixture
├── test_config.py           # pydantic validation, layered loader, SIGHUP reload
├── test_scheduler.py        # TaskGroup isolation, interval accuracy, stop_event [CREATE]
├── checks/
│   ├── test_net_icmp.py     # mock raw socket; verify CheckResult metrics [CREATE]
│   ├── test_net_tcp.py      # mock asyncio.open_connection [CREATE]
│   ├── test_net_http.py     # aiohttp mock [CREATE]
│   ├── test_net_dns.py      # dnspython mock [CREATE]
│   ├── test_net_wifi_linux.py  # mock asyncio.create_subprocess_exec [CREATE]
│   └── test_ebpf.py         # ImportError path; BPF_AVAILABLE=False branch [CREATE]
├── transport/
│   ├── test_otlp.py         # mock gRPC channel; verify metric export [CREATE]
│   └── test_retry.py        # lmdb buffer write/replay on reconnect [CREATE]
├── store/
│   ├── test_hot.py          # lmdb ring buffer eviction [CREATE]
│   └── test_cold.py         # sqlite3 WAL write/read [CREATE]
└── pki/
    ├── test_enroll.py       # mock HTTP POST; verify cert/key written [CREATE]
    └── test_renew.py        # cert < 14 days triggers renewal [CREATE]
```

Tests are added alongside each implementation phase — never write tests that
fake the behaviour of the module under test (no monkeypatching the module's own
functions to force a pass). Every test must exercise real code paths.

### 7.2 Key Test Patterns

**Mock async subprocess for CLI-based checks:**

```python
# tests/checks/test_net_wifi_linux.py
import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from collector.checks.net_wifi_linux import WifiLinuxCheck

@pytest.fixture
def mock_iw_link_output():
    return """
Connected to aa:bb:cc:dd:ee:ff (on wlan0)
        SSID: MyNetwork
        freq: 5180
        RX: 12345 bytes
        TX: 6789 bytes
        signal: -62 dBm
        tx bitrate: 300.0 MBit/s
"""

async def test_wifi_linux_check_ok(mock_settings, mock_meter, mock_iw_link_output):
    check = WifiLinuxCheck(mock_settings, mock_meter)

    async def fake_communicate():
        return mock_iw_link_output.encode(), b""

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = fake_communicate

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await check.run()

    assert result.ok
    assert result.metrics["wifi_rssi_dbm"] == -62.0
    assert result.metrics["wifi_link_speed_mbps"] == 300.0
```

**Test graceful degradation when bcc is missing:**

```python
# tests/checks/test_ebpf.py
import sys
import importlib

def test_bpf_import_failure_graceful(mock_settings, mock_meter):
    with patch.dict(sys.modules, {"bcc": None}):
        if "collector.checks.ebpf.flow_tracker" in sys.modules:
            del sys.modules["collector.checks.ebpf.flow_tracker"]
        import collector.checks.ebpf.flow_tracker as ft

        assert ft.BPF_AVAILABLE is False
        check = ft.FlowTrackerCheck(mock_settings, mock_meter)
        assert check.is_enabled() is False

        result = asyncio.get_event_loop().run_until_complete(check.run())
        assert result.ok is False
        assert "bcc not available" in result.error
```

### 7.3 Running Tests Locally

From the `collector/` directory:

```bash
# Install dev deps
pip install -r requirements-dev.txt

# All checks at once (mirrors CI exactly)
ruff check .          # linting
mypy .                # type-checking
pylint collector tests  # static analysis
pytest -q             # unit tests
```

### 7.4 CI Requirements

The `collector.yml` workflow runs on every push/PR that touches `collector/**`:

```
ruff check .    → must pass (zero errors)
mypy .          → must pass (# type: ignore[import] allowed for bcc/scapy stubs)
pytest -q       → must pass (all tests green; never delete or fake a test to force green)
```

The `pylint.yml` workflow also runs on every push/PR that touches `collector/**`:

```
pylint collector tests  → run from collector/ directory
                           disabled rules: missing-*-docstring, too-few-public-methods,
                           import-error (optional runtime deps), fixme
```

**Fixing CI failures:**
- `ruff` error → fix the lint issue in the source file; never add `# noqa` without a comment
- `mypy` error → add a type annotation or `# type: ignore[specific-code]` with a comment
- `pylint` error → fix the issue in the source; if a rule is genuinely inapplicable project-wide,
  add it to `[tool.pylint."messages control"]` disable list in `pyproject.toml` with a comment
- `pytest` failure → fix the code or fix the test to match the corrected behaviour;
  **never delete or stub out a failing test**

---

## 8. Non-Functional Requirements (Constraints)

These are hard limits from `COLLECTOR-V2-REFACTOR.md §2.2`. Every implementation decision must respect them.

| NFR | Limit | Impact on implementation |
|---|---|---|
| Memory footprint | ≤ 150 MB RSS on the reference Raspberry Pi 5 (4 GB) | No in-memory caching of raw packet data. Scapy top-talker window = 30s max. lmdb buffer size capped at 200 MB. Was ≤ 80 MB on a Pi 3B — see [ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md). |
| CPU usage | ≤ 5% average on the reference Raspberry Pi 5 (4×A76 @ 2.4 GHz) | All checks must be async. No blocking I/O. eBPF is kernel-side (no CPU cost in Python). scapy sniffer uses kernel BPF filter to drop non-matching packets before Python sees them. |
| Binary size | ≤ 25 MB PyInstaller bundle | Do not add heavy dependencies (NumPy, pandas) to the collector. ML is hub-side only. |
| Check cycle | ≤ 30s wall-clock for full scan level 2 | All checks run concurrently via asyncio.TaskGroup. No sequential scan loop. |
| Local buffer | ≤ 200 MB lmdb | Implement LRU eviction in `store/hot.py` when the 200 MB limit is approached. |
| Zero external runtime deps | PyInstaller bundle must be self-contained | All dependencies in `requirements.txt` must be pip-installable and PyInstaller-bundlable. Exception: `bcc` (apt only). |

---

## 9. Capability Reference — What Each Linux Capability Enables

| Capability | Granted by | Used for | What fails without it |
|---|---|---|---|
| `NET_RAW` | base compose | Raw ICMP sockets (`net_icmp.py`, `net_mtr.py`); AF_PACKET (`net_bcast.py` via scapy) | ICMP probe returns `Operation not permitted` |
| `NET_ADMIN` | wifi compose override only | `iw dev scan` nl80211; `iw station dump`; monitor mode setup | `iw scan` returns `Operation not permitted` |
| `BPF` | base compose | Loading eBPF programs via `bcc` (`flow_tracker.py`) | `BPF()` constructor fails with `EPERM` |
| `PERFMON` | base compose | eBPF perf event maps for flow byte counts | eBPF program attaches but perf map read fails |
| `SYS_PTRACE` | base compose | `/proc/<pid>/` reads for process metrics | `open("/proc/1234/status")` returns `EPERM` |

**Rule for adding new capabilities:** Open a PR with an explanation of exactly which syscall/operation requires the capability, which check module uses it, and why it cannot be achieved another way. Do not add capabilities speculatively.

---

## 10. Common Mistakes and How to Avoid Them

| Mistake | Why it is wrong | What to do instead |
|---|---|---|
| Using `time.sleep()` in a check | Blocks the asyncio event loop; all other checks freeze for that duration | `await asyncio.sleep(n)` |
| Raising exceptions from `run()` | The scheduler calls `run()` without try/except; one bad check crashes the scheduler task | Catch all exceptions in `run()`, return `CheckResult(ok=False, error=...)` |
| Using `asyncio.gather()` or bare `create_task()` in the scheduler | Exceptions are silently swallowed unless you inspect each return value manually | Use `asyncio.TaskGroup` (§5.8) — unhandled exceptions surface immediately as ExceptionGroup |
| Accessing `os.environ` directly | Bypasses pydantic validation and default handling; breaks test mocking | Always use `CollectorSettings` |
| Adding `NET_ADMIN` to `docker-compose.yml` (base) | All wired-only nodes get unnecessary kernel privilege | Add only to `docker-compose.wifi.yml` |
| Installing `bcc` via pip in `requirements.txt` | `bcc` is kernel-version-matched; pip installs a generic wheel that may not match the running kernel's headers | Install via `apt install python3-bpfcc` on the node; use import guard in code |
| Using `subprocess.run()` or `subprocess.Popen()` | Blocks the event loop | `await asyncio.create_subprocess_exec()` |
| Hardcoding `wlan0` in `net_wifi_linux.py` | Interface name varies per node | Read from `config.wifi.interface` |
| NumPy/pandas import in the collector | Adds 30–60 MB to the PyInstaller bundle and to cold-start time. The rule stands on the Pi 5 baseline, but on bundle-size and separation-of-concerns grounds — 150 MB of RSS would accommodate them; the architecture still should not ([ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md)) | ML is hub-side only. Collector does arithmetic in stdlib or simple list operations. |
| Committing `.env` with real credentials | Exposes secrets in Git history | `.env` is in `.gitignore`. Only `.env.example` (with dummy values) is committed. |
| Deleting or stubbing out a failing test | Hides real bugs; CI green does not mean working | Fix the code or fix the test to match corrected behaviour |
| Using `git ls-files '*.py'` in pylint from a subdirectory | `git ls-files` returns repo-root-relative paths; running from a subdirectory makes them unresolvable | Run `pylint collector tests` directly from the package directory |

---

## 11. Quick Reference — Metrics Emitted

Full metric list is in `COLLECTOR-V2-REFACTOR.md §10`. This is the subset most likely to be asked about during implementation:

```
# Wi-Fi (net_wifi_linux.py)
wifi_rssi_dbm{collector_id, site_id, interface, bssid, ssid}   gauge
wifi_link_speed_mbps{collector_id, site_id, interface}         gauge
wifi_channel{collector_id, site_id, interface, bssid}          gauge
wifi_ap_changes_total{collector_id, site_id, interface}        counter
wifi_scan_aps_visible{collector_id, site_id, interface}        gauge

# eBPF (flow_tracker.py)
ebpf_flow_bytes_total{collector_id, site_id, src_ip, dst_ip, proto, port}  counter

# Self-monitoring
collector_heartbeat_total{collector_id, site_id}               counter
collector_cert_days_left{collector_id, site_id}                gauge
collector_health_score{collector_id, site_id}                  gauge — 0.0 to 1.0
```

---

## 12. Cross-Reference Index

| Topic | Primary doc | Section |
|---|---|---|
| Wi-Fi Docker Compose (NET_ADMIN, docker-compose.wifi.yml) | `IaC-DEPLOYMENT-STRATEGY.md` | §5.4 |
| Wi-Fi check implementation (iw commands) | `COLLECTOR-V2-REFACTOR.md` | §6.2 (C4 notes) |
| Full collector config schema | `COLLECTOR-V2-REFACTOR.md` | §9 |
| Full metrics list | `COLLECTOR-V2-REFACTOR.md` | §10 |
| PyInstaller build + ARM64 cross-compile | `COLLECTOR-V2-REFACTOR.md` | §11 |
| CI pipeline (pytest + mypy + ruff + pylint) | `COLLECTOR-V2-REFACTOR.md` | §12 |
| Phased implementation plan with weeks | `COLLECTOR-V2-REFACTOR.md` | §13 |
| Hub Docker Compose (full hub stack) | `IaC-DEPLOYMENT-STRATEGY.md` | §4 |
| Collector bootstrap script | `IaC-DEPLOYMENT-STRATEGY.md` | §5.1 |
| GitHub Actions workflows | `IaC-DEPLOYMENT-STRATEGY.md` | §6 |
| Hub secrets (file-based, never env vars) | `IaC-DEPLOYMENT-STRATEGY.md` | §8 |
| Fleet health monitoring + vmalert rules | `COLLECTOR-FLEET-MONITORING.md` | All |
| Multi-site federation architecture | `ARCHITECTURE-V2-EXTENDED.md` | §2 |
| Federated ML (FedAvg, cold-start) | `ARCHITECTURE-V2-EXTENDED.md` | §5 |
| OT-specific alerting rules (IEC 62443) | `ARCHITECTURE-V2-EXTENDED.md` | §7.3 |
| RBAC roles (viewer/operator/analyst) | `ARCHITECTURE-V2-EXTENDED.md` | §10.4 |
| bcc not in requirements.txt (why) | `COLLECTOR-V2-REFACTOR.md` | §8 |
| Linux capabilities table | This document | §9 |
| NFR limits (memory, CPU, binary size) | This document | §8 |
| asyncio.TaskGroup scheduler pattern | This document | §5.8 |
| asyncio optimization (blocking detection, watchdog, uvloop, semaphore, timeouts, thread pool) | `docs/guides/ASYNCIO-OPTIMIZATION.md` | All |

---

## 13. CI & Dependabot Configuration (Current State)

> **Keep this section up to date whenever a workflow or dependabot config is changed.**

### 13.1 Active Workflows

| File | Triggers | What it runs | Must pass? |
|---|---|---|---|
| `collector.yml` | push/PR on `collector/**` | `ruff check .` → `mypy .` → `pytest -q` | Yes — blocks merge |
| `pylint.yml` | push/PR on `collector/**` | `pylint collector tests` (from `collector/` dir) | Yes — blocks merge |
| `codeql.yml` | push/PR on `main`, weekly Sunday | CodeQL Python + Actions scan | No — `continue-on-error: true` (GHAS not enabled) |
| `dependabot-auto-merge.yml` | PR by `dependabot[bot]` | Auto-merge patch/minor; label major with `major-update` + `needs-review` | N/A |

### 13.2 Pylint Configuration

Pylint is configured in `collector/pyproject.toml` under `[tool.pylint.*]`. Key decisions:

| Setting | Value | Reason |
|---|---|---|
| `max-line-length` | 100 | Matches ruff `line-length` |
| `max-args` | 8 | Checks may need up to 8 constructor args |
| `missing-*-docstring` | disabled | Enforced gradually as the codebase matures |
| `too-few-public-methods` | disabled | Pydantic models / dataclasses always trigger this |
| `import-error` | disabled | Optional runtime deps (bcc, scapy) are guarded by try/except; pylint can't resolve them |
| `fixme` | disabled | TODO/FIXME comments are intentional during active development |

**Workflow fix note:** The original `pylint.yml` used `pylint $(git ls-files '*.py')` from
`working-directory: collector`. Because `git ls-files` returns repo-root-relative paths, running
it from a subdirectory caused `FileNotFoundError` for every file outside `collector/`. Fixed to
`pylint collector tests` which resolves correctly relative to the working directory.

### 13.3 Dependabot Config (`.github/dependabot.yml`)

Two ecosystems are monitored:

| Ecosystem | Directory | Schedule | Groups | Major bumps |
|---|---|---|---|---|
| `pip` | `/collector` | Weekly Monday 06:00 CET | `pip-patch-minor`, `pip-security` | Ignored — left for manual review |
| `github-actions` | `/` | Weekly Monday 06:00 CET | `actions-all`, `actions-security` | Allowed (v3→v4→v5 is routine) |

**Removed entries (stale, directories don't exist on main):**
- `gomod /collector` — no Go code in collector; Go is hub-side only
- `pip /monitor`, `pip /dashboard`, `pip /tests` — v1 stack frozen on `release/v1.0`

### 13.4 Dependency Pinning Rules

- All runtime deps in `collector/requirements.txt` are **exact pins** (`==`). No ranges.
- All dev deps in `collector/requirements-dev.txt` are **exact pins** (`==`).
- `pylint` is in `requirements-dev.txt` so both `collector.yml` and `pylint.yml` share one cached install.
- When bumping `pytest` to a new major version, check `pytest-asyncio` compatibility first.
  - `pytest-asyncio < 1.3.0` has a hard `pytest<9` upper bound.
  - `pytest 9.x` requires `pytest-asyncio >= 1.3.0`.
- OTLP stack must be bumped together: `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`, `grpcio`, `grpcio-status` must all be compatible (verify with `pip check` after any bump).

### 13.5 Known Compatibility Constraints

| Constraint | Detail |
|---|---|
| `opentelemetry-sdk==1.25.0` + `grpcio-status==1.64.1` | **UNSATISFIABLE** — proto<5 vs proto>=5.26.1 conflict. Use `opentelemetry-sdk==1.44.0` + `grpcio==1.83.0`. |
| `pytest-asyncio < 1.3.0` | Hard `pytest<9` upper bound. For pytest 9.x, pin `pytest-asyncio>=1.3.0`. |
| `bcc` | NOT in `requirements.txt`. Install via `apt install python3-bpfcc`. Kernel-version-matched. |
