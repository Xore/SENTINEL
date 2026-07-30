# Collector v2 — Suggestions & Design Decisions

> **Updated:** 2026-07-25 — Collector v2 language changed from Go to Python. Federation agent also Python. All probe-side components are now a single-language Python stack.

---

## 1. Overview

This document records design decisions, trade-off analysis, and open questions for the v2 collector refactor. The canonical implementation design is in [`COLLECTOR-V2-REFACTOR.md`](COLLECTOR-V2-REFACTOR.md).

---

## 2. Language Decision: Python for the v2 Collector

### 2.1 Context

The v1 collector is written in Go. The backend services (`ingest`, `analyse`, `api`, federation agent) are Python. The original v2 design maintained Go for the collector to preserve the static binary advantage. The decision was revisited and reversed: **Python throughout** is the correct choice for this project.

### 2.2 Key Drivers

- **Single toolchain:** No Go installation needed anywhere in the project. CI simplifies to one language.
- **eBPF:** `bcc` Python bindings are the primary, best-documented interface for BPF programs. The Go `cilium/ebpf` library requires CGO for some features and adds complexity.
- **Packet capture:** `scapy.AsyncSniffer` provides identical access to AF_PACKET as `gopacket/afpacket`, with better documentation and a cleaner API.
- **OT protocols:** `pymodbus` and `pysnmp` are the de-facto standard Python libraries for Modbus and SNMP in OT environments. Their Go equivalents are less mature.
- **Packaging:** PyInstaller `--onefile` produces a ~18–22 MB single-file executable — comparable to the Go static binary (~22–26 MB). It is NOT a Python interpreter + zip; it is a self-contained native binary.
- **Consistency:** The backend `analyse` service already uses Python + asyncio + pydantic. The collector's scheduler, config, and transport layers are now identical in structure.

### 2.3 Go vs Python Trade-off Table

| Dimension | Go (v1 / original v2) | Python (v2 final) | Winner |
|---|---|---|---|
| Toolchain count | 2 (Go + Python) | 1 (Python only) | Python |
| Binary size | ~22–26 MB static | ~18–22 MB PyInstaller | Python |
| eBPF integration | cilium/ebpf (CGO complexity) | bcc Python bindings (standard) | Python |
| Packet capture | gopacket/afpacket | scapy AsyncSniffer | Python |
| SNMP | gosnmp (less mature) | pysnmp (standard) | Python |
| Modbus | go-modbus | pymodbus (OT standard) | Python |
| Async model | goroutines (excellent) | asyncio (good for I/O bound) | Go |
| Memory at idle | ~15 MB | ~35 MB | Go |
| Cold-start time | <100 ms | ~400 ms (PyInstaller) | Go |
| Cross-compile | GOOS/GOARCH (trivial) | Docker buildx + QEMU (workable) | Go |
| Code consistency | Separate from backend | Same language as backend | Python |
| OT library ecosystem | Sparse | Rich (pymodbus, pysnmp, scapy) | Python |

**Verdict:** Python wins on the dimensions that matter most for this project (toolchain, eBPF, OT libraries, consistency). Go wins on raw performance metrics (memory, startup) that are not constraints for a 30-second-cycle probe agent. That was already true on the old Raspberry Pi 3B baseline and is further from binding on the current one — a Raspberry Pi 5 minimum, escalating to a small-form-factor PC ([ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md)). The language decision is confirmed by the hardware change, not reopened by it.

### 2.4 Memory Budget Validation

Target: ≤ 150 MB RSS on the reference Raspberry Pi 5 (was ≤ 80 MB on a Pi 3B; [ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md)).

| Component | Estimated RSS |
|---|---|
| Python 3.12 interpreter (PyInstaller) | ~18 MB |
| opentelemetry-sdk + grpcio | ~12 MB |
| aiohttp | ~4 MB |
| scapy (loaded only when bcast check runs) | ~6 MB |
| lmdb store | ~3 MB |
| pydantic + structlog | ~3 MB |
| asyncio task overhead (20 tasks) | ~4 MB |
| **Total estimated** | **~50 MB** |

50 MB is well within the 80 MB NFR-01 budget. Scapy is only imported when `net_bcast.py` is active (scan level 2); it does not load at startup for scan level 1 nodes.

### 2.5 Federation Agent: Also Python

The federation agent was originally designed as a Go binary running on the site server alongside the backend Docker Compose stack. With the collector now Python, the federation agent is also converted to Python for consistency:

```
site-server/
  backend/ingest/     — Go (unchanged: high-throughput OTLP/gRPC ingestion)
  backend/analyse/    — Python (ML: LSTM-AE, ADWIN, PCA, RCA)
  backend/api/        — Go (unchanged: high-throughput HTTP/WebSocket API)
  backend/federation/ — Python (NEW: replaces Go federation agent binary)
```

**Why keep ingest and api in Go?** They are high-throughput network services (OTLP/gRPC at >1000 requests/s; WebSocket fan-out to many dashboard sessions). Python's GIL and asyncio are adequate but Go's goroutine scheduler excels here. These services have no OT library requirements, no eBPF, no ML — Go is the right tool. The federation agent, by contrast, is a low-frequency background service (heartbeats every 60 s, event forwarding on batch) — Python is fine.

---

## 3. Feature Gap Analysis

### 3.1 v1 Collector vs v2 Collector — Gap Table

| Feature | v1 Collector | v2 Collector | Gap Status | Phase | Python module |
|---|---|---|---|---|---|
| ICMP ping | ✅ | ✅ Planned | Covered | P2 | `net_icmp.py` |
| TCP connect | ✅ | ✅ Planned | Covered | P2 | `net_tcp.py` |
| HTTP/HTTPS probe | ✅ | ✅ Planned | Covered | P2 | `net_http.py` |
| DNS resolution | ✅ | ✅ Planned | Covered | P2 | `net_dns.py` |
| SNMP GET/WALK | ✅ | ✅ Planned | Covered | C8 | `net_snmp.py` |
| OTLP/gRPC export | ✅ | ✅ Planned | Covered | P1 | `transport/otlp.py` |
| mTLS cert auth | ✅ | ✅ Planned | Covered | P1 | `transport/mtls.py` |
| PKI auto-renew | ❌ | ✅ Planned | ✅ v2 new | P5 | `pki/renew.py` |
| Host metrics (CPU/mem/disk) | ❌ | ✅ Planned | ✅ v2 new | P3 | `os_health/linux.py` |
| systemd unit state | ❌ | ✅ Planned | ✅ v2 new | P3 | `os_health/processes.py` |
| Local hot/cold store | ❌ | ✅ Planned | ✅ v2 new | P4 | `store/hot.py`, `store/cold.py` |
| Offline retry queue | ❌ | ✅ Planned | ✅ v2 new | P4 | `transport/retry.py` |
| Wi-Fi health + AP scan | ❌ | ✅ Planned | ✅ v2 new | C4 | `net_wifi_linux.py` |
| MTR hop-tracing | ❌ | ✅ Planned | ✅ v2 new | C6 | `net_mtr.py` |
| Broadcast/multicast top-talker | ❌ | ✅ Planned | ✅ v2 new | C11 | `net_bcast.py` |
| eBPF flow tracking | ❌ | ✅ Planned | ✅ v2 new | C13 | `ebpf/flow_tracker.py` |
| Modbus passive monitoring | ❌ | ✅ Planned | ✅ v2 new | C10 | `net_modbus.py` |
| ARP watch | ✅ | ✅ Planned | Covered | C9 | `net_arp_watch.py` |
| Collector health score | ❌ | ✅ Planned | ✅ v2 new | P5 | `health/score.py` |

---

## 4. Open Questions

Moved to GitHub Issues on 2026-07-30 and folded into the phase that has to
answer them, so a question is closed by the work that resolves it rather than
lingering in this table.

| # | Question | Now tracked as |
|---|---|---|
| Q1 | PyInstaller bundle reproducibility: are builds bit-for-bit reproducible for signed binary distribution? | [#46](https://github.com/Xore/SENTINEL/issues/46) (Phase B1) |
| Q2 | `bcc` on Raspberry Pi OS: `python3-bpfcc` package available? Kernel BPF enabled? | [#44](https://github.com/Xore/SENTINEL/issues/44) (research gate R2) |
| Q3 | scapy + `CAP_NET_RAW` on Raspberry Pi OS Lite: any additional packages needed? | [#42](https://github.com/Xore/SENTINEL/issues/42) (research gate R1) |
| Q4 | Windows `--onefile` startup with Defender real-time scan enabled; may need signing | [#46](https://github.com/Xore/SENTINEL/issues/46) (Phase B1) |
| Q5 | lmdb 1.4.x on Windows: validate under a PyInstaller bundle | [#35](https://github.com/Xore/SENTINEL/issues/35) (hot ring buffer) |
| Q6 | pysnmp v6 async API: confirm asyncio compatibility | [#39](https://github.com/Xore/SENTINEL/issues/39) (Phase C8) |
| Q7 | Federation agent: Compose service or separate systemd unit on the site server? | **Decided: Docker Compose service** — consistent with `analyse`; same Python base image. |

---

## 5. Rejected Alternatives

| Alternative | Why rejected |
|---|---|
| Keep Go for collector, Python for backend | Two toolchains; eBPF in Go requires CGO complexity; OT library gap |
| Rust for collector | No benefit over Python for I/O-bound probe; steep learning curve; no OT library ecosystem |
| Node.js for collector | No eBPF or raw socket ecosystem; high memory overhead |
| Go for federation agent | Inconsistent with Python backend; federation agent is low-frequency — Go performance advantage wasted |
| Separate Go binary for high-performance probes + Python for the rest | Hybrid approach adds complexity without clear benefit at probe rates (30 s cycle) |
