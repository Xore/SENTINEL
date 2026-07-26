# Design decisions — v2 Collector

Key architectural decisions made during the v2 design phase, with rationale and
references. Companion to
[`docs/collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md).

---

## D1 — Python 3.12, not Go

**Decision:** The v2 collector is written in Python 3.12. The v1 Go collector is retired.

**Rationale:**
- The backend services (ingest, analyse, API, federation agent) already use Python
  for ML/analysis work. A single language across all components eliminates the Go
  toolchain, Go module management, and CGO cross-compilation complexity.
- Python has mature, actively maintained libraries for every check type needed:
  `scapy` (AF_PACKET), `bcc` (eBPF), `pymodbus` (Modbus), `pysnmp` (SNMP),
  `opentelemetry-sdk` (OTLP export), `pydantic` (config validation).
- eBPF integration via `bcc` Python bindings is the best-documented path for
  kernel-version-matched BPF programs on Linux arm64; Go `cilium/ebpf` requires
  more boilerplate and is harder to test on Pi hardware.
- `asyncio` provides the concurrency model (cooperative multitasking + task
  scheduling) without the complexity of goroutine lifecycle management.

**Trade-off accepted:** Python startup time is higher than Go. PyInstaller
`--onefile` cold start on Pi 3B requires validation (research gate R3 in
[`docs/gap-analysis/research-guide-for-gap-topics.md`](../gap-analysis/research-guide-for-gap-topics.md)).

---

## D2 — PyInstaller single-file binary, not Docker

**Decision:** The collector ships as a PyInstaller `--onefile` binary (~18–22 MB).
Docker is used for CI cross-compilation only — not for deployment.

**Rationale:**
- OT edge nodes and Raspberry Pis often run minimal OS images without Docker
  installed. A self-contained binary has zero runtime prerequisites beyond the OS.
- A single binary is easier to version, distribute, verify (`sha256sum`), and
  update than a Docker image on constrained hardware.
- `bcc` (eBPF) is the one exception: it is kernel-version-matched and cannot be
  bundled. It is installed via `apt install python3-bpfcc` and is optional
  (graceful degradation if absent).
- Binary size (~20 MB) is acceptable on any SD card or eMMC used in production.

---

## D3 — OTLP/gRPC over mTLS, not a custom push protocol

**Decision:** All collector-to-hub communication uses OTLP/gRPC with mutual TLS.

**Rationale:**
- OTLP is the OpenTelemetry wire standard — hub-side ingest can be any
  OTLP-compatible backend (Grafana Mimir, Victoria Metrics, self-hosted).
- gRPC provides efficient binary framing, HTTP/2 multiplexing, and built-in
  flow control — important on low-bandwidth OT links.
- mTLS means both the collector and the hub authenticate each other; a
  compromised collector cannot impersonate another node.
- PKI auto-enrolment (`pki/enroll.py`) and auto-renewal (`pki/renew.py`) keep
  cert management invisible to the operator under normal conditions.

---

## D4 — asyncio task scheduler, not threads

**Decision:** All checks run as `asyncio` coroutines scheduled by a priority-queue
scheduler (`collector/scheduler.py`). No threads are used except where a library
forces it (e.g. `scapy.AsyncSniffer`).

**Rationale:**
- A single asyncio event loop on a Pi 3B is more memory-efficient than one thread
  per check. At ~15–20 concurrent checks, thread stack overhead would add 30–40 MB
  of RSS unnecessarily.
- Cooperative multitasking makes it straightforward to reason about which check is
  running and to set per-check timeouts with `asyncio.wait_for()`.
- The MDP-style priority queue ensures high-priority checks (ICMP reachability)
  are never starved by long-running checks (bcast/mcast 30 s window).
- `scapy.AsyncSniffer` runs in a background thread internally; this is acceptable
  because it is a bounded window (30 s) with a defined stop point.

---

## D5 — lmdb hot buffer + sqlite3 cold store, not in-memory only

**Decision:** Metrics are buffered locally using `lmdb` (hot, last 30 min) and
`sqlite3` (cold, up to 24 h) when the hub is unreachable.

**Rationale:**
- OT sites frequently have unreliable WAN or inter-VLAN paths. An in-memory buffer
  is lost on process restart; a persistent buffer survives.
- `lmdb` provides fast key-value writes with ACID guarantees and near-zero
  read latency for the retry queue — appropriate for high-frequency metric samples.
- `sqlite3` is Python stdlib (zero extra dependency) and WAL mode gives
  concurrent read/write without locking the collector's main loop.
- 24 h of buffering at scan level 2 workload fits comfortably within 200 MB on
  any SD card used in production (NFR-05).

---

## D6 — `scapy.AsyncSniffer` for broadcast/multicast, not libpcap

**Decision:** Phase C11 uses `scapy.AsyncSniffer` with a BPF pre-filter. No
`libpcap`, `tcpdump`, or `dumpcap` binary is required on the collector node.

**Rationale:**
- scapy opens an AF_PACKET raw socket directly; the BPF filter
  `ether broadcast or ether multicast` is applied at kernel level before any
  packet reaches Python userspace, keeping CPU overhead minimal.
- `store=False` means raw packet bytes are never buffered — only per-MAC packet
  counts accumulate in a dict, bounding memory use to O(unique MACs).
- `scapy==2.5.0` is already in `requirements.txt` and bundled by PyInstaller
  (`--collect-all scapy`).
- Unicast frames are never received (OT confidentiality requirement: FR-02).

**Open gate:** CPU overhead on Pi 3B at 100 pps must be validated before Phase C11
is merged. See research gate R1 in
[`docs/gap-analysis/research-guide-for-gap-topics.md`](../gap-analysis/research-guide-for-gap-topics.md).

---

## D7 — `bcc` Python bindings for eBPF, installed via OS package manager

**Decision:** Phase C13 eBPF flow tracking uses `bcc` Python bindings. `bcc` is
not bundled by PyInstaller — it must be installed as `python3-bpfcc` via `apt`.

**Rationale:**
- `bcc` is kernel-version-matched: the same `.so` that links against `libbcc`
  must match the running kernel’s BPF ABI. PyInstaller cannot bundle this safely.
- `apt install python3-bpfcc` on Debian/Ubuntu installs the correct version for
  the installed kernel automatically.
- The graceful fallback (`try: from bcc import BPF except ImportError: BPF = None`)
  means a node without `python3-bpfcc` simply skips eBPF checks — all other
  phases continue normally (FR-07).
- Requires kernel ≥5.8 for the `CAP_BPF`/`CAP_PERFMON` split. 32-bit Pi OS
  images (pre-Bookworm) are unsupported for eBPF.

---

## D8 — `pydantic` v2 for config validation, not `dataclasses` or raw dicts

**Decision:** `CollectorSettings` is a `pydantic-settings` `BaseSettings` model
loaded from a YAML file. All nested config objects are `pydantic` `BaseModel`.

**Rationale:**
- `pydantic` v2 provides fast validation, clear error messages on misconfiguration,
  and automatic coercion (e.g. string `"60"` → `int` for `scan_interval_s`).
- SIGHUP hot-reload re-parses and re-validates the YAML; a validation error logs a
  structured error and keeps the previous valid config in place — the collector
  never crashes on a bad config reload.
- `pydantic-settings` supports environment variable overrides
  (`COLLECTOR__BACKEND__URL=...`) for containerised or CI test deployments.

---

## OT reachability semantics

The v2 collector defaults to TCP reachability checks only. Application-layer
protocol checks (OPC-UA `GetEndpoints`, S7comm, BACnet `Who-Is`) require separate
approval from the asset owner and must be validated on a test system first.

- OPC Foundation: `opc.tcp://<host>:4840/UADiscovery` is the well-known discovery
  address; `FindServers` and `GetEndpoints` create application traffic and are
  gated behind explicit config.
- S7comm/TCP 102: an open port proves neither device identity nor PLC health.
  Prefer passive identification from ARP watch and TCP connect; use vendor-aware
  active queries only in a documented, approved test profile.
- BACnet `Who-Is`/`I-Am` is an active broadcast mechanism — treated the same as
  OPC-UA `GetEndpoints` for approval purposes.

**Academic basis:** NIST SP 800-82 Rev.3 §6.2.1, IEC 62443-3-2 §4.2, IEC 62443-3-3 FR7.
Full analysis in [`../theory/ot/ot-protocol-safety-theory.md`](../theory/ot/ot-protocol-safety-theory.md).

---

## Academic references

| Reference | Grounds |
|---|---|
| NIST SP 800-82 Rev.3 §6.2.1 | Active scanning caution in live ICS (D6 passive-first) |
| IEC 62443-3-3 FR7 | Availability as a security property (D4 graceful degradation) |
| IEC 62443-3-2 §4.2 | Passive asset discovery as default |
| TU Munich NET-2024-04-1 §3 | Broadcast storms as OT congestion cause (D6) |
| RITICS/NCSC ICS-COI 2024 App.A | Broadcast storms as OT IoC (D6) |
| OpenTelemetry OTLP spec | Wire format for D3 |
| scapy docs — AsyncSniffer | BPF pre-filter + `store=False` pattern (D6) |
| bcc Python reference (github.com/iovisor/bcc) | eBPF Python bindings (D7) |
| pydantic v2 docs (docs.pydantic.dev) | Config validation pattern (D8) |
