# Collector v2 — Roadmap

> **Language:** Python 3.12 (PyInstaller single-file binary)  
> **Updated:** 2026-07-25 — Language changed from Go to Python. go.mod replaced with requirements.txt.

See [`COLLECTOR-V2-REFACTOR.md`](COLLECTOR-V2-REFACTOR.md) for the full implementation design and phased plan.

---

## Phase 1 — Core Bootstrap (Weeks 1–2)

**Goal:** Minimal working Python collector: config, async loop, OTLP export, mTLS.

### Deliverables
- `collector/pyproject.toml` — project metadata, ruff/mypy config
- `collector/requirements.txt` — runtime deps
- `collector/requirements-dev.txt` — pytest, mypy, ruff, pyinstaller
- `collector/__main__.py` — `asyncio.run(main())`
- `collector/config.py` — `pydantic` Settings; YAML loader; SIGHUP hot-reload
- `collector/scheduler.py` — asyncio priority-queue task loop
- `collector/transport/otlp.py` — OTLP/gRPC exporter
- `collector/transport/mtls.py` — `grpc.ssl_channel_credentials()` + cert loading
- `collector/pki/enroll.py` — PKI enrollment: POST /pki/enroll, write collector.key + collector.crt

### `requirements.txt` (at Phase 1)
```
opentelemetry-sdk==1.25.0
opentelemetry-exporter-otlp-proto-grpc==1.25.0
grpcio==1.64.1
grpcio-status==1.64.1
pydantic==2.7.4
pydantic-settings==2.3.4
structlog==24.2.0
cryptography==42.0.8
```

---

## Phase 2 — Core Probes (Weeks 3–4)

**Goal:** Core network probes.

### Deliverables
- `checks/net_icmp.py` — raw `socket.SOCK_RAW` ICMP echo; asyncio-safe
- `checks/net_tcp.py` — `asyncio.open_connection` TCP connect probe
- `checks/net_http.py` — `aiohttp` HTTP/HTTPS probe with TLS validation
- `checks/net_dns.py` — `dnspython` asyncio DNS resolution
- `checks/net_latency.py` — RTT histogram + jitter (wraps net_icmp)

### `requirements.txt` additions
```
aiohttp==3.9.5
dnspython==2.6.1
```

---

## Phase 3 — OS Health (Week 5)

**Goal:** Bundle all host metrics natively. No `node_exporter` dependency.

### Deliverables
- `os_health/linux.py` — `/proc/stat`, `/proc/meminfo`, `/proc/net/dev`, `/proc/uptime`, `os.statvfs`
- `os_health/windows.py` — `psutil` / WMI for Windows host metrics
- `os_health/processes.py` — `subprocess(['systemctl', 'show', ...])` for Linux; `win32service` for Windows

### `requirements.txt` additions
```
psutil==5.9.8   # Windows host metrics fallback
```

---

## Phase 4 — Store & Retry (Week 6)

**Goal:** 24 h offline resilience.

### Deliverables
- `store/hot.py` — `lmdb` ring buffer: last 30 min of metric samples
- `store/cold.py` — `sqlite3` (stdlib): historical samples, WAL mode
- `transport/retry.py` — exponential backoff queue; spills to lmdb on backend unreachable

### `requirements.txt` additions
```
lmdb==1.4.7
```

---

## Phase 5 — PKI Auto-renew + Health Score (Week 7)

### Deliverables
- `pki/renew.py` — check cert expiry; auto-renew when `days_remaining < 14`
- `health/score.py` — `collector_health_score` (0–1): heartbeat gap, cycle overrun, metric gaps, cert expiry, eBPF state

---

## Phase C4 — Wi-Fi Health (Week 8)

### Deliverables
- `checks/net_wifi_linux.py` — `subprocess(['iw', 'dev', iface, 'link'])` + scan; AP change detection
- `checks/net_wifi_windows.py` — `subprocess(['netsh', 'wlan', 'show', 'interfaces'])`

### Metrics added
```
wifi_rssi_dbm, wifi_link_speed_mbps, wifi_ap_changes_total
```

---

## Phase C6 — MTR Hop-Tracing (Week 9)

### Deliverables
- `checks/net_mtr.py` — raw ICMP TTL-exceeded tracing; no external binary; `CAP_NET_RAW`

### Metrics added
```
mtr_hop_rtt_ms{hop, hop_ip}, mtr_hop_loss_pct{hop, hop_ip}
```

---

## Phase C8 — SNMP (Week 10)

### Deliverables
- `checks/net_snmp.py` — `pysnmp` asyncio SNMP v2c/v3 GET/WALK

### `requirements.txt` additions
```
pysnmp==6.2.5
```

---

## Phase C9 — ARP Watch (Week 10)

### Deliverables
- `checks/net_arp_watch.py` — `/proc/net/arp` polling; new-entry detection

---

## Phase C10 — Modbus Passive (Week 11)

### Deliverables
- `checks/net_modbus.py` — `pymodbus` TCP passive monitoring (Linux only)

### `requirements.txt` additions
```
pymodbus==3.6.9
```

---

## Phase C11 — Broadcast/Multicast Top-Talker (Week 12)

Research task: [`../tasks/RESEARCH-BCAST-MCAST-GOPACKET.md`](../tasks/RESEARCH-BCAST-MCAST-GOPACKET.md) (note: research doc predates Python decision; scapy replaces gopacket).

### Deliverables
- `checks/net_bcast.py` — `scapy.AsyncSniffer`; BPF filter `ether broadcast or ether multicast`; 30 s window; top-N=10

### `requirements.txt` additions
```
scapy==2.5.0
```

### Metrics added
```
bcast_top_talker_bytes_total, bcast_top_talker_pkts_total, bcast_segment_rate_pps
```

---

## Phase C13 — eBPF Flow Tracking (Weeks 13–14)

### Deliverables
- `checks/ebpf/flow_tracker.py` — `bcc` Python bindings; loads `flow_track.c` BPF program
- `checks/ebpf/programs/flow_track.c` — BPF C source
- Install note: `apt install python3-bpfcc` on Debian/Ubuntu; NOT bundled by PyInstaller

### Capabilities required
```
CAP_BPF + CAP_PERFMON (Linux 5.8+)
```

---

## Phase B1/B2 — PyInstaller Build + CI (Week 14)

### Deliverables
- `Dockerfile.collector-amd64` — PyInstaller build for Linux amd64
- `Dockerfile.collector-arm64` — PyInstaller build for Linux arm64 (via Docker buildx + QEMU)
- `.github/workflows/ci.yml` — `setup-python@v5`, pytest, mypy, ruff, pyinstaller artifact
- `collector/dist/` — built binaries committed as CI artifacts

---

## Open Research Tasks

| # | Task | Doc |
|---|---|---|
| R1 | scapy AsyncSniffer on Pi 3B: CPU overhead at OT rates (<100 pps) | `docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md` (update: scapy replaces gopacket) |
| R2 | bcc Python bindings on Raspberry Pi OS: kernel BPF enabled? python3-bpfcc available? | TBD |
| R3 | PyInstaller --onefile startup time on Pi 3B: acceptable for systemd `ExecStartPre` health check? | TBD |
