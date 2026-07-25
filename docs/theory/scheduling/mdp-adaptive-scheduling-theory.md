# MDP Adaptive Probe Scheduling Theory
## Academic Research for `collector/` Phase 4/5 Implementation

> **Status:** Research document — feeds directly into the collector's Phase 4 (MDP adaptive scheduler) and Phase 5 (probe-budget allocation) described in `collector/ROADMAP.md`.
> **Priority:** High — the finite-state approximation currently sketched in `ROADMAP.md` uses hard-coded thresholds (loss>1%, rtt_p95>2x baseline) that are not yet derived from the underlying theory or validated against real failure data. This document closes that gap, matching the depth of the sibling documents `docs/anomaly-detection-theory.md`, `docs/probe-budget-allocation.md`, and `docs/icmp-probe-design.md`.

---

## Part 1 — Why Fixed-Interval Polling Is Provably Suboptimal

### 1.1 The Core Trade-off

Every active-probing monitoring agent faces the same trade-off: probing more frequently reduces detection latency but increases overhead (CPU, bandwidth, and â€” for OT targets â€” unacceptable load on fragile devices). Cohen et al. (2013, arXiv:1302.0792, "Probe Scheduling for Efficient Detection of Silent Failures") formalize this as a scheduling optimization problem and prove that computing the truly optimal *stochastic* probe schedule (minimizing expected detection time subject to a probe-budget constraint) is **NP-hard** in general, but that a restricted class called **memoryless schedules** (where each target's next-probe time is drawn i.i.d. from a fixed distribution) can be computed efficiently via convex programming (for average-detection-time objectives) or linear programming (for worst-case objectives), and are provably close to the NP-hard optimum.

Mahmoody, Kornaropoulos & Upfal (2015, arXiv:1509.02487, "Optimizing Static and Adaptive Probing Schedules for Rapid Event Detection") extend this to the case where nothing is known in advance about each target's failure rate, showing an **adaptive algorithm that starts with no prior information and converges to the optimal memoryless schedule** by learning from observed data — directly analogous to what the collector's RTT-baseline EMA (`RTTBaseline = 0.9*RTTBaseline + 0.1*rtt_p95`) is already attempting empirically, but without the formal convergence guarantee this paper provides.

**Implication for the collector:** fixed 30-second uniform polling is a special case of a memoryless schedule with equal probe probability for every target regardless of its actual failure risk â€” exactly the case both papers prove is dominated by adaptive, risk-weighted schedules.

### 1.2 The MDP Formulation (Zabala, Doncel & Ferro, 2023)

The collector roadmap's primary citation, Zabala, L.; Doncel, J.; Ferro, A. "Optimality of a Network Monitoring Agent and Validation in a Real Probe." *Mathematics* 11(3):610, 2023 (https://doi.org/10.3390/math11030610; full text: https://addi.ehu.es/bitstream/handle/10810/59783/mathematics-11-00610-v3.pdf), models the monitoring agent itself as a constrained resource: a **single-processor system represented as a two-tandem-queue model with a moving server**, formulated as a **three-dimensional, continuous-time MDP**. The state is the pair of queue lengths (packets waiting to be captured, packets waiting to be analyzed) plus the current position of the processor; the action at each decision epoch is which of the two queues to serve; the reward is 1 unit each time a packet completes analysis (i.e., the objective is to maximize analysis throughput, not literally to minimize detection latency directly).

The paper solves this with the standard **value-iteration algorithm**:

```
V_i(s) = max_a { R_a(s) + sum_s' p_a(s,s') * V_{i-1}(s') }
```
repeated until convergence, yielding an optimal policy. Critically, the resulting **optimal policy is proven to be a threshold-type policy**: the processor should switch from capturing to analyzing (or vice versa) once queue occupancy crosses a threshold that depends on the current state, not on a fixed schedule. The paper validates this threshold policy against a real Linux-based probe and shows the real system's throughput closely tracks the theoretical optimum.

**Important correction versus the current roadmap wording:** Zabala et al.'s MDP is about **resource allocation within a single probe process** (capture vs. analysis contention on one CPU), not directly a *multi-target reachability scheduler* choosing which remote host to ping next. The collector's Phase 4 finite-state design (STABLE/SUSPECT/DEGRADED/DOWN per target) is a reasonable **practical analogy** — it borrows the *threshold-policy* insight (switch behavior based on a state threshold, not a fixed timer) — but it is not a literal implementation of Zabala's queueing MDP. This distinction should be made explicit in `ROADMAP.md` to avoid overstating the direct applicability of the citation.

### 1.3 The Multi-Target Reachability-Scheduling Literature (Closer to the Collector's Actual Problem)

The collector's actual problem — "given N remote targets and a fixed total probe budget, which target do I probe next to minimize detection latency for any of them" — is precisely the problem studied by Cohen et al. (2013) and Mahmoody et al. (2015) above, and is also the practical framing used by Amjad et al. (2021) (already cited in `docs/probe-budget-allocation.md`). These are a better direct theoretical basis for Phase 4/5 than the Zabala paper alone, and should be cited alongside it.

---

## Part 2 — Deriving the Finite-State Scheduler From Theory

### 2.1 Why a 4-State Machine Is a Reasonable Discretization

The MDP/POMDP framing (Zabala 2023; the sensor-scheduling survey by Dey & Shi, IEEE Comm. Surveys & Tutorials, 2015, "Markov Decision Processes With Applications in Wireless Sensor Networks: A Survey") treats target health as a hidden state that must be inferred from noisy probe outcomes, and the goal is to choose a *sampling policy* (how often to probe) as a function of the belief about that state. The full Bayesian belief state is continuous; the collector's roadmap's four discrete states (STABLE, SUSPECT, DEGRADED, DOWN) can be justified as a **coarse quantization of the belief-over-health state** rather than an arbitrary heuristic — this is consistent with how the health-monitoring MDP literature (Dey & Shi 2015; the ACM "Markov decision processes for control of a sensor network-based health monitoring system" work, IAAI 2005) discretizes patient/sensor criticality into a handful of tiers to keep the policy tractable, rather than solving the full continuous-belief MDP online.

### 2.2 Threshold Derivation — What the Roadmap Currently Lacks

The roadmap's transition rule `STABLE -> SUSPECT if loss > 1% OR rtt_p95 > 2x baseline` is currently an **assumed constant**, not a value derived from a specific target or from data. Two theoretically grounded ways to derive it:

**A. CUSUM/EWMA-consistent thresholding (reuse existing anomaly-detection-theory.md work).** Because `docs/anomaly-detection-theory.md` already derives CUSUM ARL tables for exactly this kind of shift-detection problem (k_s=0.5, h_s=5 gives ARL0â‰ˆ931 intervals, ARL1â‰ˆ3.8 intervals at a 2Ïƒ shift), the STABLEâ†’SUSPECT transition should be **defined as a CUSUM alarm on the RTT/loss residual**, not as an independent ad hoc rule. This directly reuses the already-validated ARL framework instead of introducing a second, uncalibrated threshold system. Concretely: `STABLE -> SUSPECT` should fire when the CUSUM statistic `C+_t` (per `anomaly-detection-theory.md` Â§2.2) exceeds `h_s`, using per-metric Ïƒ estimated via MAD as already specified there.

**B. Probe-scheduling regret bound (Mahmoody et al. 2015).** The paper gives explicit competitive-ratio bounds for adaptive memoryless schedules relative to the optimum; these can be used to size the SUSPECT probe-acceleration factor (currently a hard-coded `/6`) so that the *worst-case* additional detection delay introduced by not probing every target continuously stays within a provable bound, rather than an arbitrarily chosen divisor.

### 2.3 Empirical Validation Requirement (Unavoidable)

Both Zabala et al. (2023) and Mahmoody et al. (2015) emphasize that their theoretical schedules were **validated against real captured data / real probes**, not deployed on assumed parameters. The collector roadmap should follow the same discipline: before shipping Phase 4, backtest the CUSUM-derived STABLEâ†’SUSPECT threshold (Â§2.2A above) against at least 30 days of the standalone monitor's historical `ping_samples`/`events` tables, exactly as already scoped in `docs/research-guide-for-gap-topics.md` Â§4.2â€“4.4. This document supplies the missing theoretical justification for *why* CUSUM-based thresholds are preferable to arbitrary constants; the research guide supplies the *validation procedure*.

---

## Part 3 — Connecting to Probe-Budget Allocation (Phase 5)

Once a target enters SUSPECT/DEGRADED, Phase 5's Frank-Wolfe-approximated budget allocation (already detailed in `docs/probe-budget-allocation.md`) determines *how much* extra probing that target receives relative to others under a global budget. The theoretical link between Phase 4 and Phase 5 is that Phase 4's finite states are effectively a discretized version of the same "uncertainty" signal that Phase 5 uses continuously via rolling RTT variance (Welford's algorithm, per `ROADMAP.md` Phase 5). Both should be described as two views of one underlying quantity — uncertainty about target health — rather than as unrelated mechanisms, so a future refactor could unify them into a single variance-driven scheduler instead of maintaining two parallel probe-rate-adjustment mechanisms.

---

## Part 4 — Implementation Checklist

| Item | File | Status |
|---|---|---|
| Cite Cohen et al. (2013) and Mahmoody et al. (2015) alongside Zabala et al. (2023) in `ROADMAP.md` Phase 4 | `collector/ROADMAP.md` | **Missing — add this** |
| Clarify that Zabala et al. models single-processor capture/analysis contention, not multi-target reachability scheduling | `collector/ROADMAP.md` | **Missing — add this** |
| Replace ad hoc `loss>1% OR rtt_p95>2x` rule with CUSUM-alarm-based transition (reusing `anomaly-detection-theory.md` Â§2.2 parameters) | `collector/main.go` (Phase 4 state machine) | Specified here — needs implementation |
| Backtest CUSUM-derived thresholds against 30+ days of `monitor/` historical data before enabling in production | N/A (validation step) | Already scoped in `docs/research-guide-for-gap-topics.md` Â§4 |
| Document the shared "uncertainty" interpretation linking Phase 4 states and Phase 5 variance weights | `collector/ROADMAP.md` | **Missing — add this** |

---

## References

1. Zabala, L.; Doncel, J.; Ferro, A. "Optimality of a Network Monitoring Agent and Validation in a Real Probe." *Mathematics* 11(3):610, 2023. https://doi.org/10.3390/math11030610
2. Cohen, E.; Hassidim, A.; Kaplan, H.; Mansour, Y.; Raz, D.; Tzur, Y. "Probe Scheduling for Efficient Detection of Silent Failures." arXiv:1302.0792, 2013. https://arxiv.org/abs/1302.0792
3. Mahmoody, A.; Kornaropoulos, E.M.; Upfal, E. "Optimizing Static and Adaptive Probing Schedules for Rapid Event Detection." arXiv:1509.02487, 2015. https://arxiv.org/abs/1509.02487
4. Dey, S.; Shi, L. et al. "Markov Decision Processes With Applications in Wireless Sensor Networks: A Survey." IEEE Communications Surveys & Tutorials, 2015. https://doi.org/10.1109/COMST.2015.2420686
5. "Markov decision processes for control of a sensor network-based health monitoring system." IAAI 2005 / ACM Digital Library. https://dl.acm.org/doi/10.5555/1620092.1620105
6. Amjad, M.J. et al. "Optimal Probing with Statistical Guarantees for Network Monitoring at Scale." arXiv:2109.07743, 2021 (cross-referenced via `docs/probe-budget-allocation.md`).
