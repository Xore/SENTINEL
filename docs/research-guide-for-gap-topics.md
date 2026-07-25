# Step-by-Step Research Guide for Gap Analysis Topics

> Companion to `docs/gap-analysis-collector-vs-standalone.md`. Use this as a working checklist before implementing each roadmap phase. Each section lists: what to read, what to measure/prototype locally, and the exit criteria that show the topic is ready to implement.

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

**Step 2.2 — Cross-check platform differences**
- Build a small matrix (already started in `SUGGESTIONS.md` §8) and validate it against actual target OSes in the deployment fleet: Raspberry Pi OS (Debian-based), Ubuntu/Debian VPS, Windows Server.
- Specifically verify `ip -j route` JSON output format on the Raspberry Pi's iproute2 version (older Pi OS images may predate iproute2 v4.12's JSON support) — this is a real compatibility risk not yet tested.

**Step 2.3 — Validate WAN check safety**
- Confirm `api.ipify.org` (or a self-hosted alternative) rate limits are compatible with the default 30s collection interval across however many collector nodes will be deployed.

**Step 2.4 — Prototype TLS/SNMP against real infra**
- Test TLS cert expiry check against the user's existing Traefik reverse-proxy endpoints.
- Test SNMP v2c/v3 GET against any existing managed switch/router in the network, using the same credential model already implemented in `monitor/snmp_probe.py`.

**Exit criteria:** each check (routes, WAN, OS health, TLS, SNMP) runs cleanly against at least one real Raspberry Pi and one real Windows Server target with no crashes or false positives over a 24-hour soak test.

---

## 3. OT Protocol Checks (Modbus, S7, BACnet, OPC-UA)

Goal: implement read-only OT polling without violating IEC 62443 safety constraints.

**Step 3.1 — Read the standards before writing any code**
- IEC 62443-3-3 (system security requirements) — specifically the availability-over-confidentiality priority for OT.
- Ollila, T. "Overview for capabilities of OT network monitoring tools." JAMK Thesis, 2024 (theseus.fi/handle/10024/851535) — the vendor-protocol-gap finding.
- RITICS/NCSC ICS-COI "How to log and monitor in ICS/OT Environments" (2024) — Appendix A indicator list.
- OPC Foundation OPC-10000-6 §7.6 (well-known discovery addresses) and Part 2 §7.2 (discovery security) — already referenced in `docs/05-research-and-decisions.md`.

**Step 3.2 — Get explicit sign-off before any active OT query**
- Per `docs/05-research-and-decisions.md`, OPC-UA `FindServers`/`GetEndpoints` and S7comm active queries require approval from the controls owner. Do not skip this step even in a lab environment — treat it as a hard gate, not a suggestion.

**Step 3.3 — Prototype against a simulator, not production OT**
- Use a Modbus TCP simulator (e.g., a local `pymodbus` test server) to validate FC01/FC03 read-only logic and the hard-coded refusal of FC05/FC06/FC16 write codes before pointing at any real PLC.

**Step 3.4 — Model multi-collector polling load (open research question)**
- If more than one collector will observe the same upstream OT device (e.g., a shared switch across Purdue zones), calculate cumulative requests/minute across all collectors and confirm it stays within the target device's documented connection-table limits. This is currently unmodeled anywhere in the repo and needs a short written note once resolved.

**Exit criteria:** simulator tests pass with zero write attempts possible even under fault injection; controls-owner sign-off obtained in writing; multi-collector load calculation documented.

---

## 4. MDP Adaptive Scheduler (Collector Phase 4)

Goal: replace fixed-interval polling with the finite-state scheduler, validated against real failure data rather than assumed thresholds.

**Step 4.1 — Read the core paper**
- Zabala, L. et al. "Optimality of a Network Monitoring Agent and Validation in a Real Environment." Mathematics 11(3):610, 2023 (mdpi.com/2227-7390/11/3/610). Focus on how they validate the MDP model against a real environment, not just simulation.

**Step 4.2 — Build a labeled dataset from your own network**
- Export the standalone monitor's `events` table (start/end/kind/failed_targets) covering at least 30 days of history.
- For each historical outage, extract the RTT/loss trajectory in the 10 minutes before onset from `ping_samples`.

**Step 4.3 — Validate the roadmap's hard-coded thresholds against that dataset**
- Check whether `loss_pct > 1.0` and `rtt_p95 > 2.0 * baseline` actually preceded the recorded outages, or whether they fire too early/late/never on your specific network profiles (home LAN vs. VPS vs. OT segment may need different thresholds).
- Adjust the thresholds per network profile if the data doesn't support one global constant.

**Step 4.4 — Backtest detection latency improvement**
- Simulate the finite-state machine against the historical data and measure the actual time-from-failure-onset-to-alert versus what the fixed 30s ticker would have produced. Compare against the paper's claimed 40-60% improvement — do not assume it transfers without checking.

**Exit criteria:** thresholds are backed by at least 30 days of this project's own outage data (not just literature defaults), and backtested detection-latency improvement is documented with real numbers before shipping Phase 4.

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

**Step 7.1 — Read the taxonomy paper**
- Brügge, M. & Simon, M. "Link Failure Detection in Computer Networks." NET-2024-04-1, TU Munich, 2024 — note it identifies ARP storms as a signal but does not give a numeric threshold for this project's network sizes.

**Step 7.2 — Collect your own baseline**
- Use the standalone monitor's existing ARP/neighbour visibility to log ARP reply rate per IP over at least one full week, covering normal usage patterns (including known-busy periods, e.g., game server or backup traffic).

**Step 7.3 — Derive threshold statistically**
- Compute mean and standard deviation of per-IP ARP rate from that baseline; set the anomaly threshold at, e.g., mean + 3 standard deviations, rather than an arbitrary literature-independent constant.

**Exit criteria:** threshold N is derived from at least 7 days of this network's own ARP-rate data, documented with the calculation, before being hard-coded into `net_arp_watch.go`.

---

## Summary Table: Research Gate per Phase

| Phase | Research required before coding? | Primary reading | Data-driven validation needed |
|---|---|---|---|
| 0 — Parity port | No | `collector/ROADMAP.md` Phase 0 | Compare against standalone SQLite data |
| 1 — Routes/WAN/OS/TLS/SNMP | Light | RFC 7799, RFC 1213 | Platform matrix soak test |
| OT protocols | Yes — safety gate | IEC 62443-3-3, Ollila 2024, RITICS/NCSC | Simulator tests + controls-owner sign-off |
| 4 — MDP scheduler | Yes | Zabala et al. 2023 | 30+ days of own outage data |
| 5 — Probe budget allocation | Yes | Amjad et al. 2021 | Small-N simulation |
| 2 — eBPF passive RTT | Yes | Sundberg 2024 | Raspberry Pi kernel/capability test |
| 3 — ARP-rate thresholds | Yes | Brügge & Simon 2024 | 7+ days of own ARP baseline |
