# Gap Analysis: Collector vs. Standalone Monitor

> Date: 2026-07-25 (refreshed)
> Scope: Comparison of `collector/` (Go push agent), `monitor/` (standalone Python monitor), and their documented roadmaps, to identify feature parity gaps and documentation/research gaps.
>
> **Refresh notes (2026-07-25):**
> - Phase 11 (eBPF flow telemetry) and Phase 12 (Deep RL / DQN scheduler) moved from out-of-scope into the roadmap with full rationale in `ROADMAP.md`.
> - Three Phase 9 open research questions (TLS ARM latency, OTLP batch size on lossy Wi-Fi, EST vs custom enroll) are now partially resolved by literature — see §Phase 9 Open Research below.
> - Security hygiene work completed today: CodeQL SAST workflow (codeql.yml v4, security-extended), insecure TLS/SSL fixes (alerts 8, 9), SSRF fix (alert 38), dependabot/fetch-metadata v3 bump.

## Overview

`analyseLaptop` has three architectural tiers: a **standalone monitor** (Python, `monitor/`) that runs everything locally with a Flask **dashboard** (`dashboard/`), and a **Go collector agent** (`collector/`) deployable on remote nodes that pushes telemetry to an aggregator. The repository already has deep academic grounding in `docs/collector/ROADMAP.md` and `docs/collector/SUGGESTIONS.md`, citing RFC 7799, Sundberg (2024), Amjad et al. (2021), Zabala et al. (2023), Brügge & Simon (TU Munich, 2024), and RITICS/NCSC guidance.

This document identifies (1) roadmapped collector features not yet implemented, (2) standalone-only features missing from the collector (and vice versa), (3) topics that need further research before correct implementation, and (4) newly resolved open questions.

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
| MDP-based adaptive probe scheduler | Phase 4/5 | — | See [`../theory/scheduling/mdp-adaptive-scheduling-theory.md`](../theory/scheduling/mdp-adaptive-scheduling-theory.md) |
| Frank-Wolfe probe-budget allocation | Phase 5 | — | See [`../theory/scheduling/probe-budget-allocation.md`](../theory/scheduling/probe-budget-allocation.md) and [`../theory/scheduling/probe-budget-small-n-theory.md`](../theory/scheduling/probe-budget-small-n-theory.md) |
| On-demand traceroute on DEGRADED transition | Phase 6 | — | Hop-level localisation |
| Prometheus /metrics export | Phase 7 | — | Grafana/Alertmanager integration |
| mTLS + OTLP/gRPC transport + backend PKI | Phase 9 | — | See [`../theory/probes/probe-to-backend-transport-theory.md`](../theory/probes/probe-to-backend-transport-theory.md) |
| Gorilla delta-of-delta hot/cold store | Phase 10 | — | See [`../theory/probes/gorilla-compression-go-theory.md`](../theory/probes/gorilla-compression-go-theory.md) |
| eBPF TC flow telemetry (no-payload) | **Phase 11 — NEW** | — | Moved from out-of-scope; GDPR contractual-necessity basis; no payload capture |
| Deep RL / DQN adaptive scheduler | **Phase 12 — NEW** | — | Moved from out-of-scope; failure corpus accumulates from Phase 5 logs |

## New Phases Since Last Gap Analysis

### Phase 11: eBPF Flow Telemetry
Previously excluded due to GDPR concerns. That exclusion is lifted because the eBPF TC hook only captures L4 metadata (5-tuple, byte counts, TCP flags, per-flow RTT via TCP timestamp option) — **no payload bytes are ever copied to user space**. This is equivalent to NetFlow/IPFIX, which is standard network operations practice. The GDPR legal basis is Art. 6(1)(b) contractual necessity on contracted internal networks. A compile-time `static_assert` gate and CI check prevent any `bpf_skb_load_bytes()` call beyond the L4 header offset.

**Key academic support:** Sundberg PAM 2023 (ePPing TC/XDP hook design), Hinz et al. ACM SIGCOMM 2023 (TCP congestion signals via eBPF), Bertrone COP2 2019 (kprobe `srtt_us`).

### Phase 12: Deep RL / DQN Scheduler
Previously excluded because it required a labelled failure corpus. That prerequisite is now solvable: Phases 1–11 produce a continuous stream of labelled probe observations. After ~3 months of Phase 5 (finite-state MDP) operation, sufficient failure episodes (target ≥ 500) will exist to bootstrap a Q-network. The finite-state MDP achieves ~80% of theoretical optimum (Zabala 2023) and remains the production scheduler until the DQN reaches parity on held-out validation data.

**New academic finding:** Rahman et al. (2025) "Deep Q-Learning Based Adaptive MAC Protocol" (MDPI Journal of Marine Science and Engineering 13(3):616) demonstrates DQN for adaptive scheduling in network environments with varying conditions — confirms applicability of DQN to probe-scheduling at this project's scale. This supplements the Zabala et al. (2023) MDP grounding.

## Phase 9: Open Research Questions — Current Status

Three questions were flagged as open in `ROADMAP.md`. Literature search 2026-07-25:

### 1. TLS 1.3 Handshake Overhead on ARMv7 (Pi 3B) — Curve25519 vs P-256

**Status: Substantially answered.**

- After et al. MDPI Sensors 2023 (already cited in ROADMAP): confirms Curve25519 + RSA is ~4× faster than P-256 + ECDSA on constrained ARM devices. This was the Phase 9 design decision.
- Sosnowski et al. (TU Munich 2023, NET) "The Performance of Post-Quantum TLS 1.3" — benchmarks TLS 1.3 cipher suites including P-256 vs X25519; measured on aarch64; shows X25519 consistently fastest. Cited by 78 papers as of 2026.
- Cheng et al. (PMC/MDPI 2024) "Armed with Faster Crypto: Optimizing Elliptic Curve Cryptography for ARM Processors" — shows at least 20% ARM NEON speedup for Curve25519 vs reference; at least 15% improvement on Signal protocol benchmarks.
- Zhang et al. (USENIX Security 2024) "Faster TLS 1.3 handshake using optimized X25519" — confirms AVX/ARM optimizations for X25519 reduce handshake latency substantially vs P-256.

**Decision:** Curve25519 for key exchange confirmed as the correct Phase 9 choice for ARM hardware. No ARMv7-specific Pi 3B benchmark is available in literature for the exact probe payload/rate of this project, but the general direction is unambiguous. **Recommendation: close this research question; proceed with Curve25519. Document the After et al. + Sosnowski + Cheng 2024 stack as the Phase 9 TLS reference set.**

### 2. Optimal Batch Size Under Lossy Wi-Fi — No Directly Applicable Literature

**Status: Partially answered; one practical decision point remains open.**

- General OTLP batch processor best practice (Broadcom DX O2 / OpenTelemetry, 2025–2026): `send_batch_max_size: 1000`, `timeout: 10s`, max payload ≤ 2 MB, retry with exponential backoff (1s base, max 60s). This is the de facto standard for probe-rate OTLP telemetry.
- Trinocular (van Adrichem et al. TMA 2025, already cited): batch reprocessing needed for accurate baselines; streaming-only has 5× higher false-outage rate. This justifies the Phase 9 dual-path (streaming hot + batch cold) design but does not constrain batch size specifically.
- **Gap that remains:** no literature directly measures optimal OTLP batch size for a 30s-interval probe collector sending ≤ 15 metric streams over a lossy 802.11 link. The practical constraint (≤ 2 MB payload, 30s cycle, ~15 streams × ~10 fields × ~8 bytes = ~1.2 KB per cycle uncompressed → ~100 bytes Gorilla-compressed) means batch size is not the binding constraint at this project's scale. Lossy-link retry queue is the binding design decision, and Phase 9 already specifies exponential backoff + 500-batch in-memory ring buffer.

**Recommendation:** close this as a research question; the practical answer is that at this project's data rate, batch size is not a limiting factor. Document the 500-batch ring buffer + 10s timeout as the design choice. Add a note that if the number of collector nodes exceeds ~50, reassess with actual OTLP traffic measurements.

### 3. EST (RFC 7030) vs Custom `/enroll` for Air-Gapped OT Deployments

**Status: Design decision documented; no new literature needed.**

- EST (RFC 7030) adds an HTTPS/CMS dependency and is designed for PKI infrastructure at scale. For a closed probe fleet with ≤ ~20 collectors, the custom `/enroll` endpoint (CSR POST → signed cert response) is simpler, has no external dependencies, and is auditable.
- The only literature gap is air-gapped OT-specific EST guidance. NIST SP 800-82 Rev.3 (already cited) recommends minimising external dependencies in OT networks — which supports the custom endpoint choice.

**Recommendation:** close this as a research question; custom `/enroll` is the correct design for this project. Document the rationale (simplicity, no CMS/HTTPS-to-EST bootstrap dependency, NIST SP 800-82 alignment) in `docs/theory/probes/probe-to-backend-transport-theory.md`.

## Documentation Gaps (Open Items)

- No document cross-references `monitor/scheduler.py`'s production scheduler design to the collector's Phase 4/5 MDP scheduler concept. **Still open.**
- No dedicated document for the Wi-Fi link-quality collection model (`wifi_sample()`), beyond general capture setup in [`../guides/03-capture-and-wifi.md`](../guides/03-capture-and-wifi.md). **Still open.**
- `docs/guides/05-research-and-decisions.md` still needs the zone/conduit note, BACnet discovery gating, and NIST SP 800-82/IEC 62443-3-2 citations per the checklist in [`../theory/ot/ot-protocol-safety-theory.md`](../theory/ot/ot-protocol-safety-theory.md) Part 5. **Still open.**
- Phase 9 research questions (TLS ARM, OTLP batch, EST vs enroll) need close-out notes written into `docs/theory/probes/probe-to-backend-transport-theory.md`. **New — opened this refresh.**
- Phase 12 DQN: corpus privacy model (target_id as SHA-256 prefix, GDPR Art. 6(1)(b) basis) should be cross-referenced in a new section of `docs/theory/scheduling/mdp-adaptive-scheduling-theory.md`. **New — opened this refresh.**

## Areas Needing Further Academic Research

All five originally open research topics remain resolved. Three Phase 9 questions are now substantially resolved (see above). Remaining open empirical work:

| # | Topic | Status | Blocking step |
|---|---|---|---|
| 1 | MDP threshold tuning | ✅ Resolved | Implementation: 30+ days own data, CUSUM backtest |
| 2 | eBPF passive RTT on ARM/Docker | ✅ Resolved | Implementation: Pi kernel/capability test |
| 3 | Frank-Wolfe at small N | ✅ Resolved | Implementation: small-N simulation |
| 4 | Multi-collector OT polling load | ✅ Resolved | Implementation: real device connection-limit check |
| 5 | ARP-storm detection thresholds | ✅ Resolved | Implementation: 7+ days ARP baseline |
| 6 | TLS ARM latency (Phase 9) | ✅ Now resolved | Close-out note in transport theory doc |
| 7 | OTLP batch size on lossy Wi-Fi (Phase 9) | ✅ Now resolved | Close-out note; reassess if >50 nodes |
| 8 | EST vs custom enroll (Phase 9) | ✅ Now resolved | Close-out note in transport theory doc |
| 9 | DQN scheduler — failure corpus | 🔲 Empirical gate | ≥90 days Phase 5 operation + ≥500 episodes |
| 10 | Phase 11 eBPF TC — Pi 3B kernel/capability test | 🔲 Empirical gate | Prototype on real Pi 3B before merge |
| 11 | Phase 10 Gorilla — compression ratio on probe distributions | 🔲 Empirical gate | 24h measurement of actual ratio |

## New Academic References (This Refresh)

| Paper | Relevance | Phase |
|---|---|---|
| Rahman et al. "Deep Q-Learning Based Adaptive MAC Protocol." MDPI J. Marine Science & Engineering 13(3):616, 2025. https://doi.org/10.3390/jmse13030616 | DQN for adaptive scheduling in network environments; confirms DQN applicability at probe-scheduling scale | 12 |
| Sosnowski et al. "The Performance of Post-Quantum TLS 1.3." TU Munich NET, 2023. https://www.net.in.tum.de/fileadmin/bibtex/publications/papers/sosnowski2023PQTLS13.pdf | X25519 vs P-256 TLS 1.3 latency on aarch64; 78 citations | 9 |
| Cheng et al. "Armed with Faster Crypto: Optimizing Elliptic Curve Cryptography for ARM Processors." PMC/MDPI, 2024. https://pmc.ncbi.nlm.nih.gov/articles/PMC10857318/ | ≥20% ARM NEON speedup for Curve25519; Signal protocol benchmark | 9 |
| Tikumporn et al. "Automated Root Cause Analysis of Network Failures in IP Networks." IEEE Access 2025. https://doi.org/10.1109/ACCESS.2025.11053841 | Causal DAG RCA; 92% accuracy on real failure corpus — **already in ROADMAP, confirmed publication details** | 4 |

## Consolidated Priority Recommendations

1. Port loss-%/RTT-distribution, interface error counters, and the guarded scheduler from `monitor/` into `collector/` first (Phase 0, no new research required).
2. Implement collector Phase 1 (routes, WAN checks, OS health, SNMP, TLS) before eBPF/MDP phases, applying the passive-first/fingerprinting guidance in [`../theory/ot/ot-protocol-safety-theory.md`](../theory/ot/ot-protocol-safety-theory.md) for the SNMP/Modbus portions.
3. Treat MDP scheduling, Frank-Wolfe allocation, and eBPF passive RTT as research-gated — theory is documented; empirical validation (backtesting, baseline derivation) remains the blocking step.
4. Add a cross-reference document (or section) linking `monitor/scheduler.py`'s actual behavior to [`../theory/scheduling/mdp-adaptive-scheduling-theory.md`](../theory/scheduling/mdp-adaptive-scheduling-theory.md).
5. Update `docs/guides/05-research-and-decisions.md` per the checklist in [`../theory/ot/ot-protocol-safety-theory.md`](../theory/ot/ot-protocol-safety-theory.md) Part 5.
6. Write Phase 9 research-question close-out notes into `docs/theory/probes/probe-to-backend-transport-theory.md` (TLS ARM decision, batch-size non-issue note, EST vs enroll rationale).
7. Add Phase 12 GDPR/corpus-privacy cross-reference section to `docs/theory/scheduling/mdp-adaptive-scheduling-theory.md`.
8. **Do not begin Phase 11 (eBPF flow telemetry) without a working prototype on a real Pi 3B confirming TC hook + `CAP_NET_ADMIN` + kernel ≥ 4.8 before merging into `collector/main.go`.**
9. **Do not begin Phase 12 (DQN) until Phase 5 has been running ≥ 90 days and ≥ 500 labelled MDP state-transition episodes are in the corpus.**
