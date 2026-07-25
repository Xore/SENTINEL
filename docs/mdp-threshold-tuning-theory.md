# MDP Adaptive Scheduler: State-Transition Threshold Tuning
## Research Backlog Item — Gap #2 from `docs/gap-analysis-collector-vs-standalone.md`

> **Status:** Research document. Addresses how to set and validate the STABLE/SUSPECT/DEGRADED/DOWN transition thresholds in `docs/mdp-adaptive-scheduling-theory.md` without a network-specific reward function to optimize against.
> **Scope:** Why exact MDP/POMDP reward-based threshold optimization is unlikely to be tractable for a single small network, what the adaptive-polling and control-theory literature offers instead, and a concrete hysteresis-based tuning procedure grounded in this project's own historical data.

---

## Part 1 — Why This Is Genuinely an Open Problem, Not Just an Unset Config Value

The existing `docs/mdp-adaptive-scheduling-theory.md` frames per-target monitoring state (STABLE, SUSPECT, DEGRADED, DOWN) as an MDP/POMDP state-estimation problem, following the general pattern used in sensor-scheduling literature: a controller observes noisy signals (RTT, loss) and must decide both a state estimate and a sampling-rate action, trading detection latency against probe cost [web:69][web:353]. This framing is well-supported — MDP-based adaptive sampling for exactly this trade-off (health criticality vs. probe/battery cost) has prior art in sensor-network health monitoring [web:69] and general POMDP theory formalizes the belief-update step needed when the true state (genuinely down vs. transient blip) is not directly observable [web:358][web:352].

However, the literature that *derives* optimal thresholds analytically (e.g., via dynamic programming over a Markov reward model, per [web:339]'s Markovian-dynamics predictability analysis, or a POMDP value-iteration solve) universally requires a specified reward/cost function and known or estimable transition probabilities for the specific network being modeled [web:342][web:346]. Neither of these is available a priori for an arbitrary home-lab or small-business network monitored by this project — the "cost of missing an outage" vs. "cost of an extra probe" trade-off is a subjective, deployment-specific judgment call, not a value derivable from first principles. This confirms the gap analysis's original framing was correct: there is no literature shortcut that removes the need for empirical, network-specific tuning.

---

## Part 2 — What the Literature Offers Instead of Exact Optimal Thresholds

### 2.1 Two-Phase / Affine Threshold Policies Are the Established Practical Compromise

Recent adaptive-polling theory (Avrachenkov et al., 2025, on Markovian switching policies) shows that broad classes of *affine, threshold-based* switching policies — not full POMDP value-iteration solutions — can achieve the Pareto frontier of performance trade-offs in polling systems with just two or a few tunable parameters, and that sweeping those parameters traces out the full space of achievable operating points [web:353]. This directly supports the *shape* of the existing STABLE/SUSPECT/DEGRADED/DOWN threshold design (a small number of numeric thresholds on RTT/loss, rather than a full learned policy) as a reasonable and literature-consistent simplification of the exact POMDP — the open question is calibrating the specific threshold *values*, not the architectural choice of using thresholds at all.

### 2.2 Stability of the Overall System Does Not Depend on the Adaptive Mechanism, Only on Aggregate Load

A relevant and somewhat reassuring finding from adaptive-polling stability analysis: whether an adaptive polling/service rule improves things or not, the underlying stability condition of the system depends on the total load relative to capacity (e.g., \(\rho_0 = \sum_k \lambda_k/\mu_k < 1\)), not on the specific adaptive rule chosen [web:353]. Translated to this project: badly tuned MDP thresholds cannot cause the collector itself to become unstable (e.g., runaway probing) as long as the DOWN-state maximum polling rate is bounded — the risk of bad tuning is *detection-quality degradation* (missed or delayed outage detection, or excessive false alarms), not systemic instability. This narrows what validation needs to check.

### 2.3 The Core Practical Risk Is State Flapping, and the Standard Mitigation Is Hysteresis

Across both control theory and the adaptive-polling literature, the well-known failure mode of any threshold-based state machine driven by a noisy signal is **flapping**: the estimated state oscillates between two adjacent states (e.g., STABLE ↔ SUSPECT) because the underlying noisy metric crosses a single threshold repeatedly due to measurement noise rather than a genuine state change. The standard, long-established fix is **hysteresis**: using two distinct thresholds per transition — a higher one to enter a worse state and a lower one to return to a better state — so a single small fluctuation cannot immediately reverse the previous transition. This project's own `docs/anomaly-detection-theory.md` already specifies CUSUM/EWMA-based smoothing for anomaly detection; the MDP scheduler's state thresholds should adopt the same smoothing-plus-hysteresis pattern rather than acting on raw instantaneous RTT/loss samples, for consistency with infrastructure already validated elsewhere in this project.

---

## Part 3 — Concrete Tuning and Validation Procedure

Since no literature-derived threshold values transfer directly to an arbitrary network (Part 1), thresholds must be tuned empirically against this project's own historical data, following the same validation pattern already used for the anomaly-detection EWMA parameters and the Phase 4 MDP backtest referenced in `docs/research-guide-for-gap-topics.md` §4.2:

1. **Define the cost trade-off explicitly, even if subjectively**, before tuning: pick a target maximum acceptable detection latency for a genuine outage (e.g., "a DOWN target must be detected within 60 seconds") and a target maximum acceptable false-alarm rate (e.g., "no more than 1 spurious SUSPECT transition per target per day under normal conditions"). This makes the otherwise-implicit reward function explicit and auditable, even without solving a formal POMDP.
2. **Add hysteresis to every state transition** (§2.3): specify separate up-thresholds and down-thresholds for each STABLE→SUSPECT→DEGRADED→DOWN boundary, with the down-threshold set looser (i.e., requiring a larger improvement to step back down) than the up-threshold.
3. **Backtest against the same 30-day historical RTT/loss dataset** already scoped for the MDP backtest in the research guide, sweeping candidate threshold/hysteresis-gap pairs and measuring, for each candidate: (a) detection latency for every known real outage in the dataset, (b) count of spurious state transitions during periods with no known outage, and (c) total probe count consumed. Select thresholds on the Pareto frontier between (a) and (b)/(c), consistent with the two-phase policy framing in §2.1.
4. **Re-validate periodically per deployment**, not once globally — because Part 1 establishes that no single threshold set is transferable across networks with different baseline latency/jitter characteristics (e.g., a VPS-hosted collector monitoring WAN targets will have a very different baseline RTT distribution than a Raspberry Pi monitoring a home LAN), thresholds tuned on one collector's historical data should be treated as a starting point, not a final answer, when applied to a differently-characterized network segment.

---

## Part 4 — Relationship to Existing Project Documents

| Existing document | Relationship |
|---|---|
| `docs/anomaly-detection-theory.md` | The hysteresis/smoothing approach recommended here (§2.3) should reuse the same EWMA/CUSUM machinery and tuning process already specified there, rather than introducing an independently-tuned smoothing parameter for the MDP scheduler. |
| `docs/probe-budget-small-n-theory.md` | Both documents converge on the same underlying recommendation: prefer a simple, exactly-computable or explicitly-thresholded mechanism over full optimal-control machinery (POMDP value iteration here; Frank-Wolfe there) at this project's scale, and validate empirically against historical data rather than relying on literature-derived closed-form values. |
| `docs/research-guide-for-gap-topics.md` §4.2 | This document's Part 3 tuning procedure is the concrete instantiation of the MDP backtest that guide already scoped, with the added hysteresis and explicit cost-tradeoff steps this document contributes. |

---

## Part 5 — Conclusion

No paper in the reviewed adaptive-polling, POMDP, or Markov-monitoring literature provides threshold values that transfer directly to an arbitrary small network — exact optimal-threshold derivation fundamentally requires a network-specific reward function and transition model that cannot be specified a priori [web:339][web:342][web:346]. What the literature does provide is validation that a small number of hysteresis-guarded thresholds is an established, near-Pareto-optimal simplification of the full POMDP formulation [web:353], and confirmation that badly-tuned thresholds degrade detection quality rather than destabilizing the collector itself [web:353]. The path forward is therefore empirical: adopt hysteresis on every state transition, define the latency/false-alarm trade-off explicitly, and backtest against this project's own historical RTT/loss data before deploying new thresholds — the same validation discipline already applied elsewhere in this project's roadmap.

---

## References

1. Redondi, A. et al. "Markov decision processes for control of a sensor network-based health monitoring system." IAAI 2009. https://dl.acm.org/doi/10.5555/1620092.1620105
2. "Predictability of Performance in Communication Networks Under Markovian Dynamics." arXiv:2408.13196, 2024. http://arxiv.org/pdf/2408.13196.pdf
3. "Optimal Scheduling of Multiple Sensors over Lossy and Bandwidth Limited Channels." arXiv:1804.05618. http://arxiv.org/pdf/1804.05618.pdf
4. "Remote Estimation of Markov Processes over Costly Channels: On the Benefits of Implicit Information." arXiv:2401.17999, 2024. http://arxiv.org/pdf/2401.17999.pdf
5. Emergent Mind. "Adaptive Polling Mechanisms" — survey covering Markovian switching policies, two-phase threshold policies, and stability results independent of adaptive rule choice. https://www.emergentmind.com/topics/adaptive-polling
6. Wikipedia. "Partially observable Markov decision process" — belief-state update formalism for noisy/partially observed state estimation. https://en.wikipedia.org/wiki/Partially_observable_Markov_decision_process
