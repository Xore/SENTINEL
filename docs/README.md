# Documentation Index

This index organizes `docs/` by purpose and tracks the status of every research gap raised in `docs/gap-analysis-collector-vs-standalone.md`. Files are not physically moved (to avoid breaking existing cross-references between docs), but are grouped here by category so the folder is easier to navigate.

---

## 1. Getting Started / Operational Guides

| Doc | Purpose |
|---|---|
| [`00-setup.md`](./00-setup.md) | Initial setup |
| [`01-design-and-safety.md`](./01-design-and-safety.md) | Design principles and safety constraints |
| [`02-install-lightweight.md`](./02-install-lightweight.md) | Lightweight install path |
| [`03-capture-and-wifi.md`](./03-capture-and-wifi.md) | Packet capture and Wi-Fi monitoring setup |
| [`04-operations.md`](./04-operations.md) | Day-to-day operations |
| [`05-research-and-decisions.md`](./05-research-and-decisions.md) | Design decisions log, incl. OT posture notes |
| [`06-auvik-feature-reference.md`](./06-auvik-feature-reference.md) | Feature-parity reference vs. Auvik |
| [`07-network-map-and-monitoring-roadmap.md`](./07-network-map-and-monitoring-roadmap.md) | Network map and monitoring roadmap |
| [`setup/`](./setup/) | Setup helper files |

## 2. Gap Analysis (Collector vs. Standalone)

| Doc | Purpose |
|---|---|
| [`gap-analysis-collector-vs-standalone.md`](./gap-analysis-collector-vs-standalone.md) | Master gap analysis: collector vs. standalone feature parity, documentation gaps, and open research topics |
| [`research-guide-for-gap-topics.md`](./research-guide-for-gap-topics.md) | Validation/backtesting procedures for each gap topic against this project's own historical data |
| [`research-notes/`](./research-notes/) | Working notes from research sessions |

## 3. Core Feature Design Docs

| Doc | Feature |
|---|---|
| [`icmp-probe-design.md`](./icmp-probe-design.md) | Active ICMP probing design |
| [`passive-vs-active-measurement.md`](./passive-vs-active-measurement.md) | Passive vs. active measurement trade-offs |
| [`wireguard-health-monitoring.md`](./wireguard-health-monitoring.md) | WireGuard tunnel health checks |
| [`snmp-sysuptime-regression-theory.md`](./snmp-sysuptime-regression-theory.md) | SNMP `sysUpTime` regression/reboot detection |
| [`fault-tree-multihop-paths.md`](./fault-tree-multihop-paths.md) | Fault-tree modeling for multi-hop path failures |
| [`rca-causal-inference.md`](./rca-causal-inference.md) | Root-cause analysis via causal inference |
| [`high-cardinality-storage.md`](./high-cardinality-storage.md) | Storage schema for high-cardinality time-series data |

## 4. Anomaly Detection & Statistics

| Doc | Method |
|---|---|
| [`anomaly-detection-theory.md`](./anomaly-detection-theory.md) | CUSUM/EWMA-based anomaly detection foundations |
| [`hotelling-t2-multivariate-detection.md`](./hotelling-t2-multivariate-detection.md) | Multivariate anomaly detection (Hotelling's T²) |

## 5. Scheduling & Probe Budget

| Doc | Status |
|---|---|
| [`mdp-adaptive-scheduling-theory.md`](./mdp-adaptive-scheduling-theory.md) | Base MDP scheduler design (STABLE/SUSPECT/DEGRADED/DOWN) |
| [`mdp-threshold-tuning-theory.md`](./mdp-threshold-tuning-theory.md) | ✅ Closes gap: threshold tuning via hysteresis + empirical backtest (no literature-derived values transfer across networks) |
| [`probe-budget-allocation.md`](./probe-budget-allocation.md) | Base Frank-Wolfe probe-budget allocation design |
| [`probe-budget-small-n-theory.md`](./probe-budget-small-n-theory.md) | ✅ Closes gap: at 5–15 targets, exact A-optimal computation is preferable to the Frank-Wolfe approximation, whose sole justification (intractability at cloud scale) doesn't apply here |

## 6. eBPF

| Doc | Status |
|---|---|
| [`ebpf-map-best-practices.md`](./ebpf-map-best-practices.md) | eBPF map design patterns |
| [`ebpf-deployment-constraints.md`](./ebpf-deployment-constraints.md) | ✅ Closes gap: BTF unavailable by default on stock Raspberry Pi OS, kprobe feature-probing required beyond kernel-version checks, container capability/AppArmor/lockdown-mode constraints, with a revised graceful-degradation code contract |

## 7. OT / Segment Health

| Doc | Status |
|---|---|
| [`ot-protocol-safety-theory.md`](./ot-protocol-safety-theory.md) | ✅ Closes gap: passive-first OT posture (NIST SP 800-82, IEC 62443), content-based protocol fingerprinting independent of port, and **multi-collector OT polling load** — mitigated via a single designated "OT owner" collector per device rather than tuning under an undocumented PLC connection limit |
| [`segment-health-arp-dhcp-theory.md`](./segment-health-arp-dhcp-theory.md) | ✅ Closes gap: **ARP-storm/spoofing detection** via combined rate-baseline (mean+3σ) and IP-MAC binding-consistency checks, plus DHCP starvation detection via message-type distribution and DECLINE/ACK ratio tracking |

---

## Research Gap Closure Status

All originally flagged "genuinely open" research topics from `gap-analysis-collector-vs-standalone.md` are now resolved:

| # | Topic | Resolution |
|---|---|---|
| 1 | eBPF passive RTT on Raspberry Pi/ARM + Docker | `ebpf-deployment-constraints.md` |
| 2 | MDP state-transition threshold tuning | `mdp-threshold-tuning-theory.md` |
| 3 | Frank-Wolfe probe-budget allocation at small N | `probe-budget-small-n-theory.md` |
| 4 | ARP-storm detection thresholds | `segment-health-arp-dhcp-theory.md` |
| 5 | Multi-collector OT polling load | `ot-protocol-safety-theory.md` §3.2–3.3 |

Remaining work on these five topics is **implementation**, not further literature review: porting the specified logic into `net_arp_watch.go`, `net_dhcp_check.go`, `ot_modbus.go`, `ot_snmp.go`, and the collector's `initEBPF()`/scheduler code, then validating against this project's own historical data per the procedures each document specifies.
