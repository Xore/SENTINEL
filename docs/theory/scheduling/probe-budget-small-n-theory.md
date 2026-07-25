# Frank-Wolfe Probe-Budget Allocation at Small N
## Research Backlog Item — Gap #3 from `docs/gap-analysis-collector-vs-standalone.md`

> **Status:** Research document. Addresses whether Amjad et al. (2021)'s Frank-Wolfe probe-budget allocation, proven at cloud scale, transfers to this project's actual target counts (5–15 targets per collector).
> **Scope:** Formal basis of the method, its stated scale assumptions, the specific numerical-stability risks at small N, and a concrete validation procedure using this project's own historical data before enabling in production, per `docs/research-guide-for-gap-topics.md` §5.

---

## Part 1 — What the Source Paper Actually Proves, and at What Scale

Amjad, Diot, Konomis, Kveton, Soule & Yang, "Optimal Probing with Statistical Guarantees for Network Monitoring at Scale" (arXiv:2109.07743, 2021), frame the problem as **A-optimal** (and **E-optimal**) experimental design: given a fixed monitoring budget (total probes/time unit), choose a probability distribution over network paths to probe such that the resulting estimator (of latency, packet loss, etc.) has minimum worst-case variance, subject to that budget constraint [web:323]. The exact A-/E-optimal design problem is a convex optimization over the probe-allocation simplex, but the paper states plainly that "these designs are too computationally costly to use at production scale" — which is precisely why they propose a Frank-Wolfe-based approximation instead of solving the exact convex program [web:323]. Critically, their validation was performed "in simulation on real network topologies, and also using a production probing system in a real cloud network," reporting "major gains in reducing the probing budget... even with very low probing budgets" [web:323]. The paper's own framing ("cloud networks," "production probing system," "at scale") signals its N (number of monitored paths) is in the range of hundreds to many thousands of paths, not the 5–15 targets typical of a single `analyseLaptop` collector instance monitoring a home lab or small business segment.

### 1.1 Why the Frank-Wolfe Approximation Exists at All — and Why That Motivation Weakens at Small N

The entire justification for replacing the exact A-optimal design with a Frank-Wolfe approximation is *computational cost at scale*: exact A-optimal design requires repeatedly inverting or factorizing a design matrix whose dimension scales with the number of paths, which becomes prohibitive when there are thousands of paths recomputed on a rolling basis [web:323][web:326]. At 5–15 targets, the exact A-optimal design problem is trivially small — inverting a 5×5 to 15×15 information matrix is computationally negligible on any modern hardware, including a Raspberry Pi. This means the core motivation for using the Frank-Wolfe approximation (avoiding an intractable exact computation) **does not apply at this project's scale at all**: the exact A-optimal solution could simply be computed directly and cheaply, making the approximation an unnecessary complexity rather than a required one. This is a materially different conclusion from the framing in the original gap analysis, which treated "whether Frank-Wolfe holds up at small N" as the open question — the more precise open question is "whether *any* variance-weighted probe allocation (exact or approximate) helps at small N," independent of which solver computes it.

### 1.2 A-Optimal Design's Statistical Logic Does Not Depend on N Being Large

Separately from the computational question, the underlying statistical logic of A-optimal design — allocate more measurement budget to paths/targets with higher estimation variance, because reducing variance on already-precise estimates has low marginal value — is a general result from optimal experimental design theory that holds for any N ≥ 2, including small N (Schorning et al. lecture notes on optimal design; Wang 2019 on A-optimal subsampling) [web:333]. What changes at small N is not whether the underlying idea is valid, but the *statistical estimation problem one layer beneath it*: the per-target variance itself must be estimated from a rolling window of recent samples (Welford's algorithm, per the existing ROADMAP design), and that variance estimate is itself noisier when only ~20 rolling samples are available per target, which is the actual mechanism by which "small N" could cause problems — not small N in the number-of-targets sense, but small n in the number-of-samples-per-target sense used to *estimate the allocation weights*.

---

## Part 2 — The Real Small-Sample Risk: Variance Estimation Noise, Not the Allocation Algorithm

### 2.1 Welford's Algorithm Is Numerically Stable; the Problem Is Statistical, Not Numerical

Welford's online algorithm (the method already specified in the ROADMAP for computing rolling per-target RTT variance) is well-established as numerically stable — it avoids the catastrophic cancellation that afflicts the naive sum-of-squares variance formula, because it never subtracts two large, similar-magnitude numbers [web:331][web:332][web:336]. This means the concern raised in `docs/research-guide-for-gap-topics.md` §5.2 ("check numerical stability") is not actually where the risk lies — Welford's method will not "swing wildly" due to floating-point error at any sample count. The real risk is purely **statistical**: with only ~20 samples in the rolling window, the variance *estimate itself* has wide sampling uncertainty (the standard error of a sample variance estimate scales roughly as \(\sigma^2\sqrt{2/(n-1)}\) for approximately normal data), so a single outlier RTT sample (e.g., one delayed probe due to a transient OS scheduling hiccup) can swing the estimated variance for that target substantially cycle-to-cycle, which in turn swings that target's allocated probe share — even though the underlying variance-computation *arithmetic* is perfectly stable.

### 2.2 Practical Consequence: Allocation Flapping, Not Numerical Blow-Up

The practically relevant failure mode at small n-per-target is **allocation flapping**: target A gets a burst of probes this cycle because one delayed sample inflated its rolling variance estimate, then target B gets the burst next cycle for the same reason, without either target actually having a persistently higher-variance path. This is a different failure mode than what §5.2 of the research guide anticipated ("variance estimates should not swing wildly") — the arithmetic won't swing wildly, but the *allocation decision* built on top of a noisy small-sample variance estimate can, which has the same practical consequence (unstable probe scheduling) via a different mechanism.

### 2.3 Mitigation: EWMA-Smoothed Variance Estimate, Not a Larger Rolling Window

Simply enlarging the rolling window (e.g., from 20 to 200 samples) would reduce estimation noise but directly conflicts with the MDP scheduler's goal of *fast adaptation* to a genuinely changing network path (per `docs/mdp-adaptive-scheduling-theory.md`). The standard resolution, consistent with the project's own already-adopted CUSUM/EWMA machinery for anomaly detection (`docs/anomaly-detection-theory.md`), is to apply exponential smoothing to the *variance estimate itself* (not just the raw RTT signal) before feeding it into the allocation weights — i.e., maintain an EWMA of Welford's rolling-window variance output, with a smoothing constant tuned for a few-cycle lag, rather than either a short noisy window or a long unresponsive one. This reuses infrastructure the project already has rather than introducing a new tuning knob.

---

## Part 3 — Concrete Small-N Validation Procedure (Answering §5.2/5.3 of the Research Guide)

The research guide already specifies the right validation shape (simulate Welford's variance over rolling 20-sample windows using historical RTT data; compare probe counts allocated under the variance-weighted scheme versus fixed-interval polling; check whether allocation still catches every real outage fixed polling caught) [existing guide, §5.2/5.3]. This document adds the specific pass/fail criteria that guide was missing:

1. **Compute exact A-optimal allocation directly** (per §1.1, this is cheap at N=5–15) rather than the Frank-Wolfe approximation, as the baseline to test against — if the exact solution itself doesn't help at this scale, the approximation quality question is moot.
2. **Quantify allocation flapping** by measuring the cycle-to-cycle churn in each target's allocated probe share (e.g., mean absolute change in allocation weight per cycle) under both the raw-Welford-variance scheme and the EWMA-smoothed variant (§2.3), using the same 30-day historical dataset already scoped for Phase 4's MDP backtest (`docs/research-guide-for-gap-topics.md` §4.2). High churn with low corresponding benefit (no additional outages caught) would indicate the added complexity is not earning its keep at this scale.
3. **Explicitly test the null hypothesis that uniform (fixed-interval) probing is sufficient at N=5–15** — given §1.1's finding that the paper's entire motivation (computational intractability of exact optimal design) does not apply at this scale, this project should not assume variance-weighted allocation is beneficial by default; it should be demonstrated to catch outages that fixed-interval polling would have missed, using the same historical corpus, before being enabled.
4. **If variance-weighted allocation is adopted, prefer computing the exact A-optimal solution over the Frank-Wolfe approximation**, since §1.1 shows the approximation's justification (computational cost) is absent at this N, and the exact solution avoids the approximation-quality question entirely while being simpler to reason about and debug.

---

## Part 4 — Relationship to Existing Project Documents

| Existing document | Relationship |
|---|---|
| `docs/mdp-adaptive-scheduling-theory.md` | Complementary: the MDP scheduler decides *when* to probe a given target (STABLE/SUSPECT/DEGRADED/DOWN interval selection); probe-budget allocation decides *how the fixed total probe budget is split across targets*. Both can reuse the same EWMA-smoothed variance estimate (§2.3) as a shared input rather than maintaining separate variance trackers. |
| `docs/anomaly-detection-theory.md` | The EWMA smoothing constant recommended in §2.3 should be chosen consistently with (or reuse the same tuning process as) the EWMA parameters already validated for anomaly detection, rather than introducing an independent, untested smoothing constant. |
| `docs/high-cardinality-storage.md` | The 30-day historical RTT dataset needed for §3's validation is the same dataset referenced for Phase 4's MDP backtest — both should be pulled from the same downsampled/normalized SQLite schema once that migration (also recommended in that document) is complete. |

---

## Part 5 — Revised Conclusion for the Gap Analysis

The original framing ("unclear whether the 50% reduction holds at small N with only 20 rolling samples") is only half the picture. This document's finding is stronger and more actionable: **at this project's scale, the Frank-Wolfe approximation itself is very likely unnecessary complexity**, because its sole justification — avoiding an intractable exact computation — does not apply when there are only 5–15 targets. The genuine open question is narrower than "does Frank-Wolfe work at small N": it is whether *any* variance-weighted probe allocation (computed exactly, cheaply, without Frank-Wolfe at all) demonstrably outperforms fixed-interval polling at this scale, and if so, whether the resulting allocation is stable enough (via EWMA-smoothed variance, §2.3) to avoid probe-schedule flapping. Both remain empirical questions requiring the historical-data validation in Part 3, but the implementation path they point to is simpler than originally scoped — exact A-optimal computation, not a Frank-Wolfe approximation, should be the first thing prototyped against this project's own data.

---

## References

1. Amjad, M.J.; Diot, C.; Konomis, D.; Kveton, B.; Soule, A.; Yang, X. "Optimal Probing with Statistical Guarantees for Network Monitoring at Scale." arXiv:2109.07743, 2021. https://arxiv.org/abs/2109.07743
2. Schorning, K. et al. "Optimal design of experiments and its potential application to high-dimensional data." TU Dortmund lecture notes — A-optimality criterion definition, general validity independent of N. http://www.dodsc.tu-dortmund.de/cms/Medienpool/files/003_Kolloquium/03_schorning.pdf
3. scicomp.StackExchange. "Understand the need for Welford's online algorithm" — numerical stability analysis distinguishing Welford's method from the naive sum-of-squares formula. https://scicomp.stackexchange.com/questions/36677/understand-the-need-for-welfords-online-algorithm
4. Wikipedia. "Algorithms for calculating variance" — Welford's algorithm derivation and stability properties. https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance
5. Wikipedia. "Optimal experimental design" — A-/D-/E-optimality criteria background. https://en.wikipedia.org/wiki/Optimal_experimental_design
