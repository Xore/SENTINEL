# v2 Collector — Implementation Status

> **Updated:** 2026-07-26
> **Scope:** Implementation status of the v2 Python collector (`collector/`) phases defined in
> [`docs/collector/ROADMAP.md`](../collector/ROADMAP.md) and
> [`docs/collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md).
> This document tracks what is built, what is pending, and what still requires research before coding begins.

## Architecture overview

The v2 collector is a **Python 3.12 asyncio process** packaged as a PyInstaller single-file binary.
It runs on any node (Linux amd64/arm64, Windows x64), collects telemetry locally, and pushes
all data to the aggregator hub via **OTLP/gRPC over mTLS**. There is no Flask dashboard,
no Go binary, and no SQLite on the collector node.

| Layer | Technology |
|---|---|
| Runtime | Python 3.12 + `asyncio` |
| Transport | OTLP/gRPC (`opentelemetry-exporter-otlp-proto-grpc`) |
| Security | mTLS — `grpc.ssl_channel_credentials()` + PKI auto-enroll/renew |
| Scheduling | asyncio priority-queue MDP scheduler (`collector/scheduler.py`) |
| Buffering | `lmdb` hot ring buffer (30 min) + `sqlite3` cold store (24 h) |
| Distribution | PyInstaller `--onefile`; Docker multi-arch builds (amd64 + arm64) |

---

## Phase implementation status

| Phase | Description | Status |
|---|---|---|
| **1** | Core bootstrap: config, asyncio loop, OTLP export, mTLS, PKI enroll | 🔲 Pending |
| **2** | Core probes: ICMP, TCP, HTTP, DNS, RTT histogram | 🔲 Pending |
| **3** | OS health: CPU/mem/disk/uptime (Linux `/proc`; Windows `psutil`), systemd unit state | 🔲 Pending |
| **4** | Store & retry: `lmdb` hot buffer, `sqlite3` cold store, exponential backoff retry | 🔲 Pending |
| **5** | PKI auto-renew + health score (0.0–1.0 gauge) | 🔲 Pending |
| **C4** | Wi-Fi health: RSSI, link speed, AP change detection (Linux `iw`; Windows `netsh`) | 🔲 Pending |
| **C6** | MTR hop-tracing: native ICMP TTL-exceeded, no external binary, `CAP_NET_RAW` | 🔲 Pending |
| **C8** | SNMP v2c/v3 GET/WALK (`pysnmp` asyncio) | 🔲 Pending |
| **C9** | ARP watch: `/proc/net/arp` polling, new-entry detection | 🔲 Pending |
| **C10** | Modbus TCP passive monitoring (`pymodbus`, Linux only) | 🔲 Pending |
| **C11** | Broadcast/multicast top-talker: `scapy.AsyncSniffer`, 30 s window, top-N=10 | 🔲 Pending — research gate (see below) |
| **C13** | eBPF flow tracking: `bcc` Python bindings, `CAP_BPF + CAP_PERFMON` (Linux 5.8+) | 🔲 Pending — research gate (see below) |
| **B1/B2** | PyInstaller build pipeline + GitHub Actions CI | 🔲 Pending |

---

## Feature coverage by phase

### Metrics produced when all phases ship

| Category | Metrics |
|---|---|
| ICMP reachability | `icmp_rtt_ms`, `icmp_loss_pct` per target |
| TCP connectivity | `tcp_connect_ms`, `tcp_connect_ok` per target:port |
| HTTP/HTTPS | `http_status_code`, `http_rtt_ms`, `http_tls_expiry_days` |
| DNS | `dns_resolve_ms`, `dns_ok` |
| OS health | `cpu_utilization_pct`, `mem_used_bytes`, `disk_used_bytes`, `uptime_seconds` |
| Systemd | `systemd_unit_active{unit}` |
| Wi-Fi | `wifi_rssi_dbm`, `wifi_link_speed_mbps`, `wifi_ap_changes_total` |
| MTR hops | `mtr_hop_rtt_ms{hop,hop_ip}`, `mtr_hop_loss_pct{hop,hop_ip}` |
| SNMP | `snmp_sysuptime_seconds`, `snmp_if_oper_status{ifindex}` |
| ARP | `arp_new_entries_total`, `arp_table_size` |
| Modbus | `modbus_coil_value{address}`, `modbus_register_value{address}` |
| Bcast/mcast | `bcast_top_talker_bytes_total`, `bcast_top_talker_pkts_total`, `bcast_segment_rate_pps` |
| eBPF flows | `ebpf_flow_bytes_total{src,dst,proto}`, `ebpf_flow_rtt_ms{src,dst}` |
| Health | `collector_health_score` (0.0–1.0) |

---

## Open research gates (must close before coding phase)

| # | Topic | Blocks | Research doc |
|---|---|---|---|
| R1 | `scapy.AsyncSniffer` CPU overhead on Pi 3B at OT rates (<100 pps) | Phase C11 | [`docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md`](../tasks/RESEARCH-BCAST-MCAST-GOPACKET.md) |
| R2 | `bcc` Python bindings on Raspberry Pi OS: kernel BPF support, `python3-bpfcc` availability | Phase C13 | TBD — `docs/tasks/RESEARCH-EBPF-BCC-RPI.md` |
| R3 | PyInstaller `--onefile` startup time on Pi 3B: acceptable for systemd `ExecStartPre`? | Phase B1 | TBD — `docs/tasks/RESEARCH-PYINSTALLER-RPI.md` |

---

## Dependency snapshot (all phases)

```
opentelemetry-sdk==1.25.0
opentelemetry-exporter-otlp-proto-grpc==1.25.0
grpcio==1.64.1
grpcio-status==1.64.1
pydantic==2.7.4
pydantic-settings==2.3.4
structlog==24.2.0
cryptography==42.0.8
aiohttp==3.9.5
dnspython==2.6.1
psutil==5.9.8
lmdb==1.4.7
pysnmp==6.2.5
pymodbus==3.6.9
scapy==2.5.0
```

> Full rationale for each dependency in [`docs/collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md).
