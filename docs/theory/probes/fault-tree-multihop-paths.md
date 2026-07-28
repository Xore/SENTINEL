# Fault-Tree Analysis for Multi-Hop Network Paths
## New Research Backlog Topic — Basis for path-level availability modeling in RCA pipeline

> **Status:** Research document, newly added to the backlog alongside adaptive thresholding and high-cardinality storage.
> **Scope:** Modeling the availability/reliability of a multi-hop path (client → access point → router → WAN → VPN tunnel → target) as a combinatorial structure of component failures, to support root-cause localization when an end-to-end check fails but the specific failing hop is unknown.

---

## Part 1 — Why This Is Needed

The project's roadmapped multi-hop tracing (`mtr`-based hop tracking, already implemented in the standalone `monitor/`; not yet in `collector/`) currently reports per-hop RTT/loss but has no formal model connecting "which hop degraded" to "what is the resulting end-to-end failure probability," and no systematic way to enumerate the combinations of hop failures (e.g., primary link down but VPN tunnel still routes via backup) that could produce an observed outage. Fault Tree Analysis (FTA) is the standard engineering technique for exactly this: a top-down deductive method that models a system-level failure (the "top event") as a Boolean combination — AND/OR gates — of lower-level component failures ("basic events"), originally developed for aerospace/nuclear reliability and required by the FAA and US Nuclear Regulatory Commission for safety-critical systems (NRC Fault Tree Handbook, NUREG-0492).

### 1.1 Why FTA Rather Than Just Reliability Block Diagrams (RBDs)

FTA and Reliability Block Diagrams are mathematically dual (a series RBD path corresponds to an AND gate; a parallel/redundant RBD path corresponds to an OR gate), so either notation can express the same multi-hop-path reliability model (Ahmed, Hasan & Pervez, arXiv:1612.08910, "Reliability Modeling and Analysis of Communication Networks"). FTA is preferable here specifically because its top-down, "what combination of failures causes THIS observed outage" framing matches the RCA pipeline's actual query direction (starting from an observed symptom and working backward to a cause), whereas RBDs are typically constructed bottom-up from a known topology to predict overall availability.

---

## Part 2 — Core FTA Mechanics Applicable to a Network Path

### 2.1 Minimal Cut Sets

The standard quantitative FTA procedure (Ahmed et al., 2016, §3.1.2) is: (1) construct the fault tree from the path topology, (2) assign a failure probability to each basic event (hop/component), (3) identify **minimal cut sets** — the smallest combinations of basic-event failures that are together sufficient to cause the top event, and (4) compute the top event's failure probability from the cut sets:

\[
P(\text{top event}) = P\left(\bigcup_{i \in I} A_i\right)
\]

where \(A_i\) are the minimal cut set events. For a simple series path (every hop must be up for end-to-end success), each hop failure is itself a minimal cut set of size 1 (single point of failure). For a path with redundant routed uplinks, the cut set for that segment requires *both* the primary and fallback to fail simultaneously.

### 2.2 Mapping the Project's Actual Path Segments to Fault-Tree Gates

| Path segment | Gate type | Rationale |
|---|---|---|
| Client NIC → access point/switch → router → WAN uplink | AND (series) | Each is a genuine single point of failure per the current topology; any one hop down fails the whole path |
| Primary vs. fallback routed uplink (if configured) | OR (parallel/redundant) | Path only fails if both fail |
| DNS resolution vs. direct-IP fallback (if the collector supports both) | OR | Analogous redundancy |
| Target-side reachability (final hop to the monitored device/service) | AND (series, terminal) | No redundancy modeled at the target end |

This table should be treated as a starting taxonomy, not a final answer — it needs to be validated against the project's actual documented network topology (per `docs/07-network-map-and-monitoring-roadmap.md`) before being encoded as a fixed fault-tree structure in code.

### 2.3 Dynamic Fault Trees for Sequence-Dependent Failures

Static FTA (AND/OR gates only) cannot express failures where the *order* of events matters — e.g., "the fallback route only fails if the primary already failed AND THEN the fallback subsequently also fails," as opposed to both failing independently. This requires **Dynamic Fault Trees (DFTs)**, which add gates such as Priority-AND (PAND) and Sequence-Enforcing gates specifically to capture such ordered dependencies (Ahmed et al., 2016, §3; MDPI 2024, "Dynamic Fault Tree Generation and Quantitative Analysis... for Embedded Systems"). When routed-uplink failover is sequence-dependent (primary must fail before fallback engages), model it as a **dynamic**, not static, fault tree using a PAND gate for the primary-then-fallback relationship rather than approximating it with a plain OR gate.

### 2.4 Quantification Methods

Once minimal cut sets are identified, three standard computation approaches exist (survey by van Ras et al., "Fault tree analysis: A survey of the state-of-the-art in modeling, analysis and tools," University of Twente):
1. **Combinatorial/algebraic** (closed-form probability formulas from cut sets) — fastest, but only exact for static trees.
2. **Markov-chain-based** — needed once repair/recovery is modeled (a hop that fails and later self-heals, e.g. DHCP lease renewal or BGP reconvergence), which is directly relevant since most of this project's failures are transient rather than permanent.
3. **Monte Carlo simulation** — generates random failure/repair times per the assigned distributions and simulates the system, recording empirical availability; recommended when gate logic is too complex (e.g. many DFT gates) for closed-form or Markov solutions to remain tractable (Durga Rao et al., cited in the Twente survey).

Given the presence of self-healing/transient failures (DHCP renewal, BGP convergence, and routed-uplink failover) throughout this project's actual failure modes, **Markov-chain-based quantification is the more appropriate starting method** over pure combinatorial FTA, consistent with how `docs/segment-health-arp-dhcp-theory.md` already treats DHCP/ARP health as time-varying rather than a fixed pass/fail state.

---

## Part 3 — Integration With the Existing RCA Pipeline

The fault tree's minimal cut sets are directly usable as **candidate hypotheses** for the causal-inference/RCA pipeline (`docs/rca-causal-inference.md`): when an end-to-end check fails, the RCA engine should evaluate each minimal cut set against the currently observed per-hop telemetry (MTR hop RTT/loss, interface/link state, and DHCP lease state) and rank candidate root causes by which cut set is most consistent with the observed per-hop evidence, rather than the RCA pipeline needing to independently rediscover the path's failure structure from scratch on every incident.

---

## Part 4 — Implementation Checklist

| Item | File | Status |
|---|---|---|
| Enumerate the project's actual path topology and map segments to AND/OR/PAND gates (§2.2) | new design doc, cross-referencing `docs/07-network-map-and-monitoring-roadmap.md` | Add when building |
| Model sequence-dependent routed-uplink failover as a dynamic (PAND) fault tree, not static OR | network-path topology contract | Add when building |
| Choose Markov-chain quantification over pure combinatorial FTA given transient/self-healing failure modes | RCA pipeline design | Add when building |
| Feed minimal cut sets into the RCA pipeline as ranked candidate hypotheses | `docs/rca-causal-inference.md` pipeline | Cross-check on implementation |

---

## References

1. U.S. Nuclear Regulatory Commission. "Fault Tree Handbook" (NUREG-0492). https://www.nrc.gov/docs/ML1007/ML100780465.pdf
2. Ahmed, W.; Hasan, O.; Pervez, U. "Reliability Modeling and Analysis of Communication Networks." arXiv:1612.08910. https://arxiv.org/pdf/1612.08910.pdf
3. van Ras, C. et al. "Fault tree analysis: A survey of the state-of-the-art in modeling, analysis and tools." University of Twente. https://ris.utwente.nl/ws/files/13291952/FTA_overview.pdf
4. MDPI Sensors. "Dynamic Fault Tree Generation and Quantitative Analysis of System Reliability for Embedded Systems Based on SysML Models." 2024. https://www.mdpi.com/1424-8220/24/18/6021
5. NASA / Nottingham repository. "Fault Tree Analysis Including Component Dependencies." ESREL 2022. https://nottingham-repository.worktribe.com/preview/10916493/
