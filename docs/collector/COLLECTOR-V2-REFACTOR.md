# Collector v2 Refactor — Design & Gap Analysis

> **Date:** 2026-07-25  
> **Status:** Design — not yet implemented  
> **Supersedes:** `docs/collector/SUGGESTIONS.md` (which remains as the academic background reference)  
> **Architecture context:** `docs/architecture/ARCHITECTURE-V2-EXTENDED.md`

This document defines exactly what the collector binary must become for v2, what it already has, what gaps exist, and how to bundle the maximum set of v2-required functions into the single Go binary while keeping it cross-platform, dependency-minimal, and OT-safe.

---

## 1. Current State (v1, v0.2.0)

| Capability | File | Status |
|---|---|---|
| Config load (JSON, env-override) | `main.go` | ✅ Done |
| HTTP push transport (`X-Ingest-Key`) | `main.go` | ✅ Done — **must be replaced** for v2 |
| Fast heartbeat ping | `main.go` | ✅ Done — becomes OTLP metric |
| HMAC-authenticated self-update | `main.go` | ✅ Done — upgrade to Ed25519 |
| Interface inventory (name/MAC/addr) | `main.go` | ✅ Done — extend with counters |
| ARP/neighbour table read | `main.go` | ✅ Done |
| Active checks: DNS/HTTP/TCP/NTP/port | `checks.go` | ✅ Done |
| ICMP ping (OS shell-out) | `ping_linux.go`, `ping_windows.go` | ✅ Done — upgrade to raw socket |
| Re-exec after self-update | `reexec_unix.go`, `reexec_windows.go` | ✅ Done |
| mTLS/gRPC OTLP transport | — | ❌ Missing |
| Gorilla delta-of-delta hot/cold store | — | ❌ Missing |
| eBPF passive RTT (kprobe + TC hook) | — | ❌ Missing |
| MDP adaptive scheduler | — | ❌ Missing |
| node_exporter host-metric read + bundle | — | ❌ Missing |
| SNMP v2c/v3 GET | — | ❌ Missing |
| Modbus TCP FC01/FC03 read-only | — | ❌ Missing |
| WireGuard peer health (wgctrl) | — | ❌ Missing |
| ICMP loss % (multi-packet, raw socket) | — | ❌ Missing |
| Interface RX/TX counters + errors | — | ❌ Missing |
| Route table + default GW RTT | — | ❌ Missing |
| WAN public IP + latency anchors | — | ❌ Missing |
| OS health (CPU/mem/disk/uptime) | — | ❌ Missing |
| Listening port snapshot (ss/netstat) | — | ❌ Missing |
| TLS certificate expiry check | — | ❌ Missing |
| PKI leaf cert auto-enrollment + renewal | — | ❌ Missing |
| Check-plan consumer (PostgreSQL-backed) | `main.go` (partial) | ⚠️ Partial — fetches via HTTP, needs OTLP plan channel |
| `collector_heartbeat_total` counter | — | ❌ Missing — needed by vmalert fleet rules |

---

## 2. v2 Transport: From HTTP Push → mTLS/gRPC OTLP

### 2.1 Why the transport must change

v1 uses plain HTTP POST with `X-Ingest-Key` in the header. This works for a single-server, single-site deployment but has four blocking problems for v2:

| Problem | v1 | v2 requirement |
|---|---|---|
| Authentication | Shared secret in HTTP header | Mutual TLS — both sides authenticate with X.509 certs |
| Protocol | JSON over HTTP/1.1 | OTLP/gRPC (proto3) over HTTP/2 — structured, typed, compressed |
| Metric model | Flat JSON rows | OTLP `ResourceMetrics` with labels — native VictoriaMetrics ingest |
| Compression | None (JSON is verbose) | gRPC with gzip per message + Gorilla local store |

### 2.2 Transport change — concrete design

The `http.Client` + `post()` function in `main.go` is replaced by an **OTLP exporter** using `go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc`.

```
┌─────────────────────────────────┐
│  collector binary               │
│                                 │
│  metrics.go                     │
│  ┌──────────────────────────┐   │
│  │ otel MeterProvider       │   │
│  │ (in-process SDK)         │   │
│  │  └─ Gorilla local store  │◀──┤ all check results recorded here
│  │      (hot/cold SQLite)   │   │
│  └──────────────────────────┘   │
│           │                     │
│           │ OTLP/gRPC export    │
│           │ every 30 s          │
│           │ mTLS (leaf cert)    │
│           ▼                     │
└─────────────────────────────────┘
           │
           ▼
  backend/ingest (Go)
  ── Prometheus remote-write ──▶ VictoriaMetrics
  ── SQL (pgx) ──────────────▶ PostgreSQL
```

### 2.3 mTLS PKI bootstrap

On first start with no cert on disk, the collector calls `POST /api/pki/enroll` over plain HTTPS (TLS verify: CA bundle provided in config) with the enrollment token. The ingest service issues a leaf cert (ECDSA P-256, 90-day validity). The collector stores `pki/ca.crt`, `pki/collector.crt`, `pki/collector.key` under `$STATE_DIR/pki/`.

Auto-renewal: 14 days before expiry, the collector calls `POST /api/pki/renew` with the current cert in the client TLS handshake. No enrollment token needed for renewal.

For air-gap sites: the cert bundle is distributed via USB. The collector detects `pki/` already populated and skips enrollment.

---

## 3. Gorilla Hot/Cold Local Store

### 3.1 What it is

When the OTLP push to the ingest service fails (network outage, ingest service restart), the collector must not lose samples. The Gorilla delta-of-delta encoding (Pelkonen et al., VLDB 2015) stores `(ts_ms, value)` pairs at ~1.375 bytes/sample vs ~16 bytes raw — 12× compression.

### 3.2 Design

```
compress/
  store.go       — hot ring buffer (in-memory, last 26h, Gorilla blocks)
  cold.go        — SQLite WAL file (/var/lib/analyselaptop/buffer.db)
  block.go       — Gorilla XOR delta-of-delta encoder/decoder
```

**Hot buffer:** last 26 h in memory (Gorilla blocks of 2 h each). Covers any normal outage window without disk I/O.

**Cold buffer:** on push failure, flush hot blocks to SQLite WAL. On reconnect, drain cold buffer first (chronological order), then resume live push. SQLite is already justified on each collector for this purpose — it is the v1 local store upgraded.

**Backpressure:** if cold buffer exceeds `max_buffer_mb` (default 256 MB), drop oldest blocks with a log warning. The ingest service deduplicates on `(collector_id, metric, target, ts_ms)` so partial replay is safe.

---

## 4. eBPF Passive RTT Layer (Linux only)

### 4.1 What it measures

Two eBPF programs are attached on Linux-only collector nodes to measure passive TCP RTT without active probes:

| Program | Hook | What it captures |
|---|---|---|
| `kprobe/tcp_close` | Kernel function | Per-flow min/max/avg RTT from kernel's `tcp_sock.rcv_rtt_est` at close time |
| `TC hook (egress)` | Traffic Control | Per-packet send timestamp → match with ACK arrival → RTT sample per packet |

This gives **passive RTT for all TCP flows the collector node can observe** — even flows it is not generating. The collector node placed at the default-gateway interface sees all LAN→WAN flows.

### 4.2 Implementation

```
ebpf/
  rtt_kprobe.c        — BPF C source, compiled with bpf2go
  rtt_kprobe_bpf.go   — generated Go bindings (bpf2go output)
  tc_rtt.c            — TC egress hook
  tc_rtt_bpf.go       — generated bindings
  collector.go        — reads perf/ring buffer, emits OTLP gauge samples
```

Build tag: `//go:build linux && cgo` — the eBPF files are excluded from the Windows/macOS builds automatically.

Required capabilities: `CAP_BPF` + `CAP_NET_ADMIN`. The existing `reexec_unix.go` pattern handles privilege escalation for the eBPF load at startup; after loading the programs, capabilities are dropped.

Academic basis: Sundberg (PAM 2023), Bertrone (COP2 2019), Hinz (SIGCOMM 2023) — passive eBPF RTT measurement is demonstrated to be within 1–2 ms of active ICMP probes with zero additional traffic.

### 4.3 Fallback

If `CAP_BPF` is unavailable (non-root, older kernel), the eBPF loader logs a warning and the collector continues with active ICMP probes only. No crash, no missing data stream — eBPF metrics are simply absent from the OTLP push.

---

## 5. MDP Adaptive Scheduler

### 5.1 Problem with fixed-interval polling

v1 runs every check on the same `cfg.Interval` (30 s). This wastes bandwidth on stable targets and under-samples degrading ones.

### 5.2 MDP scheduler design

The check plan returned from the backend now includes a `priority_hints` map:

```json
{
  "priority_hints": {
    "probe-site-a/10.0.0.1/icmp": 0.9,
    "probe-site-a/10.0.0.5/modbus": 0.2
  }
}
```

The collector scheduler implements a simplified **Markov Decision Process**:

- State: `(target, check_type)` → `{stable, degrading, failing, recovering}`
- Reward: information gain from the next probe (estimated from recent variance)
- Policy: checks with higher priority hints OR recent state changes are scheduled at `base_interval / priority` (floored at 5 s, capped at 120 s)

In practice this means:
- A failing ICMP target gets probed every 5–10 s
- A stable Modbus register gets polled every 60–120 s
- Aggregator sets priority based on CUSUM alert state in the analysis service

Academic basis: Zabala et al., *Mathematics* 11(3):610, 2023. The MDP approach reduces total probe count by ~40% while maintaining detection latency on degrading paths.

### 5.3 Implementation

```
scheduler/
  scheduler.go    — priority queue, per-check state machine, backoff logic
  state.go        — check state enum + transition table
```

The existing `sampleTick` / `pingTick` dual-ticker in `main.go` is replaced by the MDP scheduler's `Next()` channel. Each check type registers with the scheduler on startup with its default interval; the scheduler then emits `(checkType, target)` work items.

---

## 6. Bundled Functions: What Goes Inside the Binary

The v2 collector binary bundles everything needed to be self-sufficient on any node. The principle: **one binary, no runtime, no sidecar**.

### 6.1 node_exporter metrics — bundled read, not sidecar

The architecture doc specifies that the collector reads `node_exporter`'s `/metrics` endpoint on `127.0.0.1:9100` and includes host metrics in its OTLP push. For v2 this is refined: **the collector exposes the node_exporter collectors natively** rather than parsing its text output.

This eliminates the `node_exporter` binary dependency entirely on Linux nodes (Windows always uses native APIs). The relevant `/proc` and `syscall` reads are directly in `os_health_linux.go`:

| Metric | Source | Priority |
|---|---|---|
| CPU usage % | `/proc/stat` | P0 |
| Memory available/total | `/proc/meminfo` | P0 |
| Disk free/used per path | `syscall.Statfs` | P0 |
| Load average (1/5/15 min) | `/proc/loadavg` | P0 |
| Uptime seconds | `/proc/uptime` | P0 |
| systemd unit state + restart count | `systemctl show -p ActiveState,NRestarts` | P1 |
| Interface RX/TX bytes, errors, drops | `/proc/net/dev` | P0 |

On **Windows** the same metrics come from `Get-CimInstance Win32_OperatingSystem` + `Get-PSDrive`.

**Result:** The hub no longer needs `node_exporter` installed on each collector node. The `COLLECTOR-FLEET-MONITORING.md` Ansible role for `node_exporter` remains as a fallback option but is no longer the primary path.

### 6.2 All active checks — bundled in `checks.go` and new files

| Check | File | v1 | v2 |
|---|---|---|---|
| ICMP ping (binary up/down) | `ping_linux.go` / `ping_windows.go` | ✅ | Upgrade to `x/net/icmp` raw socket for loss % |
| ICMP loss % (multi-packet) | `net_icmp.go` | ❌ | ✅ — P0 |
| DNS resolution time | `checks.go` | ✅ | Extend: measure resolution latency |
| HTTP/HTTPS check + TLS cert | `checks.go` | ✅ | Extend: capture connect/TLS/response timings separately |
| TCP connect | `checks.go` | ✅ | Keep |
| NTP offset | `checks.go` | ✅ | Keep, add stratum check |
| TCP/UDP port probe | `checks.go` | ✅ | Keep |
| TLS cert expiry | `tls_check.go` | ❌ | ✅ — P1 |
| SNMP v2c/v3 GET | `ot_snmp.go` | ❌ | ✅ — P0 for OT nodes |
| Modbus TCP FC01/FC03 | `ot_modbus.go` | ❌ | ✅ — P1, OT only |
| WireGuard peer health | `net_wireguard.go` | ❌ | ✅ — P1 |
| WAN public IP + latency | `net_wan.go` | ❌ | ✅ — P0 |
| Interface counters | `net_interfaces.go` | ❌ | ✅ — P0 |
| Route table + GW RTT | `net_routes.go` | ❌ | ✅ — P1 |
| Listening port snapshot | `os_ports.go` | ❌ | ✅ — P1 |
| systemd unit state | `os_health_linux.go` | ❌ | ✅ — P1 |
| Docker container status | `os_processes.go` | ❌ | ✅ — P2 |

### 6.3 PKI lifecycle — bundled

The PKI enrollment, cert storage, auto-renewal, and cert expiry monitoring are all handled by the collector binary itself:

```
pki/
  enroll.go    — POST /api/pki/enroll, store cert+key+CA bundle
  renew.go     — auto-renewal 14 days before expiry
  loader.go    — load cert into gRPC TLS config at startup
  expiry.go    — emit collector_cert_days_left gauge to OTLP stream
```

No external tooling (`cfssl`, `openssl` CLI) is needed on the collector node.

### 6.4 Health score — bundled self-report

The `collector_health_score` gauge (0.0–1.0) from the extended architecture is calculated inside the collector and emitted as an OTLP metric every cycle:

```go
// health_score.go
func computeHealthScore(state *agentState) float64 {
    score := 1.0
    // -0.3 if heartbeat gap > 2× interval
    // -0.2 if last cycle duration > 2× mean cycle duration (overrun)
    // -0.2 if metric_gap_count > 0 (check failures)
    // -0.2 if cert_days_left < 14
    // -0.1 if ebpf_loaded == false && linux (degraded mode)
    return max(0.0, score)
}
```

This means the backend never has to infer health from absence of data — the collector self-reports.

---

## 7. Complete v2 File Structure

```
collector/
├── main.go                  # lifecycle, config, startup sequence        (refactor)
├── config.go                # v2 config struct (mTLS, OTLP, PKI, MDP)   (new)
├── checks.go                # DNS/HTTP/TCP/NTP/port — keep, extend       (extend)
├── ping_linux.go            # OS ping wrapper                            (keep)
├── ping_windows.go          # OS ping wrapper                            (keep)
├── reexec_unix.go           # self-update re-exec                        (keep)
├── reexec_windows.go        # self-update re-exec                        (keep)
│
├── transport/
│   ├── otlp.go              # gRPC OTLP exporter, mTLS dial options      (new)
│   └── retry.go             # exponential backoff 1s→60s ±20% jitter    (new)
│
├── pki/
│   ├── enroll.go            # POST /api/pki/enroll → cert+key+CA        (new)
│   ├── renew.go             # auto-renewal 14d before expiry             (new)
│   ├── loader.go            # load cert into tls.Config                  (new)
│   └── expiry.go            # emit collector_cert_days_left gauge        (new)
│
├── compress/
│   ├── store.go             # hot ring buffer, Gorilla blocks            (new)
│   ├── cold.go              # SQLite WAL cold buffer                     (new)
│   └── block.go             # Gorilla XOR delta-of-delta codec           (new)
│
├── scheduler/
│   ├── scheduler.go         # MDP priority queue, work item channel      (new)
│   └── state.go             # check state machine (stable/degrading/…)   (new)
│
├── metrics/
│   ├── meter.go             # OTel MeterProvider setup                   (new)
│   ├── recorder.go          # record check results as OTLP gauges        (new)
│   └── health_score.go      # compute + emit collector_health_score      (new)
│
├── net_icmp.go              # ICMP loss %, x/net/icmp raw socket         (new)
├── net_interfaces.go        # /proc/net/dev counters, errors, drops      (new)
├── net_routes.go            # route table, default GW RTT                (new)
├── net_wan.go               # public IP, WAN latency (1.1.1.1, 8.8.8.8) (new)
├── net_wireguard.go         # wgctrl peer health, handshake age          (new)
│
├── os_health.go             # interface + platform dispatch              (new)
├── os_health_linux.go       # /proc/stat, /proc/meminfo, /proc/uptime   (new)
├── os_health_windows.go     # CimInstance Win32_OperatingSystem          (new)
├── os_ports.go              # ss -tlnp / netstat -ano listening snapshot (new)
├── os_processes.go          # systemd unit state, Docker containers      (new)
│
├── ot_snmp.go               # SNMP v2c/v3 GET (gosnmp)                  (new)
├── ot_modbus.go             # Modbus TCP FC01/FC03 read-only             (new)
├── ot_s7.go                 # Siemens ISO-TSAP connect check             (new)
│
├── tls_check.go             # TLS cert expiry check                      (new)
│
├── ebpf/                    # Linux + cgo only
│   ├── rtt_kprobe.c         # BPF C — kprobe/tcp_close RTT capture      (new)
│   ├── rtt_kprobe_bpf.go    # bpf2go generated bindings                 (new)
│   ├── tc_rtt.c             # TC egress hook                             (new)
│   ├── tc_rtt_bpf.go        # bpf2go generated bindings                 (new)
│   └── collector.go         # read ring buffer → OTLP samples           (new)
│
├── go.mod                   # updated dependencies (see Section 8)      (update)
├── go.sum
└── collector_test.go        # existing tests + new unit tests            (extend)
```

---

## 8. go.mod — v2 Dependencies

```go
module network-probe-collector

go 1.23

require (
    // OTLP/gRPC export
    go.opentelemetry.io/otel                                      v1.28.0
    go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc v1.28.0
    go.opentelemetry.io/otel/sdk/metric                           v1.28.0
    google.golang.org/grpc                                        v1.65.0

    // mTLS / TLS helpers (stdlib covers most; grpc needs credentials)
    google.golang.org/grpc/credentials                            // part of grpc module

    // ICMP raw sockets (loss %, jitter)
    golang.org/x/net                                              v0.28.0

    // SNMP
    github.com/gosnmp/gosnmp                                      v1.38.0

    // Modbus TCP
    github.com/things-labs/go-modbus                              v0.4.0

    // WireGuard wgctrl (Linux + Windows)
    golang.zx2c4.com/wireguard/wgctrl                             v0.0.0-20230429144221-925a1e7659e6

    // eBPF (Linux only — build-tagged, excluded from other platforms)
    github.com/cilium/ebpf                                        v0.16.0

    // Gorilla local store (no external dep — implement with stdlib compress/zlib)
    // SQLite cold buffer — pure Go driver (no cgo dependency)
    modernc.org/sqlite                                            v1.32.0
)
```

**Binary size estimate:**
- v1 (stdlib only): ~6 MB stripped
- v2 (with OTel SDK + gRPC + gosnmp + go-modbus + wgctrl + sqlite): ~22–26 MB stripped
- Still a single static binary, zero runtime dependencies, cross-compiles normally

**Build tags required:**

| File/package | Build tag | Reason |
|---|---|---|
| `ebpf/` | `//go:build linux && cgo` | eBPF requires cgo + Linux kernel |
| `os_health_linux.go` | `//go:build linux` | `/proc` filesystem |
| `os_health_windows.go` | `//go:build windows` | WMI/CIM API |
| `net_routes_linux.go` | `//go:build linux` | `ip route` parsing |
| `net_routes_windows.go` | `//go:build windows` | `route print` parsing |
| `net_wireguard.go` | `//go:build linux \|\| windows` | wgctrl supports L+W |
| `os_processes.go` (systemd) | `//go:build linux` | D-Bus systemd interface |

---

## 9. v2 Config Schema

The v1 config (`aggregator_url`, `ingest_key`, `interval`) is replaced by a richer YAML/JSON config:

```json
{
  "collector_id": "probe-site-a",
  "site_id": "site-a",

  "transport": {
    "ingest_endpoint": "ingest.hub.internal:4317",
    "pki_dir": "/var/lib/analyselaptop/pki",
    "enrollment_token": "",
    "push_interval_s": 30,
    "retry_base_s": 1,
    "retry_max_s": 60,
    "retry_jitter_pct": 20
  },

  "scheduler": {
    "enabled": true,
    "base_interval_s": 30,
    "min_interval_s": 5,
    "max_interval_s": 120
  },

  "buffer": {
    "hot_hours": 26,
    "cold_max_mb": 256,
    "db_path": "/var/lib/analyselaptop/buffer.db"
  },

  "ebpf": {
    "enabled": true,
    "interfaces": ["eth0", "wg0"],
    "perf_buffer_pages": 64
  },

  "os_health": {
    "enabled": true,
    "disk_paths": ["/", "/var/lib/analyselaptop"],
    "cpu_interval_s": 15
  },

  "check_plan_source": "remote",

  "snmp_targets": [],
  "modbus_targets": [],
  "wan_checks": {
    "enabled": true,
    "public_ip_url": "https://api.ipify.org?format=json",
    "latency_targets": ["1.1.1.1", "8.8.8.8"],
    "external_url": ""
  },
  "wireguard": {
    "enabled": true,
    "max_handshake_age_s": 180
  },
  "tls_checks": []
}
```

The config file is versioned (`"version": 2`). A `migrate_config.go` tool auto-converts the v1 JSON config to v2 format on first run.

---

## 10. OTLP Metric Naming Convention

All metrics emitted by the v2 collector follow a consistent naming scheme so VictoriaMetrics labels are clean and MetricsQL queries are predictable:

| Metric | Labels | Unit |
|---|---|---|
| `probe_icmp_rtt_ms` | `collector_id, site_id, target` | ms |
| `probe_icmp_loss_pct` | `collector_id, site_id, target` | % |
| `probe_dns_latency_ms` | `collector_id, site_id, target, resolver` | ms |
| `probe_http_status_code` | `collector_id, site_id, target, url` | int |
| `probe_http_connect_ms` | `collector_id, site_id, target, url` | ms |
| `probe_http_tls_ms` | `collector_id, site_id, target, url` | ms |
| `probe_http_response_ms` | `collector_id, site_id, target, url` | ms |
| `probe_tcp_connect_ms` | `collector_id, site_id, target, port` | ms |
| `probe_ntp_offset_s` | `collector_id, site_id, target` | s |
| `probe_tls_cert_days_left` | `collector_id, site_id, host, subject` | days |
| `probe_snmp_sysuptime_s` | `collector_id, site_id, target` | s |
| `probe_snmp_ifoperstatus` | `collector_id, site_id, target, ifindex` | 0/1 |
| `probe_modbus_register` | `collector_id, site_id, target, unit_id, label` | raw |
| `probe_wg_handshake_age_s` | `collector_id, site_id, peer_key_prefix` | s |
| `probe_wg_rx_bytes_total` | `collector_id, site_id, peer_key_prefix` | bytes |
| `probe_wan_public_ip_change` | `collector_id, site_id` | 0/1 |
| `probe_wan_latency_ms` | `collector_id, site_id, anchor` | ms |
| `host_cpu_usage_pct` | `collector_id, site_id` | % |
| `host_mem_available_bytes` | `collector_id, site_id` | bytes |
| `host_disk_free_bytes` | `collector_id, site_id, mountpoint` | bytes |
| `host_uptime_s` | `collector_id, site_id` | s |
| `host_load1` | `collector_id, site_id` | float |
| `host_net_rx_bytes_total` | `collector_id, site_id, interface` | bytes |
| `host_net_tx_bytes_total` | `collector_id, site_id, interface` | bytes |
| `host_net_rx_errors_total` | `collector_id, site_id, interface` | count |
| `host_systemd_unit_active` | `collector_id, site_id, unit` | 0/1 |
| `host_listening_port_open` | `collector_id, site_id, port, proto` | 0/1 |
| `ebpf_tcp_rtt_ms` | `collector_id, site_id, src_ip, dst_ip, dport` | ms |
| `collector_heartbeat_total` | `collector_id, site_id` | counter |
| `collector_health_score` | `collector_id, site_id` | 0.0–1.0 |
| `collector_cert_days_left` | `collector_id, site_id` | days |
| `collector_cycle_duration_ms` | `collector_id, site_id` | ms |

---

## 11. OT Safety Rules (Non-Negotiable for v2)

All rules from `SUGGESTIONS.md` Section 9 apply unchanged. Summary:

1. **Never write to OT devices.** Only Modbus FC01/FC02/FC03/FC04 permitted. FC05/FC06/FC16 are compile-time absent from `ot_modbus.go`.
2. **Rate-limit all OT probes.** Maximum 1 request per target per MDP scheduler cycle. The scheduler enforces `min_interval_s: 30` for any target in `modbus_targets` or `snmp_targets`.
3. **No ARP broadcast on OT VLANs.** ARP table reads are passive (OS-maintained table). The collector never sends ARP requests.
4. **One collector per zone.** The `site_id` + `zone_id` config fields enforce this at the aggregator level (analysis service rejects cross-zone correlation).
5. **NTP < 1 s offset.** The NTP check now validates stratum ≤ 3 and offset < 1 s; violations are emitted as high-severity events directly (not deferred to analysis service).
6. **IEC 62443 rule-based detections** fire at `confidence=1.0` regardless of ML model state (see ARCHITECTURE-V2-EXTENDED.md Section 7):
   - Modbus FC write observed in passive eBPF TCP flow → alert immediately
   - New MAC on OT VLAN (ARP table) → alert immediately
   - `probe_snmp_sysuptime_s` drops >80% from previous value → alert immediately
   - `probe_wg_handshake_age_s` > `max_handshake_age_s` → alert

---

## 12. Migration from v1 to v2

The v1 and v2 collectors are separate binaries. Migration is node-by-node:

| Step | Action | Rollback |
|---|---|---|
| M1 | Deploy `backend/ingest` v2 alongside v1 aggregator. Both listen independently. | Stop ingest v2 |
| M2 | Roll out v2 collector binary to one pilot node. Validate OTLP stream in VictoriaMetrics. | Deploy v1 binary back via self-update |
| M3 | Migrate config: run `collector-v2 --migrate-config /etc/network-probe/collector.json` → writes `collector-v2.json` | Delete v2 config |
| M4 | Roll out to all nodes 5 at a time. Monitor `collector_health_score` in fleet table. | v1 self-update fallback |
| M5 | Retire v1 aggregator HTTP endpoints once all nodes are on v2 OTLP | — |

Self-update path: v1's HMAC-authenticated self-update (`update_secret`) is used to push the v2 binary to all v1 nodes. v2's first run detects the v1 config and triggers `--migrate-config` automatically before starting.

---

## 13. Phased Implementation Plan

| Phase | Deliverables | Weeks | Depends on |
|---|---|---|---|
| **C1** | Transport layer: `transport/otlp.go`, PKI enrollment/renewal, `go.mod` update, config migration tool | 3 | backend/ingest v2 running |
| **C2** | Gorilla hot/cold store (`compress/`) + SQLite cold buffer + replay-on-reconnect | 2 | C1 |
| **C3** | OS health bundle: CPU/mem/disk/uptime/load (`os_health_*.go`) — eliminates node_exporter | 2 | C1 |
| **C4** | Network checks: ICMP loss%, interface counters, route table, WAN, WireGuard | 2 | C1 |
| **C5** | SNMP v2c/v3 (`ot_snmp.go`) + Modbus TC FC01/FC03 (`ot_modbus.go`) | 2 | C1 |
| **C6** | MDP scheduler (`scheduler/`) + priority_hints consumer | 2 | C2, C3, C4 |
| **C7** | eBPF passive RTT (`ebpf/`) — Linux only, bpf2go toolchain | 3 | C1, C6 |
| **C8** | Health score gauge + cert expiry gauge + vmalert rule validation | 1 | C1–C6 |
| **C9** | IEC 62443 rule-based detection hooks (Modbus FC write, sysUpTime drop, new MAC) | 2 | C5, C7 |
| **C10** | Full test suite: unit + integration + cross-platform CI (linux/amd64, linux/arm64, windows/amd64) | 2 | C1–C9 |

**Total: ~21 weeks** for the full v2 collector. C1–C6 (core transport, checks, OS health, network checks, SNMP/Modbus, scheduler) can ship in ~13 weeks as a functional v2.0 that satisfies all non-eBPF requirements.

---

## 14. Academic Basis for v2 Collector Decisions

| Decision | Reference |
|---|---|
| mTLS/gRPC OTLP transport | Tagliaro et al. ACM CCS 2024; OpenTelemetry Gateway deployment pattern |
| Gorilla delta-of-delta compression | Pelkonen et al. VLDB 2015 — 12× compression, 85% queries hit hot window |
| eBPF passive RTT | Sundberg PAM 2023; Bertrone COP2 2019; Hinz SIGCOMM 2023 |
| MDP adaptive scheduling | Zabala et al. *Mathematics* 11(3):610, 2023 |
| ICMP loss % over binary up/down | Wren project, ACM SIGMETRICS — loss % is the leading indicator |
| SNMP sysUpTime for reboot detection | RITICS/NCSC ICS-COI 2024, Appendix A IoC list |
| Modbus FC03 read-only polling | Ollila JAMK 2024; IEC 62443-3-3 SR 2.1 |
| OT safety rules (rate-limit, no-write) | IEC 62443-3-3; RITICS/NCSC ICS-COI 2024 |
| Go language choice | Zabala 2023 (static binary for edge deployment); wgctrl, cilium/ebpf native Go |
| FedAvg gradient sharing (ML context) | McMahan et al. 2017 — new site cold-start 7d→2d |
