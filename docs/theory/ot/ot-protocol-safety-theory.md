# OT Protocol Safety & Passive Fingerprinting Theory
## Academic Research for `collector/checks/ot_snmp.py` (new), `collector/checks/ot_modbus.py` (new), and OT Discovery in `SUGGESTIONS.md` §6

> **Status:** Research document — fills the gap flagged in `docs/gap-analysis/research-guide-for-gap-topics.md` Â§3 ("OT Protocol Checks"), which is listed as a required research gate but, unlike the other gated phases (MDP scheduler, probe-budget allocation, eBPF), had no dedicated academic deep-dive alongside `docs/guides/05-research-and-decisions.md`'s short design notes.
> **Priority:** High — OT is the one domain in this project where an incorrect implementation choice (active scanning a fragile PLC) can cause a real-world safety or availability incident, not just a data-quality problem.

---

## Part 1 — Why Active Scanning Is Different in OT

### 1.1 The Core Safety Argument

Unlike IT networks, where active scanning (Nmap, PLCScan, Xprobe2-style probing) is standard practice, OT devices are frequently built on constrained embedded processors running real-time control loops with no spare cycles for handling malformed or unexpected packets. NIST SP 800-82 Rev.3 Â§6.2.1 explicitly cautions against active scanning in live ICS environments without vendor validation, because active scanners can overwhelm the limited processing capability of older PLCs, corrupt memory on legacy RTUs, or trigger unexpected behavior on safety-critical systems — documented real-world incidents, not theoretical risk. This is the same caution already reflected in `docs/guides/05-research-and-decisions.md`'s note that OPC-UA `FindServers`/`GetEndpoints` requires separate approval, and in `docs/gap-analysis/research-guide-for-gap-topics.md` Â§3.2's hard gate on active OT queries — this document supplies the underlying standards citation those notes were missing.

### 1.2 IEC 62443's Passive-First Posture

IEC 62443-3-2 Â§4.2 (security risk assessment / system partitioning) formalizes passive asset discovery — deploying a passive tap or SPAN port and fingerprinting devices purely from observed traffic — as the correct default technique for building an OT asset inventory, precisely because it never injects a single packet into the OT network. This maps directly onto the collector's existing design choice (already noted in `docs/guides/05-research-and-decisions.md`) to "prefer passive identification from captured S7/PROFINET traffic" and defaults to TCP reachability rather than active discovery calls. IEC 62443-3-3's seven Foundational Requirements (FR1â€“FR7) are also directly relevant here: **FR7 (Resource Availability)** treats availability as a security property in its own right for OT — meaning a monitoring agent that degrades a PLC's availability by probing it is itself a security violation under the standard, not merely a bug.

### 1.3 Zones, Conduits, and What This Means for a Single Collector

IEC 62443-3-2 Â§4.3 defines the zone/conduit model: OT assets are grouped into zones sharing a security level, and every communication path between zones (a "conduit") must be explicitly documented and controlled. For this project, the practical implication is that **the collector itself is a conduit endpoint** whenever it queries any OT-zone device, even read-only. This means the collector's OT polling configuration should be treated as part of the documented conduit inventory, not as an incidental monitoring detail — worth a short addition to `docs/guides/05-research-and-decisions.md`'s OT section.

---

## Part 2 — Passive Protocol Fingerprinting (The Preferred Technique)

### 2.1 Port-Based Fingerprinting Is Not Sufficient

Wellman (2023, Boise State University, "Improvements to Passive Fingerprinting of Operational Technology Environments") shows that existing passive fingerprinting tools (p0f, GrassMarlin) and even DPI-based ones rely on protocols running on their default/expected port, and fail silently when a protocol is reconfigured to a nonstandard port — a real risk in legacy OT deployments where port remaps are common maintenance practice. The paper's `protoDetect` tool instead fingerprints protocols using **content-based signatures independent of port**:

| Protocol | Default Port | Fingerprint Signature |
|---|---|---|
| Modbus TCP | 502 | Protocol identifier `0x0000` + length field (combining both reduces false positives versus either alone) |
| S7Comm | 102 | Protocol identifier byte `0x32` in the header, layered on TPKT length field |
| DNP3 | 20000 | Protocol identifier + header CRC check |
| EtherNet/IP (CIP) | 44818 / UDP 2222 | Header identifier `0x00000000`; CRC was found most reliable overall |

**Implication for `collector/checks/ot_modbus.py` (new) and any future S7/DNP3/EtherNet-IP module:** do not assume the configured port is authoritative. Where feasible, validate the passively observed protocol signature against the configured port before issuing even a read-only query, so a misconfigured target does not receive an unexpected protocol's query.

### 2.2 Passive SCADA Fingerprinting Without Deep Packet Inspection

Jeon, Yun, Choi & Kim (2016, arXiv:1608.07679, "Passive Fingerprinting of SCADA in Critical Infrastructure Network without Deep Packet Inspection") demonstrate a complementary technique: instead of parsing protocol payloads, infer the SCADA topology (master server vs. field device roles) purely from traffic *shape* — connection persistence, direction, and periodicity — achieving near-perfect F-score (~1.0) on real month-plus network traces from critical infrastructure, with the one weak spot being HMIs connected to the master server (harder to distinguish from the master itself). This is a useful secondary signal for the collector: **a long-lived, low-jitter, periodic TCP connection to a given OT-segment IP is itself evidence that IP is a live field device**, without needing to parse any protocol content — directly usable as a lightweight pre-check before running any read-only query.

### 2.3 Transaction-Pattern Fingerprinting for Anomaly Baselines

Peng, Xiang, Gao, Chen & Ren (2015, ICCIP, "Industrial Control System Fingerprinting and Anomaly Detection") build normal-behavior fingerprints from HMIâ†’PLC transaction patterns (packet size, inter-arrival time, direction) captured passively, then flag anomalies as any deviation from these transaction patterns — a control-traffic-specific alternative to the Holt-Winters/CUSUM approach already specified in `docs/anomaly-detection-theory.md` for network-layer metrics. **Recommendation:** apply the same CUSUM/EWMA machinery already built for RTT/loss (per `anomaly-detection-theory.md`) to OT transaction inter-arrival time as an additional passive OT health signal, rather than building a separate bespoke anomaly system for OT traffic.

---

## Part 3 — Read-Only Active Polling: Constraints When Passive Isn't Enough

### 3.1 Why Active Polling Is Still Sometimes Necessary

Passive fingerprinting identifies *that* a device exists and its likely protocol/role, but the collector's stated goal (per `SUGGESTIONS.md` Â§6 and `ROADMAP.md` Phase 1f/1g) is health telemetry — register values, `sysUpTime`, interface counters — which generally requires an active GET/read. The roadmap's existing safeguards (FC01/FC03 read-only, hard-coded refusal of write function codes, 2000ms timeout, one request per target per cycle) are consistent with IEC 62443-3-3 FR7's availability-preservation intent, but the roadmap does not currently address **cumulative load across multiple collectors**, addressed next.

### 3.2 Multi-Collector Polling Load — The Open Question Flagged in the Research Guide

`docs/gap-analysis/research-guide-for-gap-topics.md` Â§3.4 explicitly flags multi-collector OT polling load as "currently unmodeled anywhere in the repo." Industry guidance on SCADA master/PLC bottlenecks (Industrial Monitor Direct, 2025, "SCADA Master PLC Bottleneck and TCP/IP Connection Limits for Large-Scale Deployments") documents a concrete real-world constraint: a MicroLogix 1400 used as a SCADA master exposed only a **16 outbound TCP connection limit** and a single Ethernet port, which caused excessive poll times once more than 75 remote sites were polled through it — the failure mode was not a crash but a silent, cumulative slowdown of poll cycles across all clients sharing that limit.

**Implication for the collector:** if two or more collector instances (e.g., a Raspberry Pi collector on a purely OT-facing segment plus a VPS-hosted aggregator that also reaches into the same OT zone through a conduit) poll the same Modbus/SNMP device, their connection counts are additive against that device's documented TCP connection-table limit — a limit that is frequently in the single digits to low tens for legacy PLCs, far below typical IT expectations. This is exactly the constraint `docs/gap-analysis/research-guide-for-gap-topics.md` Â§3.4 asks to have "a short written note once resolved"; this document supplies that note.

### 3.3 Concrete Mitigation for `ot_modbus.py` / `collector/checks/ot_snmp.py` (new)

```go
// Before enabling OT polling from more than one collector against the same
// target IP, compute:
//   total_concurrent_connections = sum(open_connections_per_collector)
// and confirm this stays below the target device's documented TCP connection
// limit (check vendor datasheet; legacy PLCs commonly support single-digit to
// low-tens concurrent connections — do not assume IT-scale limits).
//
// Practical mitigation if multiple collectors must observe the same OT device:
// designate exactly one collector as the "OT owner" for that device and have
// other collectors receive its readings via the aggregator instead of polling
// the PLC directly a second time. This avoids additive connection load
// entirely rather than trying to tune timeouts/backoff to fit under a limit
// that may not be documented accurately.
```

---

## Part 4 — BACnet-Specific Caveat

A 2026 NDSS paper ("BACnet or 'BADnet'? On the (In)Security of Implicitly [Trusted BACnet Communications]") examines security weaknesses specific to BACnet's implicit trust model in building-automation deployments. For this collector, the practical takeaway (consistent with the S7comm guidance already in `docs/guides/05-research-and-decisions.md`) is: an open BACnet port (UDP/IP 47808) proves reachability but not device identity or health, and BACnet's `Who-Is`/`I-Am` discovery broadcast should be treated with the same discovery-approval gate already applied to OPC-UA's `FindServers`/`GetEndpoints`, since it is likewise an active discovery mechanism rather than passive observation.

---

## Part 5 — Implementation Checklist

| Item | File | Status |
|---|---|---|
| Cite NIST SP 800-82 Rev.3 Â§6.2.1 and IEC 62443-3-2 Â§4.2 explicitly as the basis for passive-first OT posture | `docs/guides/05-research-and-decisions.md` | **Missing — add this** |
| Content-based protocol signature check (Modbus/S7/DNP3/EtherNet-IP) before querying, independent of configured port | `collector/checks/ot_modbus.py` (new) (new helper) | **Missing — add this** |
| Passive traffic-shape pre-check (long-lived periodic connection = likely live field device) before active polling | `collector/checks/ot_modbus.py` (new) / `collector/checks/ot_snmp.py` (new) | **Missing — add this** |
| Reuse CUSUM/EWMA anomaly machinery for OT transaction inter-arrival time, not a bespoke OT anomaly system | `collector/checks/ot_modbus.py` (new) + `backend/analyse/detector.py` cross-reference | **Missing — add this** |
| Multi-collector cumulative TCP-connection-limit accounting, with "single OT-owner collector" fallback | `collector/checks/ot_modbus.py` (new), `collector/checks/ot_snmp.py` (new), deployment docs | **Missing — add this (resolves `research-guide-for-gap-topics.md` Â§3.4 open question)** |
| Treat BACnet `Who-Is`/`I-Am` as a gated active-discovery mechanism, same as OPC-UA `FindServers` | `docs/guides/05-research-and-decisions.md` | **Missing — add this** |
| Explicit zone/conduit documentation entry for the collector itself as a conduit endpoint | `docs/guides/05-research-and-decisions.md` | **Missing — add this** |

---

## References

1. NIST SP 800-82 Rev.3. "Guide to Operational Technology (OT) Security." Â§6.2.1 (active scanning caution), Â§6.2.8 (OT monitoring architecture). NIST, 2023.
2. IEC 62443-3-2. "Security Risk Assessment for System Design." Â§4.2 (passive asset discovery), Â§4.3 (zones and conduits).
3. IEC 62443-3-3. "System Security Requirements and Security Levels." FR1â€“FR7 Foundational Requirements, especially FR7 (Resource Availability).
4. Wellman, L. "Improvements to Passive Fingerprinting of Operational Technology Environments." Boise State University, Cyber Operations and Resilience Program, 2023. https://scholarworks.boisestate.edu/cyber_gradproj/4
5. Jeon, S.; Yun, J.-H.; Choi, S.; Kim, W.-N. "Passive Fingerprinting of SCADA in Critical Infrastructure Network without Deep Packet Inspection." arXiv:1608.07679, 2016. https://arxiv.org/abs/1608.07679
6. Peng, Y.; Xiang, C.; Gao, H.; Chen, D.; Ren, W. "Industrial Control System Fingerprinting and Anomaly Detection." 9th International Conference on Critical Infrastructure Protection (ICCIP), 2015. https://doi.org/10.1007/978-3-319-26567-4_5
7. "SCADA Master PLC Bottleneck and TCP/IP Connection Limits for Large-Scale Deployments." Industrial Monitor Direct, 2025. https://industrialmonitordirect.com/blogs/knowledgebase/scada-master-plc-bottleneck-and-tcpip-connection-limits-for-large-scale-deployments
8. NDSS Symposium 2026. "BACnet or 'BADnet'? On the (In)Security of Implicitly Trusted BACnet Communications." https://www.ndss-symposium.org/wp-content/uploads/2026-s794-paper.pdf
9. OPC Foundation. OPC-10000-6 Â§7.6 (well-known discovery addresses); Part 2 Â§7.2 (discovery security) — cross-referenced from `docs/guides/05-research-and-decisions.md`.
10. Ollila, T. "Overview for capabilities of OT network monitoring tools." JAMK Thesis, 2024 — cross-referenced from `docs/gap-analysis/research-guide-for-gap-topics.md` Â§3.1.
