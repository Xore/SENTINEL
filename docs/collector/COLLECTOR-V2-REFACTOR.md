# Collector v2 — Full Refactor Design

> **Language:** Python 3.12  
> **Packaging:** PyInstaller single-file executable (Linux amd64 + arm64, Windows amd64)  
> **Date:** 2026-07-25  
> **Status:** Design / Approved  
> **Supersedes:** v1 collector (Go, single binary, no bundled host metrics)  

---

## 1. Why Python for the v2 Collector?

The v2 collector is a **probe agent** running on Raspberry Pi nodes, OT edge devices, and laptops. The backend services (`ingest`, `analyse`, `api`, federation agent) already use Python for ML/analysis work. Unifying the entire stack on Python eliminates the Go toolchain from the project entirely:

| Criterion | Go (v1) | Python (v2) |
|---|---|---|
| Language consistency | Go collector + Python backend = two toolchains | Single language across all components |
| eBPF integration | `cilium/ebpf` — CGO-free but complex | `bcc` Python bindings — well-documented, widely used |
| Packet capture | `gopacket/afpacket` — requires kernel AF_PACKET | `scapy.AsyncSniffer` — same kernel interface, pure Python |
| SNMP | `gosnmp` | `pysnmp` / `easysnmp` |
| Modbus | `go-modbus` | `pymodbus` — mature, OT-standard |
| OTLP export | `go.opentelemetry.io/otel` | `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-grpc` |
| mTLS | `crypto/tls` | `grpc.ssl_channel_credentials()` + `ssl` stdlib |
| Packaging | `go build` static binary | PyInstaller `--onefile` (~18–22 MB) |
| ARM cross-compile | `GOOS=linux GOARCH=arm64 go build` | `pyinstaller --target-arch arm64` via Docker buildx |
| CI build time | ~40 s | ~90 s (PyInstaller slower but acceptable) |
| Async concurrency | goroutines | `asyncio` task loop |
| Hot/cold store | custom Gorilla ring buffer | `lmdb` (fast) or `sqlite3` (stdlib fallback) |
| PKI / cert handling | `crypto/x509` | `cryptography` library |
| Config validation | custom struct tags | `pydantic` v2 |

**Decision:** Python 3.12 throughout. The federation agent (previously a Go binary on the site server) is also Python, completing the single-language stack.

---

## 2. Requirements

### 2.1 Functional Requirements

| ID | Requirement |
|---|---|
| FR-01 | Probe all v1 check types: ICMP ping, TCP connect, HTTP/HTTPS, DNS, SNMP |
| FR-02 | Add v2 check types: MTR hop-tracing, Wi-Fi health, broadcast/multicast top-talker |
| FR-03 | Bundle host metrics: CPU, memory, disk, network interfaces, systemd unit state |
| FR-04 | Export all metrics via OTLP/gRPC with mTLS to the ingest service |
| FR-05 | Self-manage PKI leaf cert: auto-enroll, auto-renew when <14 days remaining |
| FR-06 | Offline resilience: buffer up to 24 h of metrics locally when backend unreachable |
| FR-07 | Graceful degradation: if eBPF unavailable (no CAP_BPF), skip eBPF checks and log warning |
| FR-08 | Multi-platform: Linux amd64, Linux arm64 (Raspberry Pi), Windows amd64 |
| FR-09 | Configurable via YAML with `pydantic` validation; hot-reload on SIGHUP |
| FR-10 | Structured logging (JSON) to stdout; log level configurable |

### 2.2 Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | Memory footprint ≤ 80 MB RSS on Raspberry Pi 3B (1 GB RAM) |
| NFR-02 | CPU usage ≤ 5% average on Pi 3B (4-core ARM Cortex-A53 @ 1.2 GHz) |
| NFR-03 | PyInstaller binary size ≤ 25 MB |
| NFR-04 | Check cycle ≤ 30 s wall-clock for full scan level 2 workload |
| NFR-05 | Local buffer (lmdb) ≤ 200 MB on disk |
| NFR-06 | Zero external runtime dependencies beyond the PyInstaller bundle |
| NFR-07 | CAP_NET_RAW sufficient for ICMP, AF_PACKET; CAP_BPF + CAP_PERFMON for eBPF checks |

---

## 3. Python Package Structure

```
collector/
├── __main__.py                  # Entry point: asyncio.run(main())
├── config.py                    # pydantic Settings model; YAML loader; SIGHUP hot-reload
├── scheduler.py                 # asyncio task loop: MDP-style priority queue of check coroutines
├── transport/
│   ├── __init__.py
│   ├── otlp.py                  # OTLP/gRPC exporter (opentelemetry-exporter-otlp-proto-grpc)
│   ├── mtls.py                  # grpc.ssl_channel_credentials() + cert/key loading
│   └── retry.py                 # Exponential backoff retry queue; local lmdb buffer on failure
├── pki/
│   ├── __init__.py
│   ├── enroll.py                # POST /pki/enroll → write collector.key + collector.crt
│   └── renew.py                 # Check expiry; auto-renew when days_remaining < 14
├── checks/
│   ├── __init__.py
│   ├── net_icmp.py              # Raw ICMP echo (socket.SOCK_RAW); requires CAP_NET_RAW
│   ├── net_tcp.py               # TCP connect probe (asyncio.open_connection)
│   ├── net_http.py              # HTTP/HTTPS probe (aiohttp)
│   ├── net_dns.py               # DNS resolution probe (dnspython asyncio)
│   ├── net_snmp.py              # SNMP GET/WALK (pysnmp asyncio)
│   ├── net_modbus.py            # Modbus TCP passive check (pymodbus) — Linux only
│   ├── net_latency.py           # RTT histogram + jitter (wraps net_icmp)
│   ├── net_arp_watch.py         # ARP cache change detection (/proc/net/arp)
│   ├── net_mtr.py               # MTR-style hop tracing: raw ICMP TTL-exceeded; CAP_NET_RAW
│   ├── net_wifi_linux.py        # iw link + iw scan; AP change detection — Linux only
│   ├── net_wifi_windows.py      # netsh wlan show interfaces — Windows only
│   ├── net_bcast.py             # Broadcast/multicast top-talker: scapy.AsyncSniffer; CAP_NET_RAW
│   ├── net_wireguard.py         # WireGuard: subprocess wg show + parse
│   └── ebpf/
│       ├── __init__.py
│       ├── flow_tracker.py      # eBPF flow tracking via bcc Python bindings — Linux only
│       └── programs/
│           └── flow_track.c     # BPF C program loaded by bcc
├── os_health/
│   ├── __init__.py
│   ├── linux.py                 # /proc/stat, /proc/meminfo, /proc/net/dev, /proc/uptime, syscall statvfs
│   ├── windows.py               # psutil / WMI (Windows)
│   └── processes.py             # systemctl show (Linux) / win32service (Windows)
├── store/
│   ├── __init__.py
│   ├── hot.py                   # lmdb ring buffer: last 30 min of metric samples
│   └── cold.py                  # sqlite3: historical samples for local trend; WAL mode
└── health/
    ├── __init__.py
    └── score.py                 # Collector health score (0–1): heartbeat gap, cycle overrun, cert expiry, eBPF state
```

---

## 4. Dependencies (`requirements.txt`)

```
# OTLP export
opentelemetry-sdk==1.44.0
opentelemetry-exporter-otlp-proto-grpc==1.44.0
grpcio==1.83.0
grpcio-status==1.83.0

# Config validation
pydantic==2.7.4
pydantic-settings==2.3.4

# HTTP probing
aiohttp==3.9.5

# DNS probing
dnspython==2.6.1

# SNMP
pysnmp==6.2.5

# Modbus (OT)
pymodbus==3.6.9

# Packet capture (broadcast/multicast top-talker)
scapy==2.5.0

# eBPF (Linux only — installed conditionally in CI and on-node)
# bcc is NOT pip-installable; installed via OS package manager:
#   apt install python3-bpfcc  OR  pip install bcc (kernel-version-matched)
# Import guard in flow_tracker.py: try: from bcc import BPF except ImportError: BPF = None

# PKI / TLS
cryptography==42.0.8

# Local store
lmdb==1.4.7

# Logging
structlog==24.2.0

# Build (dev/CI only — not bundled)
pyinstaller==6.8.0
```

---

## 5. Async Task Loop (`scheduler.py`)

Replaces the Go goroutine pool and MDP-style priority scheduler:

```python
# collector/scheduler.py
import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Coroutine

@dataclass(order=True)
class CheckTask:
    next_run: float
    interval_s: float = field(compare=False)
    coro_fn: Callable[[], Coroutine] = field(compare=False)
    name: str = field(compare=False)

async def run_scheduler(tasks: list[CheckTask]) -> None:
    import heapq
    heap = list(tasks)
    heapq.heapify(heap)
    while True:
        now = time.monotonic()
        task = heap[0]
        if task.next_run > now:
            await asyncio.sleep(task.next_run - now)
            continue
        heapq.heappop(heap)
        asyncio.create_task(task.coro_fn(), name=task.name)
        task.next_run = now + task.interval_s
        heapq.heappush(heap, task)
```

---

## 6. Check Inventory

### 6.1 v2 Check Table

| Phase | Module | Capability required | Linux | Windows | Scan level |
|---|---|---|---|---|---|
| C1 | `net_icmp.py` | CAP_NET_RAW | ✅ | ✅ | 1 |
| C2 | `net_tcp.py` | none | ✅ | ✅ | 1 |
| C3 | `net_http.py` | none | ✅ | ✅ | 1 |
| C4 | `net_wifi_linux.py` | none (iw) | ✅ | — | 2 |
| C4w | `net_wifi_windows.py` | none (netsh) | — | ✅ | 2 |
| C5 | `net_dns.py` | none | ✅ | ✅ | 1 |
| C6 | `net_mtr.py` | CAP_NET_RAW | ✅ | — | 2 |
| C7 | `net_latency.py` | CAP_NET_RAW | ✅ | ✅ | 1 |
| C8 | `net_snmp.py` | none | ✅ | ✅ | 2 |
| C9 | `net_arp_watch.py` | none | ✅ | — | 1 |
| C10 | `net_modbus.py` | none | ✅ | — | 2 |
| C11 | `net_bcast.py` | CAP_NET_RAW | ✅ | — | 2 |
| C12 | `net_wireguard.py` | none (subprocess) | ✅ | — | 2 |
| C13 | `ebpf/flow_tracker.py` | CAP_BPF + CAP_PERFMON | ✅ | — | 3 |
| C14 | `os_health/linux.py` | none | ✅ | — | 1 |
| C14w | `os_health/windows.py` | none | — | ✅ | 1 |
| C15 | `os_health/processes.py` | none | ✅ | ✅ | 1 |

### 6.2 Key Implementation Notes

**net_icmp.py** — raw `socket.SOCK_RAW, socket.IPPROTO_ICMP`; asyncio-compatible via `loop.sock_recv`.

**net_mtr.py** — TTL-exceeded tracing: send ICMP Echo with TTL=1..N, collect ICMP Time Exceeded replies. Same approach as the Linux `mtr` tool. No external binary needed.

**net_bcast.py** — `scapy.AsyncSniffer` with BPF filter `ether broadcast or ether multicast`; 30 s window; top-10 by byte count. Requires `CAP_NET_RAW`. Graceful skip if scapy import fails.

**net_wifi_linux.py** — `subprocess(['iw', 'dev', iface, 'link'])` + `subprocess(['iw', 'dev', iface, 'scan'])`. No kernel privilege needed beyond normal user on most distros (iw scan may need `CAP_NET_ADMIN` or be run as root).

**ebpf/flow_tracker.py** — `bcc` is installed via OS package manager, not pip. Import guard:
```python
try:
    from bcc import BPF
    BPF_AVAILABLE = True
except ImportError:
    BPF_AVAILABLE = False  # graceful degradation: log warning, skip eBPF checks
```

**os_health/linux.py** — pure `/proc/` reads; zero external dependencies beyond Python stdlib.

---

## 7. File Tree (source layout)

```
collector/
├── __main__.py
├── config.py
├── scheduler.py
├── requirements.txt             ← dependency manifest
├── requirements-dev.txt         ← pyinstaller, pytest, mypy, ruff
├── pyproject.toml               ← project metadata, ruff/mypy config
├── transport/
│   ├── otlp.py
│   ├── mtls.py
│   └── retry.py
├── pki/
│   ├── enroll.py
│   └── renew.py
├── checks/
│   ├── net_icmp.py
│   ├── net_tcp.py
│   ├── net_http.py
│   ├── net_dns.py
│   ├── net_snmp.py
│   ├── net_modbus.py
│   ├── net_latency.py
│   ├── net_arp_watch.py
│   ├── net_mtr.py
│   ├── net_wifi_linux.py
│   ├── net_wifi_windows.py
│   ├── net_bcast.py
│   ├── net_wireguard.py
│   └── ebpf/
│       ├── flow_tracker.py
│       └── programs/
│           └── flow_track.c
├── os_health/
│   ├── linux.py
│   ├── windows.py
│   └── processes.py
├── store/
│   ├── hot.py
│   └── cold.py
└── health/
    └── score.py
```

---

## 8. `requirements.txt` (canonical)

See Section 4. The `bcc` package is NOT in `requirements.txt` — it is installed via the OS package manager on nodes that need eBPF:

```bash
# On Debian/Ubuntu/Raspberry Pi OS:
sudo apt install -y python3-bpfcc
# On RHEL/Rocky:
sudo dnf install -y python3-bcc
```

All other dependencies are bundled by PyInstaller into the single-file executable.

---

## 9. Config Schema (`config.py`)

```python
# collector/config.py
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import Literal

class BackendConfig(BaseModel):
    url: str = "https://hub.internal:4317"
    pki_dir: str = "/var/lib/analyselaptop/pki"
    retry_max: int = 10
    retry_backoff_s: float = 2.0

class WifiConfig(BaseModel):
    enabled: bool = True
    interface: str = "wlan0"
    scan_interval_s: int = 60
    ap_change_alert: bool = True

class MtrConfig(BaseModel):
    enabled: bool = True
    targets: list[str] = []
    max_hops: int = 30
    probes_per_hop: int = 3
    interval_s: int = 300

class BcastMcastConfig(BaseModel):
    enabled: bool = True
    interface: str = "eth0"
    window_s: int = 30
    top_n: int = 10
    interval_s: int = 300

class EbpfConfig(BaseModel):
    enabled: bool = True  # auto-disabled if bcc import fails
    flow_track: bool = True

class CollectorSettings(BaseSettings):
    collector_id: str
    site_id: str = "default"
    scan_level_max: Literal[1, 2, 3] = 2
    backend: BackendConfig = BackendConfig()
    wifi: WifiConfig = WifiConfig()
    mtr: MtrConfig = MtrConfig()
    bcast_mcast: BcastMcastConfig = BcastMcastConfig()
    ebpf: EbpfConfig = EbpfConfig()
    log_level: str = "INFO"
    data_dir: str = "/var/lib/analyselaptop/data"

    model_config = {"env_file": ".env", "env_nested_delimiter": "__"}
```

---

## 10. Metrics Emitted

### Network probes

```
icmp_rtt_ms{collector_id, site_id, target}                     gauge
icmp_loss_pct{collector_id, site_id, target}                   gauge
tcp_connect_ms{collector_id, site_id, target, port}            gauge
http_response_ms{collector_id, site_id, target, status_code}   gauge
dns_resolve_ms{collector_id, site_id, target, record_type}     gauge
snmp_poll_ms{collector_id, site_id, target, oid}               gauge
arp_table_size{collector_id, site_id}                          gauge
arp_new_entry_total{collector_id, site_id}                     counter
mtr_hop_rtt_ms{collector_id, site_id, target, hop, hop_ip}     gauge
mtr_hop_loss_pct{collector_id, site_id, target, hop, hop_ip}   gauge
wifi_rssi_dbm{collector_id, site_id, interface, bssid}         gauge
wifi_link_speed_mbps{collector_id, site_id, interface}         gauge
wifi_ap_changes_total{collector_id, site_id, interface}        counter
bcast_top_talker_bytes_total{collector_id, site_id, iface, src_mac, src_ip, proto}  counter
bcast_top_talker_pkts_total{collector_id, site_id, iface, src_mac, src_ip, proto}   counter
bcast_segment_rate_pps{collector_id, site_id, iface}           gauge
wg_peer_handshake_age_s{collector_id, site_id, peer}           gauge
wg_peer_rx_bytes_total{collector_id, site_id, peer}            counter
ebpf_flow_bytes_total{collector_id, site_id, src_ip, dst_ip, proto, port}  counter
```

### Host metrics

```
host_cpu_usage_pct{collector_id, site_id}                      gauge
host_load1{collector_id, site_id}                              gauge
host_mem_available_bytes{collector_id, site_id}                gauge
host_mem_total_bytes{collector_id, site_id}                    gauge
host_disk_free_bytes{collector_id, site_id, mountpoint}        gauge
host_uptime_s{collector_id, site_id}                           gauge
host_net_rx_bytes_total{collector_id, site_id, interface}      counter
host_net_tx_bytes_total{collector_id, site_id, interface}      counter
host_systemd_unit_active{collector_id, site_id, unit}          gauge
host_systemd_restart_count_30m{collector_id, site_id, unit}    gauge
collector_heartbeat_total{collector_id, site_id}               counter
collector_cycle_duration_ms{collector_id, site_id}             gauge
collector_cert_days_left{collector_id, site_id}                gauge
collector_health_score{collector_id, site_id}                  gauge
```

---

## 11. PyInstaller Build

### Single-file executable

```bash
# Linux amd64 (native)
pyinstaller \
  --onefile \
  --name analyselaptop-collector \
  --add-data "checks/ebpf/programs:checks/ebpf/programs" \
  collector/__main__.py

# Output: dist/analyselaptop-collector  (~18-22 MB)
```

### Cross-compile for ARM64 (Raspberry Pi)

PyInstaller does not support true cross-compilation. Use Docker buildx with a native ARM64 emulation layer:

```dockerfile
# Dockerfile.collector-arm64
FROM python:3.12-slim AS builder
RUN apt-get update && apt-get install -y binutils
COPY collector/ /src/collector/
WORKDIR /src/collector
RUN pip install -r requirements.txt -r requirements-dev.txt
RUN pyinstaller --onefile --name analyselaptop-collector collector/__main__.py

FROM scratch
COPY --from=builder /src/collector/dist/analyselaptop-collector /analyselaptop-collector
```

```bash
# Build for arm64 on amd64 host via QEMU
docker buildx build \
  --platform linux/arm64 \
  -f Dockerfile.collector-arm64 \
  --output type=local,dest=collector/dist/arm64 \
  .
```

### bcc exclusion from bundle

`bcc` is NOT bundled by PyInstaller — it is a kernel-version-matched package that must be installed on the target node. The import guard in `flow_tracker.py` handles absence gracefully.

---

## 12. CI Pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml — collector job
test-collector:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: '3.12' }
    - run: pip install -r collector/requirements.txt -r collector/requirements-dev.txt
    - run: pytest collector/tests/ -v --tb=short
    - run: mypy collector/ --ignore-missing-imports
    - run: ruff check collector/

build-collector:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: '3.12' }
    - run: pip install -r collector/requirements.txt pyinstaller
    - name: Build Linux amd64 binary
      run: |
        cd collector
        pyinstaller --onefile --name analyselaptop-collector-linux-amd64 __main__.py
    - name: Build Linux arm64 binary (via Docker buildx)
      uses: docker/setup-buildx-action@v3
    - run: |
        docker buildx build \
          --platform linux/arm64 \
          -f Dockerfile.collector-arm64 \
          --output type=local,dest=collector/dist/arm64 .
    - uses: actions/upload-artifact@v4
      with:
        name: collector-binaries
        path: collector/dist/
        retention-days: 30
```

---

## 13. Phased Implementation Plan

| Phase | Deliverable | Weeks | Notes |
|---|---|---|---|
| P1 | Project scaffold: `pyproject.toml`, `config.py`, `scheduler.py`, `transport/otlp.py`, `transport/mtls.py`, `pki/enroll.py` | 1–2 | Replaces Go bootstrap |
| P2 | Core probes: `net_icmp.py`, `net_tcp.py`, `net_http.py`, `net_dns.py`, `net_latency.py` | 3–4 | Feature parity with v1 |
| P3 | OS health: `os_health/linux.py`, `os_health/windows.py`, `os_health/processes.py` | 5 | No deps beyond stdlib |
| P4 | Store + retry: `store/hot.py` (lmdb), `store/cold.py` (sqlite3), `transport/retry.py` | 6 | Replaces Gorilla ring buffer |
| P5 | PKI auto-renew: `pki/renew.py`; health score: `health/score.py` | 7 | |
| C4 | Wi-Fi health: `net_wifi_linux.py`, `net_wifi_windows.py` | 8 | |
| C6 | MTR hop-tracing: `net_mtr.py` | 9 | |
| C8 | SNMP: `net_snmp.py` (pysnmp) | 10 | |
| C9 | ARP watch: `net_arp_watch.py` | 10 | |
| C10 | Modbus passive: `net_modbus.py` (pymodbus) | 11 | |
| C11 | Broadcast/multicast top-talker: `net_bcast.py` (scapy) | 12 | Research: RESEARCH-BCAST-MCAST.md |
| C12 | WireGuard monitoring: `net_wireguard.py` | 12 | |
| C13 | eBPF flow tracking: `ebpf/flow_tracker.py` (bcc) | 13–14 | Linux only; bcc via apt |
| B1 | PyInstaller build pipeline + Dockerfile.collector-arm64 | 14 | |
| B2 | CI: pytest + mypy + ruff + pyinstaller artifact upload | 14 | |
| M1–M5 | Migration from v1: parallel run, cutover, decommission | 15–25 | See Section 15 |

**Total: ~25 weeks** (same as original Go timeline; Python build is slower but parallelisable).

---

## 14. Academic & Technical References

| Reference | What it grounds |
|---|---|
| OpenTelemetry Python SDK (opentelemetry.io) | OTLP/gRPC export; `opentelemetry-exporter-otlp-proto-grpc` |
| scapy documentation (scapy.net) | `AsyncSniffer` for broadcast/multicast capture (C11) |
| bcc Python reference (github.com/iovisor/bcc) | Python eBPF bindings for flow tracking (C13) |
| pymodbus documentation (pymodbus.readthedocs.io) | Modbus TCP passive monitoring (C10) |
| pysnmp documentation (pysnmp.com) | SNMP v2c/v3 GET/WALK (C8) |
| cryptography library (cryptography.io) | X.509 PKI cert handling; mTLS credential loading |
| pydantic v2 (docs.pydantic.dev) | Config validation; zero-cost model serialisation |
| PyInstaller manual (pyinstaller.org) | Single-file bundle; `--onefile`; exclusion of OS-matched packages |
| TU Munich (Brügge & Simon, NET-2024-04-1) | Broadcast storm as wireless OT congestion cause (C11) |
| RITICS/NCSC ICS-COI 2024, Appendix A | Broadcast storm as OT IoC (C11) |
| 802.11k/v (IEEE 2008) | Roaming event detection via Wi-Fi health (C4) |

---

## 15. Migration Plan (v1 → v2)

| Phase | Action |
|---|---|
| M1 | Deploy v2 Python collector alongside v1 on a test node; verify OTLP metrics reach ingest |
| M2 | Parallel run on 5 nodes: compare v1 vs v2 metrics; validate feature parity |
| M3 | Roll out v2 to 50% of fleet (Ansible `--serial 25`) |
| M4 | Roll out v2 to remaining 50% |
| M5 | Decommission v1; remove legacy Ansible tasks; remove `node_exporter` from all nodes |

During M1–M4, the v1 and v2 collectors run on separate systemd units (`analyselaptop-collector-v1.service` and `analyselaptop-collector-v2.service`). The ingest service accepts both by collector_id prefix.
