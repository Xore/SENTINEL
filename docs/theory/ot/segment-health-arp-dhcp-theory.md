# Segment Health: ARP Storm & DHCP Starvation Detection Theory
## Academic Research for `collector/` Phase 3 Implementation

> **Status:** Research document — feeds directly into `docs/collector/ROADMAP.md` Phase 3 (`net_arp_watch.go`, `net_segment_health.go`, `net_dhcp_check.go`) and the "excessive client" detection goal described there.
> **Priority:** Medium-High — Phase 3's current spec leaves the ARP-rate anomaly threshold as an unspecified "> N ARP replies per minute" and gives no detection method for DHCP-side congestion beyond a simple lease-percentage check. This document supplies concrete, citable detection methods and closes that gap, matching the depth of the sibling documents already in `docs/` (`anomaly-detection-theory.md`, `mdp-adaptive-scheduling-theory.md`, `probe-budget-allocation.md`).

---

## Part 1 — ARP Storm / ARP Spoofing Detection

### 1.1 Why Rate Thresholds Alone Are Insufficient

The roadmap's current placeholder ("> N ARP replies per minute" from an IP) is a **volumetric** signal only. The literature shows this catches broadcast storms but is easily evaded by spoofing attacks that send a small, targeted number of forged replies rather than flooding — Numan, Hashim & Abdul Latiff (2017, IEEE MICC, "Detection and mitigation of ARP storm attacks using software defined networks") demonstrate that pure volumetric storms are trivially detected by rate counting, but this alone does not catch a **spoofing** attack where an attacker sends a handful of forged ARP replies claiming another host's IP — exactly the kind of stealthy compromise relevant to the user's threat model (rogue devices, MITM).

### 1.2 A Two-Signal Detection Model (Rate + Consistency)

Combining two independent academic detection families gives a stronger signal than rate alone:

**A. Volumetric/rate-based detection (broadcast storms).** Track ARP replies-per-minute per source IP using the ARP table diff already available from the standalone monitor's neighbour-table polling. Ijcsi's "ARP Storm Detection and Prevention Measures" formalizes the storm case as a sustained deviation from a learned per-host baseline rate rather than a single global constant — supporting the same "derive from your own baseline" approach already recommended in `docs/research-guide-for-gap-topics.md` Â§7 for this exact metric.

**B. Consistency-based detection (spoofing).** DS-ARP (Hindawi, *The Scientific World Journal*, 2014, "DS-ARP: A New Detection Scheme for ARP Spoofing Attacks Based on Routing Trace for Ubiquitous Environments") detects spoofing not by rate but by **cross-checking the claimed IP-MAC binding against an independent routing/path trace** — if a host's MAC-to-IP mapping changes without a corresponding, plausible network-path change, it is flagged. For this collector, the practical equivalent is: maintain a **persistent IPâ†’MAC binding table** (already partially implied by the existing ARP/neighbour polling) and alert whenever an existing binding changes MAC address without the old MAC disappearing entirely from the segment first (a legitimate device replacement typically shows old-MAC-vanishes-then-new-MAC-appears, not old-and-new-MAC-both-claiming-the-same-IP simultaneously).

A 2022 SDN-focused paper (MDPI *Electronics* 11(13):1965, "An Extendable Software Architecture for Mitigating ARP Spoofing-Based Attacks in SDN Data Plane Layer") reinforces that IP-MAC binding-table verification, not packet rate, is the primary academically validated technique for the spoofing case specifically, while rate-based methods remain the correct tool for the storm case. **Both mechanisms should be implemented in `net_arp_watch.go`, not just one.**

### 1.3 Recommended Detection Logic for `net_arp_watch.go`

```go
// Two independent checks per ARP-table poll cycle:

// Check 1 — Storm/flood (volumetric)
// rate = arp_replies_from_ip / poll_interval_minutes
// threshold = per-IP baseline_mean + 3*baseline_stddev (derived empirically,
// per docs/research-guide-for-gap-topics.md §7.2-7.3 — NOT a fixed constant)

// Check 2 — Spoofing (binding consistency)
// For each IP in the binding table:
//   if claimed_mac != last_known_mac AND last_known_mac still present
//      elsewhere in the ARP table (i.e., old MAC did not disappear first)
//   -> flag as suspected spoofing, do not silently overwrite the binding
```

This directly implements the storm-vs-spoofing distinction from the literature reviewed above, rather than collapsing both threat types into a single rate counter as the current roadmap sketch does.

### 1.4 Applicability to Wireless/OT Segments

The wireless sensor network broadcast-storm literature (MDPI *Sensors* 11(6):5952, "Adaptive Broadcasting Method Using Neighbor Type Information in Wireless Sensor Networks") is a useful cross-domain reference confirming that **broadcast storms scale with neighbor density**, not just attack intent — a legitimately crowded Wi-Fi segment (many IoT devices) can trigger false positives on a naive global threshold. This reinforces per-segment, density-aware baselining (Phase 3b's `net_segment_health.go`) rather than a single network-wide constant, and is consistent with the TU Munich (2024) finding already cited in `docs/collector/ROADMAP.md` that congestion should be correlated against neighbour count.

---

## Part 2 — DHCP Starvation / Lease-Exhaustion Detection

### 2.1 Beyond Simple Lease-Percentage Thresholds

The roadmap's current spec for `net_dhcp_check.go` ("alert if lease_count / max_leases > 80%") only detects **exhaustion after the fact**. Tripathi & Hubballi (2017, *Journal of Computer Virology and Hacking Techniques* 14(3):233â€“244, "Detecting stealth DHCP starvation attack using machine learning approach") show that a **stealth** starvation attack can exhaust the lease pool gradually and evade naive rate-based IDS because each individual DHCP request looks legitimate; detection instead requires **profiling the distribution of DHCP message types** (DISCOVER/OFFER/REQUEST/ACK/DECLINE ratios) and flagging deviation from the learned normal distribution, achieved in their study using one-class classifiers on real network captures.

Hubballi & Tripathi's earlier companion paper (2017, *Computers & Security* 65:387â€“404, "A closer look into DHCP starvation attack in wireless networks") proposes a lighter-weight, non-ML alternative directly implementable in Go: computing the **Hellinger distance** between a training-period distribution of DHCP message types and the live distribution, flagging an attack when the distance exceeds a learned threshold. This is a much better fit for a lightweight collector agent than a full ML pipeline, since it requires only counting message types and a simple distance calculation.

### 2.2 The "Induced DHCP Starvation" Variant — Relevant Because It Uses DECLINE Messages

The same authors describe an attack variant that abuses the client-side IP-conflict-detection mechanism: a malicious host injects a fake ARP reply during a victim's pre-use IP-conflict probe, causing the victim to broadcast a `DHCPDECLINE` and forfeit a valid lease repeatedly. This is directly relevant to the collector's design because it means **an unusually high rate of `DHCPDECLINE` messages relative to `DHCPACK`** is itself a distinct, specific indicator — not merely "lease pool getting full" — and should be tracked as its own counter rather than folded into the generic lease-percentage metric.

### 2.3 Practical Detection Plan for `net_dhcp_check.go`

```go
// For dnsmasq/Pi-hole-FTL deployments (already the user's DNS/DHCP stack):
// 1. Parse lease file/db for lease_count / max_leases (existing roadmap check — keep)
// 2. NEW: tail dnsmasq's DHCP event log (or query Pi-hole-FTL's dhcp table if present)
//    for message-type counts over a rolling window
// 3. NEW: compute Hellinger distance between the current window's message-type
//    distribution and a learned "quiet-hours" baseline distribution
// 4. NEW: track DECLINE-to-ACK ratio specifically; alert if it exceeds a
//    baseline-derived threshold (Induced DHCP Starvation indicator)
// 5. Existing: alert on repeated lease requests from the same MAC in a short window
//    (classic starvation signature)
```

### 2.4 SDN/Non-SDN Relevance Caveat

Most recent detection papers (2023â€“2025) frame DHCP starvation mitigation in an SDN-controller context (e.g., *Journal of Computer Virology* 2023, "DHCP DoS and starvation attacks on SDN controllers and their mitigation"; 2025 ONOS-relay study). The collector is not SDN-based, so the **mitigation** mechanisms in that literature (dynamic flow-rule installation) do not transfer directly — only the **detection statistics** (message-type distribution, DECLINE ratio, port-scanning-based starvation checks per Jony et al. 2023) are applicable here. This distinction should be noted explicitly so future contributors do not attempt to port SDN-specific mitigation code into a non-SDN Go agent.

---

## Part 3 — Implementation Checklist

| Item | File | Status |
|---|---|---|
| Volumetric ARP-rate check with per-host baseline (mean+3Ïƒ, empirically derived) | `collector/net_arp_watch.go` | Specified here — needs implementation |
| IP-MAC binding-consistency check (spoofing detection, independent of rate) | `collector/net_arp_watch.go` | **Missing from current roadmap — add this** |
| Density-aware baselining correlated with neighbour count | `collector/net_segment_health.go` | Partially specified in `ROADMAP.md` Â§3b — now grounded in WSN broadcast-storm literature |
| DHCP message-type distribution tracking (DISCOVER/OFFER/REQUEST/ACK/DECLINE) | `collector/net_dhcp_check.go` | **Missing — add this** |
| Hellinger-distance-based distribution anomaly check | `collector/net_dhcp_check.go` | **Missing — add this** |
| DECLINE-to-ACK ratio tracking (Induced DHCP Starvation indicator) | `collector/net_dhcp_check.go` | **Missing — add this** |
| Explicit note that SDN-specific mitigation literature does not transfer to this non-SDN agent | `docs/collector/ROADMAP.md` Phase 3 | **Missing — add this** |

---

## References

1. Numan, M.; Hashim, F.; Abdul Latiff, N.M. "Detection and mitigation of ARP storm attacks using software defined networks." IEEE MICC 2017. https://api.semanticscholar.org/CorpusID:3886468
2. "ARP Storm Detection and Prevention Measures." IJCSI 8(2):456â€“460. https://ijcsi.org/papers/IJCSI-8-2-456-460.pdf
3. "DS-ARP: A New Detection Scheme for ARP Spoofing Attacks Based on Routing Trace for Ubiquitous Environments." The Scientific World Journal, 2014. https://downloads.hindawi.com/journals/tswj/2014/264654.pdf
4. "An Extendable Software Architecture for Mitigating ARP Spoofing-Based Attacks in SDN Data Plane Layer." MDPI Electronics 11(13):1965, 2022. https://www.mdpi.com/2079-9292/11/13/1965
5. "Adaptive Broadcasting Method Using Neighbor Type Information in Wireless Sensor Networks." MDPI Sensors 11(6):5952, 2011. https://www.mdpi.com/1424-8220/11/6/5952
6. Tripathi, N.; Hubballi, N. "Detecting stealth DHCP starvation attack using machine learning approach." Journal of Computer Virology and Hacking Techniques 14(3):233â€“244, 2018. https://doi.org/10.1007/s11416-017-0310-x
7. Hubballi, N.; Tripathi, N. "A closer look into DHCP starvation attack in wireless networks." Computers & Security 65:387â€“404, 2017. https://doi.org/10.1016/j.cose.2016.10.002
8. Mohammed, N.H.; Salem, N.; Rahouma, K. "Detection and Mitigation of Stealth DHCP Attack in SDN network." 2025. https://journals.ekb.eg/article_425639_24191c47a8c2e7d858670bec2477fd44.pdf
9. Mukhtar, H. et al. "Mitigation of DHCP starvation attack." Computers & Electrical Engineering, 2012. https://doi.org/10.1016/j.compeleceng.2012.03.001
