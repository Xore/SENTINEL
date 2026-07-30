# v2 Collector — Implementation Status

> **Updated:** 2026-07-30
> **Scope:** Implementation status of the v2 Python collector (`collector/`) phases defined in
> [`docs/collector/ROADMAP.md`](../collector/ROADMAP.md) and
> [`docs/collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md).
> This document tracks what is built, what is pending, and what still requires research before coding begins.

## Architecture overview

The v2 collector is a **Python 3.12 asyncio process**, intended to ship as a PyInstaller
single-file binary (packaging is designed, not yet built — see phase B1).
It runs on any node (Linux amd64/arm64, Windows x64) — minimum a Raspberry Pi 5, escalating
to a small-form-factor x86-64 PC where that is not enough
([ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md)) — collects
telemetry locally, and pushes
all data to the aggregator hub via **OTLP/gRPC over mTLS**. There is no Flask dashboard
and no Go binary on the collector node. It does keep a local SQLite database: the cold
store below is the collector's own durable queue, which is what lets it survive a 24 h
backend outage.

| Layer | Technology | Built? |
|---|---|---|
| Runtime | Python 3.12 + `asyncio` | yes — `collector/__main__.py` |
| Transport | OTLP/gRPC (`opentelemetry-exporter-otlp-proto-grpc`) | yes — `collector/transport/otlp.py` |
| Security | mTLS — `grpc.ssl_channel_credentials()` + PKI auto-enroll/renew | enroll yes (`pki/enroll.py`), auto-renew no |
| Scheduling | asyncio priority-queue MDP scheduler (`collector/scheduler.py`) | priority queue with fixed per-check `interval_s`, yes; MDP interval *adaptation* is not implemented — see [`04-mdp-scheduler.md`](research-notes/04-mdp-scheduler.md) |
| Buffering | `lmdb` hot ring buffer (30 min) + `sqlite3` cold store (24 h) | cold store yes (`store/sqlite_queue.py`); hot ring buffer not written |
| Distribution | PyInstaller `--onefile`; Docker multi-arch builds (amd64 + arm64) | no — no spec file and no collector Dockerfile exist yet |

---

## Phase implementation status

> **What "Built" means here.** This column describes what exists in the tree, nothing
> more. It is *not* the work board. A phase can be fully written and still have its
> work item sitting in `REVIEW`, because only the reviewing agent marks an item `DONE`.
> The authoritative per-item state is the Active Work Board in
> [`AGENT-COORDINATION.md`](../guides/AGENT-COORDINATION.md); where the two disagree,
> the work board wins on *item status* and this table wins on *what code exists*.
> The **Work item** column links the GitHub issue that holds each open scope;
> a phase with no issue is complete.
> **This table covers the collector only.** The analysis tier, ML, production API
> and UI, deployment, federation, HA, RBAC, audit and air-gap requirements are not
> here at all — they live in
> [`REQUIREMENTS-TRACEABILITY.md`](../architecture/REQUIREMENTS-TRACEABILITY.md),
> which spans all 18 phases and links an issue per requirement. Reading this page
> as the whole backlog understates the remaining work by a wide margin.

| Phase | Description | Built | Work item |
|---|---|---|---|
| **1** | Core bootstrap: config, asyncio loop, OTLP export, mTLS, PKI enroll | ✅ `config.py`, `scheduler.py`, `transport/otlp.py`, `transport/mtls.py`, `pki/enroll.py`, `__main__.py` | S0-01/S1-01/S1-02/S2-01 `DONE` |
| **2** | Core probes: ICMP, TCP, HTTP, DNS, RTT histogram | ✅ all five `checks/net_*.py` | S2-02 `DONE` |
| **3** | OS health: CPU/mem/disk/uptime (Linux `/proc`; Windows `psutil`), systemd unit state | ◐ seven Linux `checks/host_*.py` modules exist; metric emission and runtime registration are not wired, and there is no Windows implementation | S3-01A `DONE`; S3-01B `READY` (Codex) — [#31](https://github.com/Xore/SENTINEL/issues/31), Windows [#36](https://github.com/Xore/SENTINEL/issues/36) |
| **4** | Store & retry: `lmdb` hot buffer, `sqlite3` cold store, exponential backoff retry | ◐ cold store built (`store/envelope.py`, `store/sqlite_queue.py`); `store/hot.py` and `transport/retry.py` not written | S4-01A `DONE`; S4-01B `READY` (Codex) — [#32](https://github.com/Xore/SENTINEL/issues/32), hot buffer [#35](https://github.com/Xore/SENTINEL/issues/35) |
| **5** | PKI auto-renew + health score (0.0–1.0 gauge) | 🔲 `pki/renew.py` and `health/score.py` absent; `health/` holds only `loop_watchdog.py` | [#34](https://github.com/Xore/SENTINEL/issues/34); the separate signed-updater slice S5-01 is `READY` — [#33](https://github.com/Xore/SENTINEL/issues/33) |
| **C4** | Wi-Fi health: RSSI, link speed, AP change detection (Linux `iw`; Windows `netsh`) | 🔲 | [#37](https://github.com/Xore/SENTINEL/issues/37) |
| **C6** | MTR hop-tracing: native ICMP TTL-exceeded, no external binary, `CAP_NET_RAW` | 🔲 | [#38](https://github.com/Xore/SENTINEL/issues/38) |
| **C8** | SNMP v2c/v3 GET/WALK (`pysnmp` asyncio) | 🔲 — `pysnmp` is already pinned | [#39](https://github.com/Xore/SENTINEL/issues/39) |
| **C9** | ARP watch: `/proc/net/arp` polling, new-entry detection | 🔲 | [#40](https://github.com/Xore/SENTINEL/issues/40) |
| **C10** | Modbus TCP passive monitoring (`pymodbus`, Linux only) | 🔲 — `pymodbus` is already pinned | [#41](https://github.com/Xore/SENTINEL/issues/41) |
| **C11** | Broadcast/multicast top-talker: `scapy.AsyncSniffer`, 30 s window, top-N=10 | 🔲 — research gate R1 (see below) | [#43](https://github.com/Xore/SENTINEL/issues/43) |
| **C13** | eBPF flow tracking: `bcc` Python bindings, `CAP_BPF + CAP_PERFMON` (Linux 5.8+) | 🔲 — research gate R2 (see below) | [#45](https://github.com/Xore/SENTINEL/issues/45) |
| **B1** | PyInstaller build pipeline (`--onefile`, amd64 + arm64) | 🔲 no `.spec` file and no collector Dockerfile in the tree; `pyinstaller` is a dev dependency only | [#46](https://github.com/Xore/SENTINEL/issues/46) — includes research gate R3 |
| **B2** | GitHub Actions CI | ◐ `collector.yml`, `backend.yml`, `pylint.yml`, `codeql.yml`, `integration-test.yml`, `container-supply-chain.yml` all exist and run; no binary-artifact job | C1-02 `IN_PROGRESS` [#48](https://github.com/Xore/SENTINEL/issues/48), C2-03 `REVIEW` [#47](https://github.com/Xore/SENTINEL/issues/47) |

Legend: ✅ built · ◐ partially built · 🔲 not started.

---

## Feature coverage by phase

### Metrics

**[`docs/contracts/METRICS.md`](../contracts/METRICS.md) is the authority.** Names are not
repeated here, because the sketch that used to sit in this section had drifted away from
the contract on every axis that matters: it dropped the `sentinel_` prefix, used `_ms`
and `_pct` where the contract mandates base units (`_seconds`, `_ratio`), and carried
free-form labels — `{src,dst}`, `{address}`, `{hop_ip}`, `{unit}` — of exactly the
unbounded-cardinality kind the contract's bounded-label policy forbids. Implementing from
that list would have produced a non-conforming collector.

Shipped today, all under §"Core probe families" of the contract, all `target_id`-labelled
and cardinality-capped: `sentinel_collector_icmp_rtt_seconds`,
`sentinel_collector_icmp_loss_ratio`, `sentinel_collector_tcp_connect_seconds`,
`sentinel_collector_http_response_seconds`, `sentinel_collector_dns_resolve_seconds`,
`sentinel_collector_latency_{rtt,jitter}_seconds`,
`sentinel_collector_latency_loss_ratio`, plus the runtime families
(`heartbeat_total`, `check_runs_total`, `check_duration_seconds`,
`export_failures_total`, `cycle_duration_seconds`, `event_loop_lag_seconds`).

**Not yet contract-defined:** host health (phase 3), Wi-Fi, MTR, SNMP, ARP, Modbus,
broadcast/multicast, eBPF flows, and `collector_health_score`. Each needs families added
to `METRICS.md` *before* its phase is implemented, and each needs a bounded label chosen
deliberately — the open cases are recorded as [#50](https://github.com/Xore/SENTINEL/issues/50) (multi-mount disk). Per-flow and per-address
identifiers (eBPF `{src,dst}`, Modbus `{address}`, MTR `{hop_ip}`) are the hardest of
these and should not be assumed admissible.

---

## Open research gates

These gate the phases named below. They do **not** gate the project as a whole — phases 1
through 4 were implemented without needing them. All three require physical hardware, which
is why none has closed.

All three were re-baselined from the Raspberry Pi 3B to the Raspberry Pi 5 on 2026-07-30
([ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md)). None closes as
a result; each loses most of its risk, and R1's and R3's pass thresholds were re-derived.

| # | Topic | Blocks | Research doc |
|---|---|---|---|
| R1 [#42](https://github.com/Xore/SENTINEL/issues/42) | `scapy.AsyncSniffer` CPU overhead on the reference Pi 5 at OT rates (<100 pps) | Phase C11 | [`docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md`](../tasks/RESEARCH-BCAST-MCAST-GOPACKET.md) — exists; its Go-era filename and `gopacket` framing predate the Python decision |
| R2 [#44](https://github.com/Xore/SENTINEL/issues/44) | `bcc` Python bindings on Raspberry Pi OS for the Pi 5: `python3-bpfcc` availability (kernel BPF support is no longer in doubt on 6.6+ arm64) | Phase C13 | **not written** — `docs/tasks/` contains only the R1 document |
| R3 [#46](https://github.com/Xore/SENTINEL/issues/46) | PyInstaller `--onefile` startup time on the reference Pi 5: acceptable for systemd `ExecStartPre`? | Phase B1 | **not written** |

---

## Dependencies

**[`collector/requirements.txt`](../../collector/requirements.txt) is the single source of
truth.** Pins are deliberately not copied here.

The snapshot this section used to carry had drifted on all eleven shared pins, omitted
`PyYAML` and `uvloop`, and listed `psutil` — which is not a collector dependency; the
Linux host modules read `/proc` and `os.statvfs` directly. Worse, it published a
combination that **cannot be installed**: `opentelemetry-sdk==1.25.0` pulls
`opentelemetry-proto`, which requires `protobuf<5.0`, while `grpcio-status==1.64.1`
requires `protobuf>=5.26.1`. `requirements.txt` records that conflict and pins a resolved
pair instead. Anyone following the old block hit a resolver failure on their first
`pip install`.

Two dependencies are deliberately not in `requirements.txt`:

- **`bcc`** (eBPF, phase C13) — installed via the OS package manager
  (`apt install python3-bpfcc`), not pip, and guarded by an import check. It is not
  PyInstaller-bundlable.
- **`uvloop`** is present but conditional (`sys_platform == "linux"`) and soft; see
  [`ASYNCIO-OPTIMIZATION.md`](../guides/ASYNCIO-OPTIMIZATION.md) §7 and the import guard
  in `collector/__main__.py`.

> Rationale for each dependency choice is in
> [`docs/collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md).
