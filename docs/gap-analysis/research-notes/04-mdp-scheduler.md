# Topic 4: MDP Adaptive Scheduler (Collector Phase 4)


> **Language note (2026-07-30):** this research note predates the 2026-07-25 decision to
> write the v2 collector in Python (`docs/collector/SUGGESTIONS.md` §2). File names below
> are the Python modules; the findings themselves are language-independent.

**Status:** Literature reviewed (Zabala et al. 2023). Dataset extraction query written. Threshold validation and backtest require live SQLite data — pending.

---

## Zabala et al. 2023 — Key Findings

**Citation:** Zabala, L. et al. "Optimality of a Network Monitoring Agent and Validation in a Real Environment." *Mathematics* 11(3):610, 2023. DOI: 10.3390/math11030610.

### MDP Model Summary
The paper models a network monitor as an agent operating over a finite state space:
- **States:** `{NORMAL, DEGRADED, FAILED}` (or equivalent 3-state model)
- **Actions:** `{POLL_SLOW, POLL_FAST, ALERT}` mapped to polling intervals
- **Transition probabilities:** Learned from historical outage data, NOT assumed from literature
- **Reward function:** Penalises missed detections heavily, over-polling lightly
- **Policy derivation:** Value iteration over the MDP yields a threshold policy:
  `if P(FAILED | current_state) > θ_alert → switch to POLL_FAST`
  `if P(FAILED | current_state) > θ_alert_high → emit alert`

### Validation Approach (Critical for This Project)
The paper's key methodological contribution is **validating against a real campus network**, not just simulation. They:
1. Collected 30+ days of real outage/recovery events
2. Labeled the 10-minute pre-onset RTT/loss trajectory for each outage
3. Fit MDP transition probabilities from that data
4. Backtested detection latency: fixed-interval ticker vs. MDP policy
5. Reported **40–60% reduction in detection latency** — but this was for their specific network profile

> ⚠️ **Do not assume 40–60% transfers to this project's network.** The improvement is highly dependent on outage frequency, duration, and RTT/loss trajectory shape. Must be validated against `monitor/outage_monitor.py` data.

### Thresholds from Paper (Starting Point Only)
- `loss_pct > 1.0` as degraded-state trigger
- `rtt_p95 > 2.0 × baseline` as degraded-state trigger
- Paper uses a 5-minute observation window for state estimation

These are **reasonable starting values** but must be validated against this project's own data before shipping Phase 4.

---

## Dataset Extraction Queries

Run against `monitor/outage_monitor.py`'s SQLite database (`~/.local/share/outage_monitor/monitor.db` or configured path):

```sql
-- Extract all outage events (≥30 days recommended)
SELECT
    id,
    start_time,
    end_time,
    kind,
    failed_targets,
    duration_s
FROM events
WHERE start_time >= datetime('now', '-90 days')
ORDER BY start_time;

-- Extract RTT/loss trajectory in 10-min window before each outage onset
-- Replace :event_start with each event's start_time
SELECT
    ps.target,
    ps.timestamp,
    ps.rtt_min,
    ps.rtt_p50,
    ps.rtt_p95,
    ps.rtt_max,
    ps.loss_pct
FROM ping_samples ps
WHERE ps.timestamp BETWEEN datetime(:event_start, '-10 minutes') AND :event_start
ORDER BY ps.target, ps.timestamp;

-- Compute per-target RTT baseline (median over stable periods)
SELECT
    target,
    AVG(rtt_p50) as baseline_rtt_p50,
    AVG(rtt_p95) as baseline_rtt_p95,
    AVG(loss_pct) as baseline_loss_pct
FROM ping_samples
WHERE loss_pct < 0.5  -- stable-state filter
GROUP BY target;
```

See `scripts/mdp_backtest.py` for the full extraction + threshold validation script.

---

## Threshold Validation Plan

For each outage event in the historical dataset:
1. Extract the per-target RTT/loss trajectory in the 10 minutes before onset
2. For each candidate threshold pair `(loss_thresh, rtt_mult)` in the grid:
   - `loss_thresh` ∈ {0.5, 1.0, 2.0, 5.0} %
   - `rtt_mult` ∈ {1.5, 2.0, 3.0} × baseline
3. Record: True Positive (threshold fires ≤ 10 min before onset), False Positive (fires during stable period), Miss (threshold never fires in 10-min window)
4. Compute precision/recall for each threshold pair
5. Select threshold pair maximising recall subject to precision ≥ 0.80

Expected outcome: different threshold pairs will be optimal for different network segments (home LAN vs. VPS vs. OT segment) — document per-profile thresholds.

---

## Backtest Detection Latency

For the chosen threshold pair:
1. Replay historical outage timeline
2. Record time-from-onset to first threshold trigger (MDP policy)
3. Compare against fixed-30s-ticker detection time (always = up to 30s)
4. Report: mean latency improvement, 95th-percentile latency improvement, missed outages

Only ship Phase 4 if mean improvement > 0% and missed outage count = 0.

---

## Exit Criteria Status

- [ ] ≥ 30 days of outage data exported from `monitor` SQLite
- [ ] Per-target RTT baselines computed
- [ ] Threshold grid search complete; optimal `(loss_thresh, rtt_mult)` documented per network segment
- [ ] Backtest latency improvement documented with real numbers (not assumed from Zabala et al.)
- [ ] MDP transition probabilities fitted to this project's data and stored in `config/mdp-profiles.toml`

## Next Implementation Step

Run `scripts/mdp_backtest.py` against the live `monitor.db`. Then implement the adaptive-interval layer in `collector/scheduler.py` using the validated thresholds from `config/mdp-profiles.toml`. The scheduler exists today as a priority queue with a fixed per-check `interval_s`; this note supplies the adaptation on top of it, not a second scheduler.
