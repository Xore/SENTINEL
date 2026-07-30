# Topic 5: Frank-Wolfe Probe-Budget Allocation (Collector Phase 5)


> **Language note (2026-07-30):** this research note predates the 2026-07-25 decision to
> write the v2 collector in Python (`docs/collector/SUGGESTIONS.md` §2). File names below
> are the Python modules; the findings themselves are language-independent.

**Status:** Literature reviewed (Amjad et al. 2021). Small-N simulation design ready. Simulation requires historical RTT data from Step 4.2 — depends on Topic 4 dataset extraction.

---

## Amjad et al. 2021 — Key Findings

**Citation:** Amjad, M.J. et al. "Optimal Probing with Statistical Guarantees for Network Monitoring at Scale." arXiv:2109.07743, 2021. https://arxiv.org/abs/2109.07743

### Core Algorithm Summary

The paper proposes **variance-weighted probe budget allocation**:
- Each target `i` receives probe count proportional to `σ_i / Σσ_j` where `σ_i` is the RTT variance for target `i`
- Variance is estimated online via **Welford's algorithm** (numerically stable, single-pass, O(1) space per target)
- Allocation is updated each cycle using the Frank-Wolfe convex optimization step
- Key guarantee: detection probability for all targets is bounded below, even under budget constraints

### Scale Assumptions (IMPORTANT)
The paper's results were demonstrated on:
- Real cloud network with **hundreds to thousands of paths**
- Large-N scenario where variance diversity is statistically meaningful

> ⚠️ **This project targets 5–15 targets per collector.** At this scale, the variance-weighted allocation may converge to near-uniform allocation (all targets have similar variance on a stable LAN), making the complexity cost unjustifiable. The small-N simulation (Step 5.2) is **mandatory** before enabling Phase 5.

### Welford's Online Variance Algorithm

```
Initialize: count=0, mean=0, M2=0
For each new RTT sample x:
    count += 1
    delta = x - mean
    mean += delta / count
    delta2 = x - mean
    M2 += delta * delta2
Variance = M2 / (count - 1)  # sample variance, count > 1
```

Key property: **numerically stable** for floating-point RTT values (avoids catastrophic cancellation in naïve sum-of-squares formula). Required for production use per `docs/theory/scheduling/probe-budget-small-n-theory.md`.

---

## Small-N Simulation Design

Using historical RTT data from Topic 4 dataset (per-target `rtt_p50` samples):

### Input
- Per-target RTT time series: `rtt[target][t]` for `t` in `[0, T]`
- Rolling window: 20 samples per target (configurable)
- Total probe budget: `B = N × k` where `N` = target count, `k` = probes per cycle (default k=1 for fixed-interval baseline)

### Simulation Steps
1. **Compute rolling Welford variance** for each target over windows of 20 samples
2. **Allocate probes** proportional to variance: `b_i = round(B × σ_i / Σσ_j)`
3. **Simulate outage detection** for each historical outage event:
   - Fixed baseline: 1 probe per target per cycle
   - Variance-weighted: `b_i` probes per target per cycle
   - Record whether the outage was detected within 2 cycles
4. **Check variance stability**: flag if any target's variance estimate oscillates > ±50% cycle-to-cycle during a stable (non-outage) window

### Expected Outcomes

| Scenario | Expected result |
|---|---|
| All targets have similar variance (typical stable LAN) | Allocation ≈ uniform → no benefit from Phase 5 |
| One target clearly higher variance (e.g., Wi-Fi vs. wired) | Allocation skews to Wi-Fi target → potential benefit |
| Outage detection rate | Must be ≥ fixed-interval baseline (no misses) |

See `scripts/welford_variance_sim.py` for the simulation implementation.

---

## Frank-Wolfe Update Step (Collector Implementation)

```
# Per-cycle probe allocation update
for each target i:
    variance[i] = welford_variance(rtt_samples[i][-20:])
total_variance = sum(variance)
for each target i:
    allocation[i] = max(1, round(BUDGET * variance[i] / total_variance))
```

Constraint: `allocation[i] >= 1` (every target gets at least 1 probe per cycle).

---

## Exit Criteria Status

- [ ] Historical RTT data available from Topic 4 dataset extraction
- [ ] Welford variance stability checked over 20-sample windows — no wild oscillation (< ±50% cycle-to-cycle during stable periods)
- [ ] Simulation shows no missed outages vs. fixed-interval baseline
- [ ] Allocation outcomes documented: does variance-weighted scheme actually differ from uniform at this project's target count (5–15)?
- [ ] Decision documented: enable Phase 5 only if variance-weighted scheme provides measurable benefit (> 1 probe difference in allocation per target)

## Next Implementation Step

Run `scripts/welford_variance_sim.py` using the RTT dataset from `scripts/mdp_backtest.py`. If simulation shows benefit, implement `collector/scheduler_probe_budget.py`. If not, document the finding and skip Phase 5 for this deployment scale.
