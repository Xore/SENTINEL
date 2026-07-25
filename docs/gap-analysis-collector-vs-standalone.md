# Gap Analysis: Collector vs. Standalone Monitor

> Date: 2026-07-25 (updated same day after adding `mdp-adaptive-scheduling-theory.md`, `segment-health-arp-dhcp-theory.md`, and `ot-protocol-safety-theory.md`)
> Scope: Comparison of `collector/` (Go push agent), `monitor/` (standalone Python monitor), and their documented roadmaps, to identify feature parity gaps and documentation/research gaps.

## Overview

`analyseLaptop` has three architectural tiers: a **standalone monitor** (Python, `monitor/`) that runs everything locally with a Flask **dashboard** (`dashboard/`), and a **Go collector agent** (`collector/`) deployable on remote nodes that pushes telemetry to an aggregator. The repository already has deep academic grounding in `collector/ROADMAP.md` and `collector/SUGGESTIONS.md`, citing RFC 7799, Sundberg (2024), Amjad et al. (2021), Zabala et al. (2023), Brügge & Simon (TU Munich, 2024), and RITICS/NCSC guidance. `docs/` additionally contains deep-dive papers on ICMP probe design, eBPF, anomaly detection theory, RCA/causal inference, WireGuard health, probe-budget allocation, MDP adaptive scheduling theory, segment health/ARP/DHCP theory, and OT protocol safety theory.

This document identifies (1) roadmapped collector features not yet implemented, (2) standalone-only features missing from the collector (and vice versa), and (3) topics that need further research before correct implementation.

## Current State by Component

| Component | Language | Core capability today |
|---|---|---|
| `collector/main.go` | Go | Interface enumeration, ARP/neighbour table, ping/dns/http/tcp/ntp/port checks pulled from aggregator config, fast heartbeat + slower sample push, HMAC-gated self-update |
| `monitor/outage_monitor.py` | Python | Per-target continuous ping workers (1s resolution, up/down + RTT), Wi-Fi link stats, interface RX/TX/error/drop counters, DNS/HTTP/TCP/NTP checks via guarded scheduler (jitter, backoff, OT/IT pacing), TCP/UDP port probes, mtr-based route tracing with per-hop loss/jitter, route-change detection, outage classification, broadcast/multicast snapshot on outage |
| `monitor/snmp_probe.py` | Python | Single-host, read-only SNMP GET/walk (sysDescr/sysUpTime/sysName/ifDescr), v2c and v3 auth |
| `dashboard/` | Python/Flask | Web UI, auth, history, metrics, service config, reconciliation, IDS adapter |
| `docs/05-research-and-decisions.md` | — | Documents stack choices; defers OPC-UA discovery/S7comm active probing pending vendor approval |

## Standalone-Only Features Missing from the Collector

| Standalone-only feature | Present in collector? | Notes |
|---|---|---|
| Loss %/RTT distribution per target | No — binary reachability only | Roadmapped as Phase 0 (P0.1/P0.2) |
| Interface error/drop counters | No | Roadmapped as P0.3 |
| Wi-Fi link quality (signal, bitrate, retries, beacon loss) | No | Not in collector roadmap at all |
| mtr-based hop-level route quality + route-change detection | No | Collector defers to Phase 6, on-demand only |
| Guarded scheduler (jitter, backoff, OT/IT pacing, cooldown) | Partial — fixed intervals only | Collector Phase 4/5 intends this but unbuilt; theory now documented in `docs/mdp-adaptive-scheduling-theory.md` |
| Broadcast/multicast top-talker snapshot (tshark) | No | Heavier dependency than collector's stdlib-only design goal |
| SNMP GET | No | Collector Phase 1e implements with gosnmp, not yet built |
| DNS/HTTP/TCP/NTP with TLS handshake timing, NTP stratum/offset | Partial | Collector checks exist but lack this granularity |

**Recommendation:** port loss-%/RTT-distribution and interface counters into the collector first (Phase 0, no new research needed), then bring the guarded-scheduler concept forward from Phase 4/5, now that its theoretical basis is documented in `docs/mdp-adaptive-scheduling-theory.md`.

## Collector-Roadmapped Features Not Yet in Either System

| Feature | Roadmap phase | Priority | Basis |
|---|---|---|---|
| Route table dump + GW-specific ping | Phase 1b | P0/P1 | TU Munich failure taxonomy |
| WAN checks (public IP, latency anchors, external URL) | Phase 1c | P0/P1 | NAT failover / ISP degradation detection |
| OS health (CPU/mem/disk/swap/uptime/load/temp) | Phase 1d | P0 | RITICS/NCSC IoC list |
| Modbus TCP FC01/FC03 read-only polling | Phase 1f | P1 | Ollila (2024) JAMK thesis; safety/passive-fingerprinting basis now in `docs/ot-protocol-safety-theory.md` |
| WireGuard peer health (wgctrl) | Phase 1g | P1 | See `docs/wireguard-health-monitoring.md` |
| TLS certificate expiry checks | Phase 1h | P1 | Avoids surprise outages |
| Passive eBPF RTT layer (epping-style) | Phase 2 | — | Sundberg PAM 2023; needs CAP_BPF+CAP_NET_ADMIN, kernel >=5.6 |
| ARP-rate/broadcast-storm + segment-density health | Phase 3 | — | TU Munich (2024); detection methodology now documented in `docs/segment-health-arp-dhcp-theory.md` |
| DHCP lease exhaustion/storm detection | Phase 3c | — | Relevant given existing Pi-hole/DNScrypt deployment; message-distribution/Hellinger-distance methodology now documented in `docs/segment-health-arp-dhcp-theory.md` |
| MDP-based adaptive probe scheduler | Phase 4 | — | Zabala et al. (2023): 40-60% faster detection latency; full theory (plus corrected scope vs. multi-target scheduling) now in `docs/mdp-adaptive-scheduling-theory.md` |
| Frank-Wolfe probe-budget allocation | Phase 5 | — | Amjad et al. (2021): 50% probe-traffic reduction |
| On-demand traceroute on DEGRADED transition | Phase 6 | — | Hop-level localisation |
| Prometheus /metrics export | Phase 7 | — | Grafana/Alertmanager integration |
| SNMP/BACnet/OPC-UA/S7/EtherNet-IP/DNP3 checks | Phase 1e / 3.3 backlog | P0-P3 | Full OT matrix documented, unimplemented; passive-first posture, protocol fingerprinting, and multi-collector load constraints now documented in `docs/ot-protocol-safety-theory.md` |

## Documentation Gaps

- No document ties `monitor/scheduler.py`'s production scheduler design to the collector's Phase 4 MDP scheduler concept — same mechanism implemented once in production and once only on paper. `docs/mdp-adaptive-scheduling-theory.md` documents the MDP/probe-scheduling theory itself but does **not yet** cross-reference `monitor/scheduler.py`'s actual implementation; this specific cross-reference remains open.
- No dedicated document for the Wi-Fi link-quality collection model (`wifi_sample()`), beyond general capture setup in `docs/03-capture-and-wifi.md`.
- eBPF docs cover map best practices but not the TC/XDP attach point, `epping` C source vendoring, or fallback when CAP_BPF is unavailable.
- ~~No document maps IEC 62443-3-3 zone/conduit boundaries to actual deployment topology beyond the safety-rule bullets in `SUGGESTIONS.md` §9.~~ **Resolved:** `docs/ot-protocol-safety-theory.md` Part 1.3 now maps the collector itself as a conduit endpoint under IEC 62443-3-2's zone/conduit model and recommends a documentation addition to `docs/05-research-and-decisions.md`'s OT section (that addition itself is still pending — see checklist in that document).
- `docs/05-research-and-decisions.md` is comparatively thin and not cross-referenced with `anomaly-detection-theory.md` / `rca-causal-inference.md` / the three new theory docs listed above. This cross-referencing is still outstanding.

## Areas Needing Further Academic Research

1. **MDP/finite-state scheduler tuning** — Zabala et al. (2023) proves the general result for single-processor capture/analysis contention (not literally multi-target reachability scheduling — see the correction in `docs/mdp-adaptive-scheduling-theory.md` §1.2); the roadmap's finite-state version is a practical analogy borrowing the threshold-policy insight. Hard-coded thresholds (loss>1%, rtt_p95>2x baseline) still need validation against real outage data from the standalone monitor's SQLite history — the *method* for deriving them (CUSUM-consistent thresholding) is now specified in `docs/mdp-adaptive-scheduling-theory.md` §2.2, but the empirical backtest itself has not been run.
2. **eBPF passive RTT portability** — `epping` is proven on commodity Linux, but ARM/Raspberry Pi verifier limitations and container/eBPF interaction under Docker are unaddressed.
3. **Probe-budget allocation (Frank-Wolfe approximation)** — proven at cloud scale (many paths); unclear whether the 50% reduction holds at small N (5-15 targets) with only 20 rolling samples for variance estimation.
4. **OT protocol safety at multi-collector scale** — ~~cumulative polling load when multiple zone-collectors target a shared upstream OT switch is not modeled anywhere~~. **Resolved theoretically:** `docs/ot-protocol-safety-theory.md` §3.2-3.3 documents the constraint (citing real-world SCADA-master TCP-connection-limit data) and proposes a "single OT-owner collector" mitigation. Still outstanding: confirming actual connection limits against the specific PLC/SNMP devices in this deployment.
5. **Broadcast-storm/ARP-rate thresholds** — TU Munich (2024) establishes ARP storms as a signal; `docs/segment-health-arp-dhcp-theory.md` now supplies a concrete two-signal detection method (rate-based + IP-MAC binding consistency) plus density-aware baselining rationale, but the numeric threshold itself still needs empirical derivation from the user's own network baseline per `docs/research-guide-for-gap-topics.md` §7.2-7.3 — this has not yet been executed.

## Consolidated Priority Recommendations

1. Port loss-%/RTT-distribution, interface error counters, and the guarded scheduler from `monitor/` into `collector/` first (Phase 0, no new research required).
2. Implement collector Phase 1 (routes, WAN checks, OS health, SNMP, TLS) before eBPF/MDP phases, applying the passive-first/fingerprinting guidance in `docs/ot-protocol-safety-theory.md` for the SNMP/Modbus portions.
3. Treat MDP scheduling, Frank-Wolfe allocation, and eBPF passive RTT as research-gated, not just engineering-gated — theory is now documented for MDP scheduling and OT safety; empirical validation (backtesting, baseline derivation) remains the blocking step for all of them.
4. Add a cross-reference document (or section) linking `monitor/scheduler.py`'s actual behavior to `docs/mdp-adaptive-scheduling-theory.md`'s theoretical framing — this specific link is still missing.
5. Document ARM/Raspberry Pi and Docker-container constraints before starting Phase 2 (eBPF).
6. Update `docs/05-research-and-decisions.md` per the checklist in `docs/ot-protocol-safety-theory.md` (zone/conduit note, BACnet discovery gating, NIST SP 800-82/IEC 62443-3-2 citations) — currently outstanding.
