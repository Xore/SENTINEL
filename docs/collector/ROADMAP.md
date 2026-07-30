# Collector v2 — Roadmap

> **Language:** Python 3.12 (PyInstaller single-file binary)  
> **Updated:** 2026-07-30 — Deliverable paths corrected to the modules that were actually
> built, stale/unsatisfiable pin blocks replaced by a pointer to `requirements.txt`, and
> metric sketches replaced by a pointer to the Metrics Contract.
> Language changed from Go to Python on 2026-07-25; `go.mod` replaced with `requirements.txt`.
>
> Current build status per phase is in
> [`gap-analysis-collector-vs-standalone.md`](../gap-analysis/gap-analysis-collector-vs-standalone.md).

See [`COLLECTOR-V2-REFACTOR.md`](COLLECTOR-V2-REFACTOR.md) for the full implementation design and phased plan.

## Where the open work lives

This file describes *what each phase is*. **What is still open, and who is on it,
is tracked in [GitHub Issues](https://github.com/Xore/SENTINEL/issues?q=is%3Aissue+is%3Aopen+label%3Acollector)** —
one issue per open phase, research gate, and design question. Phases with no
issue below are complete.

| Phase | Open work | Issue |
|---|---|---|
| 3 | Host-health metrics contract, configuration and runtime registration | [#31](https://github.com/Xore/SENTINEL/issues/31) |
| 3 | Windows host-health implementation | [#36](https://github.com/Xore/SENTINEL/issues/36) |
| 4 | Durable export spool and replay integration | [#32](https://github.com/Xore/SENTINEL/issues/32) |
| 4 | `store/hot.py` lmdb ring buffer | [#35](https://github.com/Xore/SENTINEL/issues/35) |
| 5 | Signed updater verifier and installer foundation | [#33](https://github.com/Xore/SENTINEL/issues/33) |
| 5 | PKI auto-renew + collector health score | [#34](https://github.com/Xore/SENTINEL/issues/34) |
| C4 | Wi-Fi health | [#37](https://github.com/Xore/SENTINEL/issues/37) |
| C6 | MTR hop-tracing | [#38](https://github.com/Xore/SENTINEL/issues/38) |
| C8 | SNMP | [#39](https://github.com/Xore/SENTINEL/issues/39) |
| C9 | ARP watch | [#40](https://github.com/Xore/SENTINEL/issues/40) |
| C10 | Passive Modbus | [#41](https://github.com/Xore/SENTINEL/issues/41) |
| C11 | Broadcast/multicast top-talker | [#43](https://github.com/Xore/SENTINEL/issues/43) |
| C13 | eBPF flow tracking | [#45](https://github.com/Xore/SENTINEL/issues/45) |
| B1 | PyInstaller build pipeline | [#46](https://github.com/Xore/SENTINEL/issues/46) |
| B2 | CI: binary artifacts, tag path, canary, rollback | [#48](https://github.com/Xore/SENTINEL/issues/48) |

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

### Dependencies

Pins live in [`collector/requirements.txt`](../../collector/requirements.txt) and are not
duplicated here. The block this section used to carry — `opentelemetry-sdk==1.25.0` with
`grpcio-status==1.64.1` — is **unsatisfiable**: `opentelemetry-proto` requires
`protobuf<5.0` and `grpcio-status` requires `protobuf>=5.26.1`. `requirements.txt` records
the conflict and pins the resolved pair. Phase 1's dependency set is: OTLP SDK + gRPC
exporter, `grpcio`/`grpcio-status`, `pydantic`/`pydantic-settings`, `PyYAML`, `structlog`,
`cryptography`, and `uvloop` on Linux only.

---

## Phase 2 — Core Probes (Weeks 3–4)

**Goal:** Core network probes.

### Deliverables
- `checks/net_icmp.py` — raw `socket.SOCK_RAW` ICMP echo; asyncio-safe
- `checks/net_tcp.py` — `asyncio.open_connection` TCP connect probe
- `checks/net_http.py` — `aiohttp` HTTP/HTTPS probe with TLS validation
- `checks/net_dns.py` — `dnspython` asyncio DNS resolution
- `checks/net_latency.py` — RTT histogram + jitter (wraps net_icmp)

### Dependencies added

`aiohttp` (HTTP probing) and `dnspython` (DNS probing) — both already pinned in `requirements.txt`.

---

## Phase 3 — OS Health (Week 5)

**Goal:** Bundle all host metrics natively. No `node_exporter` dependency.

### Deliverables

Built as seven per-family modules under `checks/`, not the single `os_health/` package
originally sketched, so each host family is a `Check` like every probe and goes through
the same scheduler and timeout path:

- `checks/host_cpu.py`, `checks/host_memory.py`, `checks/host_load.py` — `/proc/stat`, `/proc/meminfo`, `os.getloadavg`
- `checks/host_disk.py` — `os.statvfs`
- `checks/host_network.py` — `/proc/net/dev`
- `checks/host_process.py`, `checks/host_service.py` — process counts; `systemctl show` for unit state
- Windows equivalents (`psutil` / WMI / `win32service`) — not written

### Dependencies added

None on Linux: the host modules read `/proc` and `os.statvfs` directly, so `psutil` was
never added. A Windows implementation would need it; none exists yet.

---

## Phase 4 — Store & Retry (Week 6)

**Goal:** 24 h offline resilience.

### Deliverables
- `store/envelope.py` — immutable versioned envelope with checksum (built)
- `store/sqlite_queue.py` — `sqlite3` (stdlib) cold queue, WAL mode (built; replaces the sketched `store/cold.py`)
- `store/hot.py` — `lmdb` ring buffer: last 30 min of metric samples (not written)
- `transport/retry.py` — exponential backoff queue; spills to lmdb on backend unreachable (not written)

### Dependencies added

`lmdb` — already pinned. The cold store (`store/sqlite_queue.py`) uses stdlib `sqlite3`
and needs nothing extra; `lmdb` is for the hot ring buffer, which is not written yet.

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

Wi-Fi RSSI, link speed, and an AP-change counter. Exact family names, units, and bounded
labels must be added to [`METRICS.md`](../contracts/METRICS.md) before implementation —
the contract mandates base units (`_seconds`, `_bytes`, `_ratio`) and capped labels.

---

## Phase C6 — MTR Hop-Tracing (Week 9)

### Deliverables
- `checks/net_mtr.py` — raw ICMP TTL-exceeded tracing; no external binary; `CAP_NET_RAW`

### Metrics added

Per-hop RTT and loss. Not yet in [`METRICS.md`](../contracts/METRICS.md), and the label
choice is the hard part: a raw `hop_ip` is unbounded and the contract forbids it.

---

## Phase C8 — SNMP (Week 10)

### Deliverables
- `checks/net_snmp.py` — `pysnmp` asyncio SNMP v2c/v3 GET/WALK

### Dependencies added

`pysnmp` — already pinned.

---

## Phase C9 — ARP Watch (Week 10)

### Deliverables
- `checks/net_arp_watch.py` — `/proc/net/arp` polling; new-entry detection

---

## Phase C10 — Modbus Passive (Week 11)

### Deliverables
- `checks/net_modbus.py` — `pymodbus` TCP passive monitoring (Linux only)

### Dependencies added

`pymodbus` — already pinned.

---

## Phase C11 — Broadcast/Multicast Top-Talker (Week 12)

Research task: [`../tasks/RESEARCH-BCAST-MCAST-GOPACKET.md`](../tasks/RESEARCH-BCAST-MCAST-GOPACKET.md) (note: research doc predates Python decision; scapy replaces gopacket).

### Deliverables
- `checks/net_bcast.py` — `scapy.AsyncSniffer`; BPF filter `ether broadcast or ether multicast`; 30 s window; top-N=10

### Dependencies added

`scapy` — already pinned.

### Metrics added

Top-talker bytes/packets and a segment rate. Not yet in
[`METRICS.md`](../contracts/METRICS.md); top-N=10 bounds the talker label, which is what
makes this family admissible at all.

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

All three require physical hardware, which is why none has closed.

| # | Task | Issue | Doc |
|---|---|---|---|
| R1 | scapy AsyncSniffer on the reference Pi 5: CPU overhead at OT rates (<100 pps) | [#42](https://github.com/Xore/SENTINEL/issues/42) | `docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md` (scapy replaces gopacket; re-baselined off the Pi 3B by [ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md)) |
| R2 | bcc Python bindings on Raspberry Pi OS for the Pi 5: is `python3-bpfcc` packaged? (kernel BPF itself is no longer in doubt on 6.6+ arm64) | [#44](https://github.com/Xore/SENTINEL/issues/44) | not written |
| R3 | PyInstaller --onefile startup time on the reference Pi 5: acceptable for systemd `ExecStartPre` health check? | folded into [#46](https://github.com/Xore/SENTINEL/issues/46) | not written |
