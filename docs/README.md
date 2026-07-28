# Documentation Index

This index organizes `docs/` by purpose and tracks the status of every research gap raised in `docs/gap-analysis/`.

---

## 1. Getting Started / Operational Guides

| Doc | Purpose |
|---|---|
| [`guides/00-setup.md`](./guides/00-setup.md) | Initial setup |
| [`guides/01-design-and-safety.md`](./guides/01-design-and-safety.md) | Design principles and safety constraints |
| [`guides/02-install-lightweight.md`](./guides/02-install-lightweight.md) | Lightweight install path |
| [`guides/03-capture-and-wifi.md`](./guides/03-capture-and-wifi.md) | Packet capture and Wi-Fi monitoring setup |
| [`guides/04-operations.md`](./guides/04-operations.md) | Day-to-day operations |
| [`guides/05-research-and-decisions.md`](./guides/05-research-and-decisions.md) | Design decisions log, incl. OT posture notes |
| [`guides/06-auvik-feature-reference.md`](./guides/06-auvik-feature-reference.md) | Feature-parity reference vs. Auvik |
| [`guides/07-network-map-and-monitoring-roadmap.md`](./guides/07-network-map-and-monitoring-roadmap.md) | Network map and monitoring roadmap |
| [`setup/`](./setup/) | Setup helper files |

## 2. Gap Analysis (Collector vs. Standalone)

| Doc | Purpose |
|---|---|
| [`gap-analysis/gap-analysis-collector-vs-standalone.md`](./gap-analysis/gap-analysis-collector-vs-standalone.md) | Master gap analysis: collector vs. standalone feature parity, documentation gaps, and open research topics |
| [`gap-analysis/research-guide-for-gap-topics.md`](./gap-analysis/research-guide-for-gap-topics.md) | Validation/backtesting procedures for each gap topic against this project's own historical data |
| [`gap-analysis/`](./gap-analysis/) | Working notes from research sessions |

## 3. Core Feature Design Docs

| Doc | Feature |
|---|---|
| [`theory/probes/icmp-probe-design.md`](./theory/probes/icmp-probe-design.md) | Active ICMP probing design |
| [`theory/probes/passive-vs-active-measurement.md`](./theory/probes/passive-vs-active-measurement.md) | Passive vs. active measurement trade-offs |
| [`theory/probes/snmp-sysuptime-regression-theory.md`](./theory/probes/snmp-sysuptime-regression-theory.md) | SNMP `sysUpTime` regression/reboot detection |
| [`theory/probes/fault-tree-multihop-paths.md`](./theory/probes/fault-tree-multihop-paths.md) | Fault-tree modeling for multi-hop path failures |
| [`theory/anomaly/rca-causal-inference.md`](./theory/anomaly/rca-causal-inference.md) | Root-cause analysis via causal inference |
| [`theory/probes/high-cardinality-storage.md`](./theory/probes/high-cardinality-storage.md) | Storage schema for high-cardinality time-series data |

## 4. Anomaly Detection & Statistics

| Doc | Method |
|---|---|
| [`theory/anomaly/anomaly-detection-theory.md`](./theory/anomaly/anomaly-detection-theory.md) | CUSUM/EWMA-based anomaly detection foundations |
| [`theory/anomaly/hotelling-t2-multivariate-detection.md`](./theory/anomaly/hotelling-t2-multivariate-detection.md) | Multivariate anomaly detection (Hotelling's T²) |

## 5. Scheduling & Probe Budget

| Doc | Status |
|---|---|
| [`theory/scheduling/mdp-adaptive-scheduling-theory.md`](./theory/scheduling/mdp-adaptive-scheduling-theory.md) | Base MDP scheduler design (STABLE/SUSPECT/DEGRADED/DOWN) |
| [`theory/scheduling/mdp-threshold-tuning-theory.md`](./theory/scheduling/mdp-threshold-tuning-theory.md) | ✅ Closes gap: threshold tuning via hysteresis + empirical backtest (no literature-derived values transfer across networks) |
| [`theory/scheduling/probe-budget-allocation.md`](./theory/scheduling/probe-budget-allocation.md) | Base Frank-Wolfe probe-budget allocation design |
| [`theory/scheduling/probe-budget-small-n-theory.md`](./theory/scheduling/probe-budget-small-n-theory.md) | ✅ Closes gap: at 5–15 targets, exact A-optimal computation is preferable to the Frank-Wolfe approximation, whose sole justification (intractability at cloud scale) doesn't apply here |

## 6. eBPF

| Doc | Status |
|---|---|
| [`theory/ebpf/ebpf-map-best-practices.md`](./theory/ebpf/ebpf-map-best-practices.md) | eBPF map design patterns |
| [`theory/ebpf/ebpf-deployment-constraints.md`](./theory/ebpf/ebpf-deployment-constraints.md) | ✅ Closes gap: BTF unavailable by default on stock Raspberry Pi OS, kprobe feature-probing required beyond kernel-version checks, container capability/AppArmor/lockdown-mode constraints, with a revised graceful-degradation code contract |

## 7. OT / Segment Health

| Doc | Status |
|---|---|
| [`theory/ot/ot-protocol-safety-theory.md`](./theory/ot/ot-protocol-safety-theory.md) | ✅ Closes gap: passive-first OT posture (NIST SP 800-82, IEC 62443), content-based protocol fingerprinting independent of port, and **multi-collector OT polling load** — mitigated via a single designated "OT owner" collector per device rather than tuning under an undocumented PLC connection limit |
| [`theory/ot/segment-health-arp-dhcp-theory.md`](./theory/ot/segment-health-arp-dhcp-theory.md) | ✅ Closes gap: **ARP-storm/spoofing detection** via combined rate-baseline (mean+3σ) and IP-MAC binding-consistency checks, plus DHCP starvation detection via message-type distribution and DECLINE/ACK ratio tracking |

## 8. Roadmap Phases 11–12

| Doc | Phase |
|---|---|
| *(to be created)* `theory/ebpf/ebpf-flow-telemetry-theory.md` | Phase 11 — eBPF TC hook flow metadata: 5-tuple, byte counts, per-flow RTT, no-payload gate, GDPR scope |
| *(to be created)* `theory/scheduling/deep-rl-mdp-theory.md` | Phase 12 — DQN scheduler: corpus schema, reward function, state vector, shadow evaluation, fallback contract |

---

## Research Gap Closure Status

All originally flagged "genuinely open" research topics from `gap-analysis/gap-analysis-collector-vs-standalone.md` are now resolved:

| # | Topic | Resolution |
|---|---|---|
| 1 | eBPF passive RTT on Raspberry Pi/ARM + Docker | [`theory/ebpf/ebpf-deployment-constraints.md`](./theory/ebpf/ebpf-deployment-constraints.md) |
| 2 | MDP state-transition threshold tuning | [`theory/scheduling/mdp-threshold-tuning-theory.md`](./theory/scheduling/mdp-threshold-tuning-theory.md) |
| 3 | Frank-Wolfe probe-budget allocation at small N | [`theory/scheduling/probe-budget-small-n-theory.md`](./theory/scheduling/probe-budget-small-n-theory.md) |
| 4 | ARP-storm detection thresholds | [`theory/ot/segment-health-arp-dhcp-theory.md`](./theory/ot/segment-health-arp-dhcp-theory.md) |
| 5 | Multi-collector OT polling load | [`theory/ot/ot-protocol-safety-theory.md`](./theory/ot/ot-protocol-safety-theory.md) §3.2–3.3 |

Remaining work on these five topics is **implementation**, not further literature review: porting the specified logic into `net_arp_watch.go`, `net_dhcp_check.go`, `ot_modbus.go`, `ot_snmp.go`, and the collector's `initEBPF()`/scheduler code, then validating against this project's own historical data per the procedures each document specifies.

## New Phases — Theory Docs Needed

Phases 11 and 12 have been added to `ROADMAP.md` and require companion theory documents before implementation begins:

| Phase | Theory doc to write | Key decisions to document |
|---|---|---|
| 11 | `theory/ebpf/ebpf-flow-telemetry-theory.md` | TC hook vs XDP; LRU map sizing; flow export batching interval; GDPR scope boundary |
| 12 | `theory/scheduling/deep-rl-mdp-theory.md` | Reward function design; DQN vs PPO; corpus minimum size validation; shadow-mode promotion criteria |
