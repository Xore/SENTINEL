# Topic 8: OTLP Batch Sizing Under Lossy Wi-Fi

**Status:** Literature reviewed (Kaul 2012, Kadota 2020, Dash0 2026, Gilbert-Elliott 1963/1989). Recommended starting config ready to deploy. Simulation design complete — requires ≥14 days of loss traces.

---

## Theory Summary

### Age of Information (Kaul et al. INFOCOM 2012)
- AoI measures **staleness** of status at receiver: `Δ(t) = t - u(t)` where `u(t)` is the generation time of the freshest received update
- For a D/D/1 queue (deterministic inter-arrival, deterministic service): `Δ_avg = T/2 + D` where `T` = inter-arrival time, `D` = service (transmission) time
- **Key result for batch sizing:** larger batch → higher T → higher average AoI → slower anomaly detection
- At 30s probe interval, a 4096-item batch (≈400KB) that fails and retries adds up to 5 minutes of AoI before retransmit succeeds — well above the 60s AoI target

### Kadota 2020 (MIT Thesis) — Lossy Wireless Extension
- Extends AoI to channels with packet loss; derives D/G/1 queue AoI formula
- For a channel with burst-loss probability `p_B` and good-state probability `p_G`:
  `Δ_avg ≈ T × (1 + ρ_B) / (1 - p_B)` (simplified bound)
  where `ρ_B = p_B / (p_G + p_B)` is the fraction of time in bad state
- **Optimal flush interval** `T*` minimises `Δ_avg`: smaller batches with shorter flush intervals dominate under lossy conditions
- For typical home Wi-Fi (≈2% burst loss, burst length 3–5 packets): `T* ≈ 5–15s` flush interval with ≤256 items/batch

### Gilbert-Elliott Channel Model (Elliott 1963 / Mushkin & Bar-David 1989)
- Two-state Markov chain: Good state (low loss `p_G`) and Bad state (high loss `p_B`)
- Transition probabilities: `α` (Good→Bad), `β` (Bad→Good)
- **Key insight for OTLP:** Wi-Fi loss is **bursty**, not i.i.d. A single 100ms congestion burst can drop an entire 800KB OTLP flush (8192 items × ≈100 bytes/item)
- Smaller batches (≤256 items ≈ 25KB) fit within a good-state burst window, reducing full-batch loss probability
- Parameters to fit: `α`, `β`, `p_G`, `p_B` — from `outage_monitor.py` `ping_samples` loss data

### Dash0 June 2026 — OTel Collector Exporter Knobs
- New `batch` block at exporter level (separate from `batch` processor) — use exporter-level for size control
- `sizer` semantics: `items` (default) or `bytes` — use `items` for predictable Wi-Fi batch sizing
- `min_size`: minimum items before flush (replaces deprecated `send_batch_size`)
- `flush_timeout`: maximum time before flush regardless of `min_size`
- `persistent_queue`: must be enabled to survive collector restart without data loss on Wi-Fi
- `num_consumers`: parallelism for retry; 4 is recommended for Wi-Fi (enough parallelism without overwhelming small uplinks)
- `max_elapsed_time: 0` disables retry abandonment — essential for lossy links where retries eventually succeed

---

## Recommended Starting Configuration

See `config/otelcol-wifi.yaml` for the full configuration. Key parameters:

```yaml
# Wi-Fi-optimised OTLP exporter configuration
exporters:
  otlp/wifi:
    endpoint: "${OTEL_EXPORTER_OTLP_ENDPOINT}"
    tls:
      insecure: false
    retry_on_failure:
      enabled: true
      initial_interval: 5s
      max_interval: 30s
      max_elapsed_time: 0  # never give up
    sending_queue:
      enabled: true
      num_consumers: 4
      queue_size: 2000
      storage: file_storage/queue  # persistent queue
    batch:
      min_size: 256      # ≤25KB per flush, fits good-state burst
      flush_timeout: 5s  # maximum 5s staleness
```

Rationale: 256 items × ≈100 bytes/item ≈ 25KB — fits within a typical Wi-Fi good-state burst window. 5s flush_timeout keeps AoI below 60s target even on total loss (retry within 5+5+10+20+30=70s max, but persistent queue preserves data).

---

## Gilbert-Elliott Parameter Fitting

See `scripts/gilbert_elliott_fit.py` for the full fitting procedure.

### Query to Extract Loss Traces from outage_monitor.py
```sql
SELECT
    target,
    timestamp,
    loss_pct,
    CASE WHEN loss_pct > 0 THEN 1 ELSE 0 END as is_loss
FROM ping_samples
WHERE timestamp >= datetime('now', '-14 days')
ORDER BY target, timestamp;
```

### MLE Parameter Estimation
Fit `(α, β, p_G, p_B)` by maximum likelihood:
```python
# Run-length encoding of loss/good sequences
# Count: N_GG (good→good), N_GB (good→bad), N_BB (bad→bad), N_BG (bad→good)
# MLE estimates:
# α = N_GB / (N_GG + N_GB)  -- P(good→bad)
# β = N_BG / (N_BB + N_BG)  -- P(bad→good)
# p_G = loss_count_in_good / samples_in_good
# p_B = loss_count_in_bad / samples_in_bad
```

---

## Simulation Grid

See `scripts/otlp_simulation.py` for the full simulation.

Grid: `min_size` ∈ {128, 256, 512, 1024, 4096, 8192} × `flush_timeout` ∈ {1s, 5s, 10s, 30s}

For each configuration, measure:
- `total_items_dropped` (items lost when `max_elapsed_time` = 300s, for comparison)
- `avg_aoi_seconds` (average time from item generation to receipt at backend)
- `retry_overhead_pct` (bytes retried / bytes sent × 100)

Pareto-optimal: minimise `avg_aoi_seconds` subject to `drop_rate < 0.1%`.

---

## Exit Criteria Status

- [ ] ≥ 14 days of Wi-Fi loss traces extracted from `ping_samples`
- [ ] Gilbert-Elliott parameters `(α, β, p_G, p_B)` fitted and documented
- [ ] Simulation grid complete; Pareto-optimal `(min_size, flush_timeout)` identified
- [ ] Recommended starting config deployed (`config/otelcol-wifi.yaml`)
- [ ] 72-hour soak test passed: `otelcol_exporter_enqueue_failed_*` < 0.1%

## Next Implementation Step

1. Run `scripts/gilbert_elliott_fit.py` against `monitor.db` loss traces
2. Run `scripts/otlp_simulation.py` to identify Pareto-optimal config
3. Deploy `config/otelcol-wifi.yaml` on the Wi-Fi-connected collector node
4. Monitor `otelcol_exporter_enqueue_failed_*` for 72 hours
