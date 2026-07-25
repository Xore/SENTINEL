# Gap Analysis: Collector vs. Standalone Monitor

> Date: 2026-07-25  
> Scope: Comparison of `collector/` (Go push agent), `monitor/` (standalone Python monitor), and their documented roadmaps, to identify feature parity gaps and documentation/research gaps.

## Overview

`analyseLaptop` has three architectural tiers: a **standalone monitor** (Python, `monitor/`) that runs everything locally with a Flask **dashboard** (`dashboard/`), and a **Go collector agent** (`collector/`) deployable on remote nodes that pushes telemetry to an aggregator. The repository already has deep academic grounding in `docs/collector/ROADMAP.md` and `docs/collector/SUGGESTIONS.md`, citing RFC 7799, Sundberg (2024), Amjad et al. (2021), Zabala et al. (2023), Brügge & Simon (TU Munich, 2024), and RITICS/NCSC guidance.

This document identifies (1) roadmapped collector features not yet implemented, (2) standalone-only features missing from the collector (and vice versa), and (3) topics that need further research before correct implementation.

## Current State by Component

| Component | Language | Core capability today |
|---|---|---|
| `collector/main.go` | Go | Interface enumeration, ARP/neighbour table, ping/dns/http/tcp/ntp/port checks pulled from aggregator config, fast heartbeat + slower sample push, HMAC-gated self-update |
| `monitor/outage_monitor.py` | Python | Per-target continuous ping workers (1s resolution, up/down + RTT), Wi-Fi link stats, interface RX/TX/error/drop counters, DNS/HTTP/TCP/NTP checks via guarded scheduler (jitter, backoff, OT/IT pacing), TCP/UDP port probes, mtr-based route tracing with per-hop loss/jitter, route-change detection, outage classification, broadcast/multicast snapshot on outage |
| `monitor/snmp_probe.py` | Python | Single-host, read-only SNMP GET/walk (sysDescr/sysUpTime/sysName/ifDescr), v2c and v3 auth |
| `dashboard/` | Python/Flask | Web UI, auth, history, metrics, service config, reconciliation, IDS adapter |

## Standalone-Only Features Missing from the Collector

| Standalone-only feature | Present in collector? | Notes |
|---|---|---|
| Loss %/RTT distribution per target | No — binary reachability only | Roadmapped as Phase 0 (P0.1/P0.2) |
| Interface error/drop counters | No | Roadmapped as P0.3 |
| Wi-Fi link quality (signal, bitrate, retries, beacon loss) | No | Not in collector roadmap at all |
| mtr-based hop-level route quality + route-change detection | No | Collector defers to Phase 6, on-demand only |
| Guarded scheduler (jitter, backoff, OT/IT pacing, cooldown) | Partial — fixed intervals only | Collector Phase 4/5 intends this but unbuilt; theory in [`../theory/scheduling/mdp-adaptive-scheduling-theory.md`](../theory/scheduling/mdp-adaptive-scheduling-theory.md) |
| SNMP GET | No | Collector Phase 1e implements with gosnmp, not yet built |

**Recommendation:** port loss-%/RTT-distribution and interface counters into the collector first (Phase 0, no new research needed), then bring the guarded-scheduler concept forward from Phase 4/5.

## Collector-Roadmapped Features Not Yet in Either System

| Feature | Roadmap phase | Priority | Basis |
|---|---|---|---|
| Route table dump + GW-specific ping | Phase 1b | P0/P1 | TU Munich failure taxonomy |
| WAN checks (public IP, latency anchors, external URL) | Phase 1c | P0/P1 | NAT failover / ISP degradation detection |
| OS health (CPU/mem/disk/swap/uptime/load/temp) | Phase 1d | P0 | RITICS/NCSC IoC list |
| Modbus TCP FC01/FC03 read-only polling | Phase 1f | P1 | See [`../theory/ot/ot-protocol-safety-theory.md`](../theory/ot/ot-protocol-safety-theory.md) |
| WireGuard peer health (wgctrl) | Phase 1g | P1 | See [`../theory/probes/wireguard-health-monitoring.md`](../theory/probes/wireguard-health-monitoring.md) |
| TLS certificate expiry checks | Phase 1h | P1 | Avoids surprise outages |
| Passive eBPF RTT layer (epping-style) | Phase 2 | — | See [`../theory/ebpf/ebpf-deployment-constraints.md`](../theory/ebpf/ebpf-deployment-constraints.md) |
| ARP-rate/broadcast-storm + segment-density health | Phase 3 | — | See [`../theory/ot/segment-health-arp-dhcp-theory.md`](../theory/ot/segment-health-arp-dhcp-theory.md) |
| DHCP lease exhaustion/storm detection | Phase 3c | — | See [`../theory/ot/segment-health-arp-dhcp-theory.md`](../theory/ot/segment-health-arp-dhcp-theory.md) |
| MDP-based adaptive probe scheduler | Phase 4 | — | See [`../theory/scheduling/mdp-adaptive-scheduling-theory.md`](../theory/scheduling/mdp-adaptive-scheduling-theory.md) |
| Frank-Wolfe probe-budget allocation | Phase 5 | — | See [`../theory/scheduling/probe-budget-allocation.md`](../theory/scheduling/probe-budget-allocation.md) and [`../theory/scheduling/probe-budget-small-n-theory.md`](../theory/scheduling/probe-budget-small-n-theory.md) |
| On-demand traceroute on DEGRADED transition | Phase 6 | — | Hop-level localisation |
| Prometheus /metrics export | Phase 7 | — | Grafana/Alertmanager integration |

## Documentation Gaps (Open Items)

- No document cross-references `monitor/scheduler.py`'s production scheduler design to the collector's Phase 4 MDP scheduler concept.
- No dedicated document for the Wi-Fi link-quality collection model (`wifi_sample()`), beyond general capture setup in [`../guides/03-capture-and-wifi.md`](../guides/03-capture-and-wifi.md).
- `docs/guides/05-research-and-decisions.md` still needs the zone/conduit note, BACnet discovery gating, and NIST SP 800-82/IEC 62443-3-2 citations per the checklist in [`../theory/ot/ot-protocol-safety-theory.md`](../theory/ot/ot-protocol-safety-theory.md) Part 5.

## Areas Needing Further Academic Research

All five originally open research topics are now resolved:

| # | Topic | Status | Doc |
|---|---|---|---|
| 1 | MDP threshold tuning | ✅ Resolved | [`../theory/scheduling/mdp-threshold-tuning-theory.md`](../theory/scheduling/mdp-threshold-tuning-theory.md) |
| 2 | eBPF passive RTT on ARM/Docker | ✅ Resolved | [`../theory/ebpf/ebpf-deployment-constraints.md`](../theory/ebpf/ebpf-deployment-constraints.md) |
| 3 | Frank-Wolfe at small N | ✅ Resolved | [`../theory/scheduling/probe-budget-small-n-theory.md`](../theory/scheduling/probe-budget-small-n-theory.md) |
| 4 | Multi-collector OT polling load | ✅ Resolved | [`../theory/ot/ot-protocol-safety-theory.md`](../theory/ot/ot-protocol-safety-theory.md) §3.2-3.3 |
| 5 | ARP-storm detection thresholds | ✅ Resolved | [`../theory/ot/segment-health-arp-dhcp-theory.md`](../theory/ot/segment-health-arp-dhcp-theory.md) |

Remaining work on all five is **implementation**, not further literature review.

## Consolidated Priority Recommendations

1. Port loss-%/RTT-distribution, interface error counters, and the guarded scheduler from `monitor/` into `collector/` first (Phase 0, no new research required).
2. Implement collector Phase 1 (routes, WAN checks, OS health, SNMP, TLS) before eBPF/MDP phases, applying the passive-first/fingerprinting guidance in [`../theory/ot/ot-protocol-safety-theory.md`](../theory/ot/ot-protocol-safety-theory.md) for the SNMP/Modbus portions.
3. Treat MDP scheduling, Frank-Wolfe allocation, and eBPF passive RTT as research-gated — theory is documented; empirical validation (backtesting, baseline derivation) remains the blocking step.
4. Add a cross-reference document (or section) linking `monitor/scheduler.py`'s actual behavior to [`../theory/scheduling/mdp-adaptive-scheduling-theory.md`](../theory/scheduling/mdp-adaptive-scheduling-theory.md).
5. Update `docs/guides/05-research-and-decisions.md` per the checklist in [`../theory/ot/ot-protocol-safety-theory.md`](../theory/ot/ot-protocol-safety-theory.md) Part 5.
