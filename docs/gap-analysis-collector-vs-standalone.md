# Gap Analysis: Collector vs. Standalone Monitor

> **Date:** 2026-07-25  
> **Updated:** 2026-07-25 — v2 scope expanded: Wi-Fi health, mtr hop-tracing, broadcast/multicast top-talker added.  
> **Scope:** Comparison of `collector/` (Go push agent), `monitor/` (standalone Python monitor), and their documented roadmaps, to identify feature parity gaps and documentation/research gaps.  
> **v2 collector design:** See [`docs/collector/COLLECTOR-V2-REFACTOR.md`](collector/COLLECTOR-V2-REFACTOR.md) for the full v2 feature set, file structure, and implementation phases.

## Overview

`analyseLaptop` has three architectural tiers: a **standalone monitor** (Python, `monitor/`) that runs everything locally with a Flask **dashboard** (`dashboard/`), and a **Go collector agent** (`collector/`) deployable on remote nodes that pushes telemetry to an aggregator. The repository already has deep academic grounding in `docs/collector/SUGGESTIONS.md` (academic background reference) and `docs/collector/COLLECTOR-V2-REFACTOR.md` (v2 design), citing RFC 7799, Sundberg (2024), Amjad et al. (2021), Zabala et al. (2023), Brügge & Simon (TU Munich, 2024), and RITICS/NCSC guidance.

This document identifies (1) v2 collector features not yet implemented, (2) standalone-only features missing from the collector (and vice versa), and (3) topics that need further research before correct implementation.

## Current State by Component

| Component | Language | Core capability today |
|---|---|---|
| `collector/main.go` (v1, v0.2.0) | Go | Interface enumeration, ARP/neighbour table, ping/dns/http/tcp/ntp/port checks pulled from aggregator config, fast heartbeat + slower sample push, HMAC-gated self-update. **v2 refactor design complete — see `COLLECTOR-V2-REFACTOR.md`.** |
| `collector/` (v2 design, not yet built) | Go | All v1 features + mTLS/gRPC OTLP transport, PKI lifecycle, Gorilla hot/cold store, MDP scheduler, OS health (CPU/mem/disk/uptime), ICMP loss%, interface counters, WAN checks, WireGuard, SNMP v2c/v3, Modbus TCP, TLS cert expiry, listening port snapshot, systemd unit state, eBPF passive RTT (Linux), **Wi-Fi health (signal/AP scan/roaming), mtr hop-level tracing, broadcast/multicast top-talker snapshots**. **Eliminates node_exporter dependency.** |
| `monitor/outage_monitor.py` | Python | Per-target continuous ping workers (1s resolution, up/down + RTT), Wi-Fi link stats, interface RX/TX/error/drop counters, DNS/HTTP/TCP/NTP checks via guarded scheduler (jitter, backoff, OT/IT pacing), TCP/UDP port probes, mtr-based route tracing with per-hop loss/jitter, route-change detection, outage classification, broadcast/multicast snapshot on outage |
| `monitor/snmp_probe.py` | Python | Single-host, read-only SNMP GET/walk (sysDescr/sysUpTime/sysName/ifDescr), v2c and v3 auth |
| `dashboard/` | Python/Flask | Web UI, auth, history, metrics, service config, reconciliation, IDS adapter |

## Gap Table: Standalone Features vs. v2 Collector Design

| Feature | Standalone monitor | v2 Collector | Notes |
|---|---|---|---|
| Loss % / RTT distribution per target | ✅ | ✅ Planned (C4, `net_icmp.go`) | P0; `x/net/icmp` raw socket |
| Interface error/drop counters | ✅ | ✅ Planned (C4, `net_interfaces.go`) | `/proc/net/dev` |
| Wi-Fi link quality (signal, bitrate, retries, AP scan, rogue AP detection) | ✅ | ✅ Planned (C4, `net_wifi_linux.go` / `net_wifi_windows.go`) | `iw`/`iwconfig` shell-out; AP change detection; see `COLLECTOR-V2-REFACTOR.md` §6.2 |
| mtr-based hop-level route tracing | ✅ | ✅ Planned (C6 upgrade, `net_mtr.go`) | Native raw ICMP TTL-exceeded probing via `x/net/icmp`; on-demand on DEGRADED transition |
| Guarded scheduler (jitter, backoff, OT pacing) | ✅ | ✅ Planned (C6, MDP scheduler) | Zabala et al. 2023 |
| Broadcast/multicast top-talker snapshot | ✅ | ✅ Planned (C11, `net_bcast.go`) | AF_PACKET + gopacket; Linux only; `CAP_NET_RAW`; see research task `docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md` |
| SNMP GET v2c/v3 | ✅ (Python) | ✅ Planned (C5, `ot_snmp.go`) | gosnmp; P0 for OT nodes |
| Modbus TCP FC01/FC03 | ❌ | ✅ Planned (C5, `ot_modbus.go`) | P1; OT-only |
| WireGuard peer health | ❌ | ✅ Planned (C4, `net_wireguard.go`) | P1; wgctrl |
| TLS cert expiry check | ❌ | ✅ Planned (C4, `tls_check.go`) | P1 |
| OS health (CPU/mem/disk/uptime) | ❌ | ✅ Planned (C3, `os_health_*.go`) | Eliminates node_exporter |
| systemd unit state | ❌ | ✅ Planned (C3, `os_processes.go`) | Eliminates node_exporter |
| Listening port snapshot | ❌ | ✅ Planned (C4, `os_ports.go`) | P1 |
| WAN public IP + latency anchors | ❌ | ✅ Planned (C4, `net_wan.go`) | P0 |
| Route table + GW RTT | ❌ | ✅ Planned (C4, `net_routes.go`) | P1 |
| mTLS/gRPC OTLP transport | N/A | ✅ Planned (C1, `transport/`) | Transport change from v1 HTTP |
| PKI auto-enrollment + cert renewal | N/A | ✅ Planned (C1, `pki/`) | No openssl CLI needed on node |
| Gorilla hot/cold buffer (26h) | N/A | ✅ Planned (C2, `compress/`) | Pelkonen VLDB 2015 |
| MDP adaptive scheduling | ❌ | ✅ Planned (C6, `scheduler/`) | Zabala 2023; ~40% fewer probes |
| eBPF passive RTT | ❌ | ✅ Planned (C7, `ebpf/`) | Linux only; CAP_BPF required |
| Self-reported health score | ❌ | ✅ Planned (C8, `health_score.go`) | 0.0–1.0 gauge; fleet table |

## Remaining Documentation Gaps (post-v2 design)

- No document maps the `monitor/scheduler.py` guarded-scheduler design to the collector v2 MDP scheduler (`scheduler/scheduler.go`) — the same concept implemented twice.
- eBPF docs cover map best practices but not ARM/Raspberry Pi verifier constraints or Docker-container eBPF interaction.
- No document maps IEC 62443-3-3 zone/conduit boundaries to actual deployment topology (beyond `SUGGESTIONS.md` §9 and `COLLECTOR-V2-REFACTOR.md` §11).
- Broadcast/multicast top-talker implementation approach in Go requires validation — see [`docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md`](tasks/RESEARCH-BCAST-MCAST-GOPACKET.md) and GitHub issue #TBD.

## Areas Needing Further Academic Research

1. **MDP scheduler threshold tuning** — Zabala et al. (2023) proves the general result, but the hard-coded thresholds (loss>1%, rtt_p95>2× baseline) need validation against real outage data from the standalone monitor's SQLite history.
2. **eBPF passive RTT on ARM/Raspberry Pi** — verifier limitations and Docker/eBPF interaction are unvalidated on the target hardware.
3. **Probe-budget (Frank-Wolfe) at small N** — 50% reduction proven at cloud scale; unclear if it holds at N=5–15 targets with only 20 rolling variance samples.
4. **OT multi-collector polling load** — cumulative polling load when multiple zone-collectors target a shared upstream OT switch is not modeled.
5. **ARP-rate/broadcast-storm thresholds** — TU Munich (2024) establishes the signal but gives no numeric threshold; needs empirical derivation from baseline data.
6. **Broadcast/multicast top-talker in Go** — gopacket AF_PACKET approach is feasible but requires validation of performance at OT segment rates (sparse traffic) and verification that `CAP_NET_RAW` + static binary deploy model holds on ARM. See `docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md`.

## Consolidated Priority Recommendations

1. **Implement v2 collector phases C1–C6** (transport, buffer, OS health, network checks, SNMP/Modbus, MDP scheduler) — this closes the majority of gaps with the standalone monitor.
2. **C4 now includes Wi-Fi health** (`net_wifi_linux.go`, `net_wifi_windows.go`) — AP change detection and signal drop monitoring are in scope.
3. **C6 mtr upgrade** — on-demand mtr hop-tracing via native `x/net/icmp` TTL-exceeded probing replaces the exec-based placeholder.
4. **C11 broadcast/multicast** — implement after C7 (eBPF) since it shares the `CAP_NET_RAW` capability and gopacket dependency. Validate approach first via the research task.
5. After C1–C6 ship, validate MDP scheduler thresholds against standalone monitor's historical outage dataset before tuning Phase C7 (eBPF) priority hints.
6. Document ARM/Raspberry Pi and Docker-container constraints before starting Phase C7 (eBPF) and C11 (gopacket).
