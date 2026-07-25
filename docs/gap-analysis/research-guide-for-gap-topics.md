# Step-by-Step Research Guide for Gap Analysis Topics

> Companion to `docs/gap-analysis-collector-vs-standalone.md`. Use this as a working checklist before implementing each roadmap phase. Each section lists: what to read, what to measure/prototype locally, and the exit criteria that show the topic is ready to implement.
>
> **Update (2026-07-25):** Dedicated deep-research documents now exist for three of the topics below — `docs/mdp-adaptive-scheduling-theory.md` (§4), `docs/segment-health-arp-dhcp-theory.md` (§7), and `docs/ot-protocol-safety-theory.md` (§3). Where a topic has a completed theory doc, the "read" step is satisfied; the empirical/data-driven validation steps in this guide remain the blocking work before implementation.
>
> **Update (2026-07-25, later):** Research backlog topics 9, 11, and 12 checked/closed out, and three new backlog topics added — see §8 below.
> - **Topic 9 (SNMP sysUpTime regression)** → now covered by new `docs/snmp-sysuptime-regression-theory.md`.
> - **Topic 11 (MDP finite-state approximation)** → found to already be substantially covered by the existing `docs/mdp-adaptive-scheduling-theory.md` Part 2 ("Deriving the Finite-State Scheduler From Theory"); no new document was needed, this backlog item should be marked ✅ rather than "Next".
> - **Topic 12 (Hotelling T² multivariate detection)** → now covered by new `docs/hotelling-t2-multivariate-detection.md`.
> - **New topics added:** adaptive thresholding logic (cross-cutting — see note in §8.1), fault-tree analysis for multi-hop paths (new `docs/fault-tree-multihop-paths.md`), and high-cardinality metric storage (new `docs/high-cardinality-storage.md`).

## How to Use This Guide

Work top-to-bottom in priority order. Do not start implementation on a topic until its "Exit Criteria" are met — this keeps the academically-grounded style of the existing `collector/ROADMAP.md` and avoids hard-coding unvalidated thresholds.

---

## 1. Baseline Parity Checks (No New Research Required)

Goal: port already-proven standalone behavior into the collector.

**Step 1.1 — Re-read source of truth**
- Re-read `monitor/outage_monitor.py` (`PingWorker`, `iface_counters()`, `wifi_sample()`) and `collector/main.go` side by side.
- Re-read `collector/ROADMAP.md` Phase 0 and `collector/SUGGESTIONS.md` §3.1/§6.1-6.2.

**Step 1.2 — Extract the algorithm, not the code**
- Loss % computation: `(sent - received) / sent * 100`.
- RTT distribution: track `rtt_min`, `rtt_max`, `rtt_p50`, `rtt_p95` per target per cycle.
- Interface counters: `/proc/net/dev` deltas → bytes/s, errors/s (Linux); `Get-NetAdapterStatistics` (Windows).

**Step 1.3 — Prototype in isolation**
- Write a small standalone Go test harness that runs `pingWithLoss()` against 2-3 real targets for 10 minutes and compares its loss%/RTT output against the standalone monitor's SQLite `ping_samples` table for the same targets and time window.

**Exit criteria:** Go prototype's loss%/RTT numbers match the standalone monitor's numbers within measurement noise (±1 sample) for the same targets over the same window. No literature review needed — this is a straight port validated by data comparison.

---

## 2. Route Table, WAN Checks, OS Health, TLS, SNMP (Collector Phase 1)

Goal: implement well-specified checks that exist in `SUGGESTIONS.md` §6.3-6.10 but require verifying real-world edge cases.

**Step 2.1 — Read the primary standards**
- RFC 7799 ("Active and Passive Metrics and Methods") for the terminology used throughout the roadmap.
- RFC 1213 (SNMPv2-MIB) for the exact OID semantics being read (`sysDescr`, `sysUpTime`, `ifOperStatus`).
- For `sysUpTime` specifically, also read `docs/snmp-sysuptime-regression-theory.md` before implementing reboot-detection logic — it documents the 32-bit rollover pitfall (~497 days) and the correct disambiguation using `snmpEngineTime`/`hrSystemUptime`, which RFC 1213 alone does not warn about.

**Step 2.2 — Cross-check platform differences**
- Build a small matrix (already started in `SUGGESTIONS.md` §8) and validate it against actual target OSes in the deployment fleet: Raspberry Pi OS (Debian-based), Ubuntu/Debian VPS, Windows Server.
- Specifically verify `ip -j route` JSON output format on the Raspberry Pi's iproute2 version (older Pi OS images may predate iproute2 v4.12's JSON support) — this is a real compatibility risk not yet tested.

**Step 2.3 — Validate WAN check safety**
- Confirm `api.ipify.org` (or a self-hosted alternative) rate limits are compatible with the default 30s collection interval across however many collector nodes will be deployed.

**Step 2.4 — Prototype TLS/SNMP against real infra**
- Test TLS cert expiry check against the user's existing Traefik reverse-proxy endpoints.
- Test SNMP v2c/v3 GET against any existing managed switch/router in the network, using the same credential model already implemented in `monitor/snmp_probe.py`.
- Implement the `sysUpTime` regression classifier per `docs/snmp-sysuptime-regression-theory.md` §2.3's decision table, not a naive "counter decreased = reboot" check.

**Exit criteria:** each check (routes, WAN, OS health, TLS, SNMP) runs cleanly against at least one real Raspberry Pi and one real Windows Server target with no crashes or false positives over a 24-hour soak test. SNMP reboot detection specifically must be validated to not false-positive near the 497-day rollover boundary (may require simulating a rollover in a test harness rather than waiting 497 days).

---

## 3. OT Protocol Checks (Modbus, S7, BACnet, OPC-UA)

Goal: implement read-only OT polling without violating IEC 62443 safety constraints.

> **Reading step now satisfied by `docs/ot-protocol-safety-theory.md`** — it covers NIST SP 800-82 Rev.3, IEC 62443-3-2/3-3, passive protocol fingerprinting (Modbus/S7/DNP3/EtherNet-IP/BACnet), and the multi-collector polling-load question raised in Step 3.4 below. The steps below remain the required empirical/procedural validation on top of that theory.

**Step 3.1 — Read the standards before writing any code**
- IEC 62443-3-3 (system security requirements) — specifically the availability-over-confidentiality priority for OT (FR7, per `docs/ot-protocol-safety-theory.md` §1.2).
- Ollila, T. "Overview for capabilities of OT network monitoring tools." JAMK Thesis, 2024 (theseus.fi/handle/10024/851535) — the vendor-protocol-gap finding.
- RITICS/NCSC ICS-COI "How to log and monitor in ICS/OT Environments" (2024) — Appendix A indicator list.
- OPC Foundation OPC-10000-6 §7.6 (well-known discovery addresses) and Part 2 §7.2 (discovery security) — already referenced in `docs/05-research-and-decisions.md`.
- NIST SP 800-82 Rev.3 §6.2.1 (active-scanning caution) and IEC 62443-3-2 §4.2 (passive-first posture) — now cited in full in `docs/ot-protocol-safety-theory.md` Part 1.

**Step 3.2 — Get explicit sign-off before any active OT query**
- Per `docs/05-research-and-decisions.md`, OPC-UA `FindServers`/`GetEndpoints` and S7comm active queries require approval from the controls owner. Do not skip this step even in a lab environment — treat it as a hard gate, not a suggestion. `docs/ot-protocol-safety-theory.md` Part 4 extends the same gate to BACnet's `Who-Is`/`I-Am` discovery.

**Step 3.3 — Prototype against a simulator, not production OT**
- Use a Modbus TCP simulator (e.g., a local `pymodbus` test server) to validate FC01/FC03 read-only logic and the hard-coded refusal of FC05/FC06/FC16 write codes before pointing at any real PLC.
- Add the content-based protocol-signature check from `docs/ot-protocol-safety-theory.md` §2.1 to the simulator test matrix (verify the signature check correctly rejects a simulator misconfigured to answer on the wrong port).

**Step 3.4 — Model multi-collector polling load (theory now documented; empirical step still open)**
- If more than one collector will observe the same upstream OT device (e.g., a shared switch across Purdue zones), calculate cumulative requests/minute across all collectors and confirm it stays within the target device's documented connection-table limits. `docs/ot-protocol-safety-theory.md` §3.2-3.3 now documents this constraint (with a real-world SCADA-master TCP-connection-limit example) and proposes a "single OT-owner collector" mitigation; what remains is confirming the actual connection limits of the specific PLC/SNMP devices in this deployment and applying the mitigation.

**Exit criteria:** simulator tests pass with zero write attempts possible even under fault injection (including the protocol-signature check); controls-owner sign-off obtained in writing; multi-collector load calculation documented against real device connection limits (not just the general theory).

---

## 4. MDP Adaptive Scheduler (Collector Phase 4)

Goal: replace fixed-interval polling with the finite-state scheduler, validated against real failure data rather than assumed thresholds.

> **Reading step now satisfied by `docs/mdp-adaptive-scheduling-theory.md`** — it covers Zabala et al. (2023) in depth, corrects the scope of that paper's applicability (single-processor capture/analysis contention, not literally multi-target reachability scheduling), and adds the more directly relevant probe-scheduling literature (Cohen et al. 2013; Mahmoody et al. 2015). It also specifies (§2.2) that the STABLE→SUSPECT transition should be a CUSUM alarm reusing `docs/anomaly-detection-theory.md`'s parameters rather than an independent ad hoc threshold. **Its Part 2 ("Deriving the Finite-State Scheduler From Theory") is also the answer to backlog topic 11 ("MDP finite-state approximation") — no separate document was needed for that backlog item.** Steps 4.2-4.4 below remain the required empirical validation.

**Step 4.1 — Read the core paper**
- Zabala, L. et al. "Optimality of a Network Monitoring Agent and Validation in a Real Environment." Mathematics 11(3):610, 2023 (mdpi.com/2227-7390/11/3/610). Focus on how they validate the MDP model against a real environment, not just simulation.
- Also read Cohen et al. (arXiv:1302.0792) and Mahmoody et al. (arXiv:1509.02487), per `docs/mdp-adaptive-scheduling-theory.md` §1.1/1.3, for the multi-target probe-scheduling framing that maps more directly onto this collector's actual problem than Zabala et al. alone.

**Step 4.2 — Build a labeled dataset from your own network**
- Export the standalone monitor's `events` table (start/end/kind/failed_targets) covering at least 30 days of history.
- For each historical outage, extract the RTT/loss trajectory in the 10 minutes before onset from `ping_samples`.

**Step 4.3 — Validate the roadmap's hard-coded thresholds against that dataset**
- Check whether `loss_pct > 1.0` and `rtt_p95 > 2.0 * baseline` actually preceded the recorded outages, or whether they fire too early/late/never on your specific network profiles (home LAN vs. VPS vs. OT segment may need different thresholds).
- Prefer replacing the ad hoc constants with the CUSUM-alarm-based transition specified in `docs/mdp-adaptive-scheduling-theory.md` §2.2, then validate that formulation against the dataset instead of the raw constants.

**Step 4.4 — Backtest detection latency improvement**
- Simulate the finite-state machine against the historical data and measure the actual time-from-failure-onset-to-alert versus what the fixed 30s ticker would have produced. Compare against the paper's claimed 40-60% improvement — do not assume it transfers without checking, and note the scope correction in `docs/mdp-adaptive-scheduling-theory.md` §1.2 when interpreting the comparison.

**Exit criteria:** thresholds are backed by at least 30 days of this project's own outage data (not just literature defaults), CUSUM-based transition logic has been implemented and backtested per §2.2 of the theory doc, and backtested detection-latency improvement is documented with real numbers before shipping Phase 4.

---

## 5. Frank-Wolfe Probe-Budget Allocation (Collector Phase 5)

Goal: implement variance-weighted probing only if it demonstrably helps at this project's scale.

**Step 5.1 — Read the source paper and note its scale assumptions**
- Amjad, M.J. et al. "Optimal Probing with Statistical Guarantees for Network Monitoring at Scale." arXiv:2109.07743, 2021. Note that results were demonstrated on real cloud networks with many paths — a materially larger N than a typical collector's 5-15 targets.

**Step 5.2 — Run a small-N simulation before implementing**
- Using the historical RTT data gathered in Step 4.2, simulate Welford's online variance over rolling windows of 20 samples per target and check numerical stability (variance estimates should not swing wildly cycle-to-cycle for genuinely stable targets).

**Step 5.3 — Compare allocation outcomes**
- Compare probe counts allocated under the variance-weighted scheme versus fixed-interval polling over the same historical window, and check whether the reduction in probes sent still catches every real outage that fixed polling caught.

**Exit criteria:** simulation shows no missed outages versus fixed-interval baseline, and variance estimates are stable enough (no wild oscillation) at this project's target counts (5-15 per collector) before enabling in production.

---

## 6. Passive eBPF RTT Layer (Collector Phase 2)

Goal: add in-kernel passive RTT observation without breaking on Raspberry Pi or inside Docker.

**Step 6.1 — Read the source design**
- Sundberg, S. "Towards Ubiquitous and Continuous Network Latency Monitoring." Karlstad University Licentiate Thesis, 2024 (doi.org/10.59217/xpyc8728) — read the `epping` chapter specifically for its TC/XDP hook design and BPF map layout.

**Step 6.2 — Verify target hardware compatibility first**
- Check the Linux kernel version on each Raspberry Pi image actually in use; `epping` requires kernel ≥5.6. Older Raspberry Pi OS (Legacy/Buster) images may not meet this — verify before committing to the design.
- Check whether `CAP_BPF` and `CAP_NET_ADMIN` are obtainable in the collector's actual deployment mode (bare systemd service vs. inside a Docker container) — container eBPF support depends on the container runtime's seccomp/AppArmor profile and needs a documented test, not an assumption.

**Step 6.3 — Prototype the vendored epping program in isolation**
- Vendor the Apache-2 licensed `epping` BPF C source, compile with `clang -target bpf`, and load via `cilium/ebpf` in a throwaway test binary on one Raspberry Pi before integrating into `collector/main.go`.

**Step 6.4 — Define and document the fallback path**
- Confirm the collector cleanly disables the eBPF module (rather than crashing) when capabilities are absent, and write this behavior into a new `docs/ebpf-deployment-constraints.md` alongside the existing `docs/ebpf-map-best-practices.md`.

**Exit criteria:** working prototype on at least one real Raspberry Pi target confirming kernel/capability compatibility, plus a documented graceful-fallback behavior, before merging into `collector/main.go`.

---

## 7. ARP-Rate / Broadcast-Storm Thresholds (Collector Phase 3)

Goal: derive a real threshold instead of the placeholder "> N ARP replies per minute" left open in `SUGGESTIONS.md`.

> **Reading step now satisfied by `docs/segment-health-arp-dhcp-theory.md`** — it covers ARP storm vs. ARP spoofing as two distinct detection problems (volumetric-rate vs. IP-MAC binding-consistency), density-aware baselining for wireless/IoT-heavy segments, and DHCP starvation/message-distribution detection (extending this section's original scope to Phase 3c as well). Steps 7.2-7.3 below remain the required empirical baselining.

**Step 7.1 — Read the taxonomy paper**
- Brügge, M. & Simon, M. "Link Failure Detection in Computer Networks." NET-2024-04-1, TU Munich, 2024 — note it identifies ARP storms as a signal but does not give a numeric threshold for this project's network sizes.
- Also read the ARP-spoofing detection literature in `docs/segment-health-arp-dhcp-theory.md` §1.2 (DS-ARP binding-consistency method) to ensure the implementation covers spoofing, not just volumetric storms.

**Step 7.2 — Collect your own baseline**
- Use the standalone monitor's existing ARP/neighbour visibility to log ARP reply rate per IP over at least one full week, covering normal usage patterns (including known-busy periods, e.g., game server or backup traffic).

**Step 7.3 — Derive threshold statistically**
- Compute mean and standard deviation of per-IP ARP rate from that baseline; set the anomaly threshold at, e.g., mean + 3 standard deviations, rather than an arbitrary literature-independent constant. Implement this alongside the independent IP-MAC binding-consistency check from `docs/segment-health-arp-dhcp-theory.md` §1.3 — the two checks are complementary, not substitutes for each other.

**Exit criteria:** threshold N is derived from at least 7 days of this network's own ARP-rate data, documented with the calculation, before being hard-coded into `net_arp_watch.go`; the binding-consistency check is implemented as a separate, independent detector rather than folded into the rate threshold.

---

## 8. Cross-Cutting / Recently Added Backlog Topics

These three topics were added to the research backlog alongside the closeout of topics 9, 11, and 12, and cut across multiple phases above rather than belonging to a single one.

### 8.1 Adaptive Thresholding Logic for Network Metrics

This is deliberately **not** a new standalone theory document, because the project already has the two building blocks it needs, spread across existing docs:
- Univariate adaptive thresholds (CUSUM ARL tables, EWMA parameters, MAD-based per-metric sigma) → `docs/anomaly-detection-theory.md`.
- Multivariate/cross-metric adaptive thresholds (Hotelling T² with per-temporal-cluster hysteresis thresholds) → new `docs/hotelling-t2-multivariate-detection.md` §2.3.
- State-transition adaptive thresholds for the scheduler itself → `docs/mdp-adaptive-scheduling-theory.md` §2.2.

**Remaining work is integration, not new research:** write a short design note (when Phase 4 implementation begins) that shows all three existing threshold mechanisms sharing one debounce/hysteresis implementation rather than three parallel ad hoc ones, per the cross-references already added in §2.3 of the new Hotelling doc and §2.2 of the MDP doc.

### 8.2 Fault-Tree Analysis for Multi-Hop Network Paths

Covered in full by new `docs/fault-tree-multihop-paths.md`. Read this before designing the RCA pipeline's per-hop root-cause ranking logic (`docs/rca-causal-inference.md`) — the fault tree's minimal cut sets are meant to be consumed as candidate hypotheses by that pipeline, not implemented as a separate, disconnected feature.

**Exit criteria:** the project's actual path topology has been enumerated against the AND/OR/PAND gate taxonomy in `docs/fault-tree-multihop-paths.md` §2.2 before any fault-tree logic is coded, and the WireGuard primary/fallback relationship is modeled as a dynamic (PAND) tree rather than a static OR gate.

### 8.3 Optimizing Data Storage Structures for High-Cardinality Metrics

Covered in full by new `docs/high-cardinality-storage.md`, with a concrete priority order for this project (downsampling first, series-identity normalization second, unbounded-field exclusion third, everything else deferred until scale justifies it).

**Exit criteria:** downsampling tiers and series-identity normalization (§2.1/§2.4 of the new doc) are implemented in the standalone monitor's SQLite schema *before* per-hop (`mtr`) and per-OID (SNMP) collector-parity features are added — adding those features first, on the current unnormalized schema, would multiply cardinality before the mitigation exists.

---

## Summary Table: Research Gate per Phase

| Phase | Research required before coding? | Primary reading | Theory doc status | Data-driven validation needed |
|---|---|---|---|---|
| 0 — Parity port | No | `collector/ROADMAP.md` Phase 0 | N/A | Compare against standalone SQLite data |
| 1 — Routes/WAN/OS/TLS/SNMP | Light | RFC 7799, RFC 1213 | Light, plus **Complete** for sysUpTime specifically — `docs/snmp-sysuptime-regression-theory.md` | Platform matrix soak test; rollover-boundary test for SNMP reboot detection |
| OT protocols | Yes — safety gate | IEC 62443-3-3, Ollila 2024, RITICS/NCSC, NIST SP 800-82 | **Complete** — `docs/ot-protocol-safety-theory.md` | Simulator tests + controls-owner sign-off + real device connection-limit check |
| 4 — MDP scheduler | Yes | Zabala et al. 2023; Cohen et al. 2013; Mahmoody et al. 2015 | **Complete** (incl. finite-state approximation) — `docs/mdp-adaptive-scheduling-theory.md` | 30+ days of own outage data; CUSUM-transition backtest |
| 5 — Probe budget allocation | Yes | Amjad et al. 2021 | Not yet written | Small-N simulation |
| 2 — eBPF passive RTT | Yes | Sundberg 2024 | Not yet written (map-level notes only in `docs/ebpf-map-best-practices.md`) | Raspberry Pi kernel/capability test |
| 3 — ARP-rate thresholds | Yes | Brügge & Simon 2024; DS-ARP; Tripathi & Hubballi | **Complete** — `docs/segment-health-arp-dhcp-theory.md` | 7+ days of own ARP baseline |
| Cross-cutting — multivariate detection | Yes | Melnikov et al. 2025 (SICAMS) | **Complete** — `docs/hotelling-t2-multivariate-detection.md` | Empirical normality check per metric; 30-day backtest shared with Phase 4 |
| Cross-cutting — path fault modeling | Yes | NRC Fault Tree Handbook; Ahmed et al. 2016 | **Complete** — `docs/fault-tree-multihop-paths.md` | Topology enumeration against real deployment |
| Cross-cutting — metric storage scaling | Yes | Netdata Academy 2026; InfoQ 2026 | **Complete** — `docs/high-cardinality-storage.md` | None (design-only until scale requires benchmarking) |
