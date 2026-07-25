# OTLP Batch Sizing Under Lossy Wi-Fi Links

> **Status:** Open research / implementation guide  
> **Scope:** `collector/` → `monitor/` export pipeline on intermittent Wi-Fi  
> **Related:** `docs/research-guide-for-gap-topics.md` §8, `ROADMAP.md` §Open Research Questions

---

## 1. Problem Statement

The OpenTelemetry Collector's default exporter-helper configuration was designed for
data-centre network conditions: low loss (< 0.1 %), low RTT (< 5 ms), stable bandwidth.
Key defaults that carry those assumptions:

| Parameter | Default value | Data-centre assumption |
|---|---|---|
| `send_batch_size` (batch processor) | 8 192 items | Link can absorb one flush without retransmit |
| `flush_timeout` | 200 ms | Backend responds within one RTT |
| `sending_queue.queue_size` | 1 000 requests | Outages are short (seconds, not minutes) |
| `retry_on_failure.max_elapsed_time` | 300 s | Backend recovers within 5 minutes |
| `num_consumers` | 10 | Enough parallelism to drain queue before overflow |

On a laptop probe attached to intermittent Wi-Fi (e.g., residential 2.4 GHz,
café hotspot, mobile tethering), three structural differences invalidate these defaults:

1. **Burst loss:** 802.11 frame-loss events are bursty (Gilbert-Elliott model), not
   i.i.d. A single 100 ms congestion event can silently drop an entire 8 192-item flush.
2. **Variable RTT:** Wi-Fi RTT swings between 2 ms (clear channel) and 200+ ms
   (interference, re-association). The 5 s export timeout (`timeout: 5s`) can fire
   mid-flush during a roaming event even though the link recovers in the next second.
3. **Long outages:** Mobile or café Wi-Fi outages easily exceed 5 minutes. The default
   `max_elapsed_time: 300s` then permanently drops the queued batch, even though the
   data is still on disk (if a persistent queue is configured).

---

## 2. Theoretical Background

### 2.1 Age of Information (AoI) — Freshness vs. Batch Size

Age of Information (AoI) quantifies the staleness of the most recently received
update at the consumer. For a discrete-time push system with fixed inter-generation
interval `g` and random service time (influenced by retransmits), the time-average AoI
under a D/G/1 queue is:

$$\bar{\Delta} = g + \frac{\mathbb{E}[S^2]}{2\,\mathbb{E}[S]} - \frac{g}{2}$$

where `S` is the system service time (transmission + possible retransmit).

Larger batch sizes increase `g` (less frequent pushes) and increase `E[S²]` (a single
large flush takes longer to retransmit on loss). Both terms in the formula grow,
increasing AoI. Smaller batches reduce freshness penalty but increase per-flush
overhead. The optimal `g` minimises this trade-off given the measured loss rate `p`.

For the `analyseLaptop` context: the monitor needs recent probe results for anomaly
detection (`CUSUM` / `EWMA` thresholds). If the OTLP flush is delayed by 30 s during
a Wi-Fi outage, the detection latency blows out by the same amount. AoI directly
bounds the minimum achievable anomaly-detection latency.

**Key reference:** Kaul, S. et al. "Real-time Status Updates: A Fresh Perspective."
IEEE INFOCOM 2012 (original AoI paper). Kadota, I. "Age-of-information in Wireless
Networks: Theory and Practice." MIT PhD Thesis, 2020. (dspace.mit.edu)

### 2.2 Gilbert-Elliott Burst-Loss Model

Wi-Fi loss is best described by the two-state Markov (Gilbert-Elliott) model:

- **Good state (G):** frame loss probability `p_G` ≈ 0–2 %
- **Bad state (B):** frame loss probability `p_B` ≈ 20–60 % (interference, congestion)
- Transition probabilities `α` (G→B) and `β` (B→G) determine burst length

Under this model, the probability that an entire OTLP batch survives delivery is:

$$P(\text{batch survives}) = (1 - p_G)^n \cdot \pi_G + (1 - p_B)^n \cdot \pi_B$$

where `n` is the number of IP packets in the flush and `π_G`, `π_B` are steady-state
probabilities. For a 8 192-item batch at ~100 bytes/item ≈ 800 KB, at `p_B = 0.3` the
batch-level loss rate is near 100 % during a bad burst — the entire batch is dropped
and retried, doubling effective bandwidth consumption.

Smaller batches (e.g., 256 items ≈ 25 KB) reduce per-packet-sequence length and
improve the probability of fitting within a good-state burst.

**Key reference:** Elliott, E.O. "Estimates of Error Rates for Codes on Burst-Noise
Channels." Bell System Technical Journal, 1963. Mushkin, M. & Bar-David, I. "Capacity
and Coding for the Gilbert-Elliott Channels." IEEE Trans. Inf. Theory, 1989.

### 2.3 OTel Exporter-Helper Pipeline Mechanics

The OpenTelemetry Collector exporter helper (as of v0.100+) uses a fixed pipeline:

```
receiver → sending_queue (buffer) → batcher → consumer pool → retry_sender → network
```

Key interactions for lossy links:

- **`block_on_overflow: false` (default):** When `queue_size` is exhausted, incoming
  data is **dropped** — not returned to retry. The drop is counted by
  `otelcol_exporter_enqueue_failed_*` but the data is gone.
- **Retries hold consumers:** Each of the `num_consumers` workers is tied up
  during the `initial_interval … max_interval` backoff loop. If all 10 consumers
  are retrying simultaneously, nothing drains the queue. Queue fills → drops.
- **Persistent queue survival:** With `file_storage` extension, undelivered batches
  survive Collector restarts. Setting `max_elapsed_time: 0` (retry forever) is
  appropriate when the persistent queue bounds disk consumption.

**Key reference:** Dash0 "Batching, Queuing, and Retries in the OpenTelemetry
Collector." June 2026. (dash0.com/guides/batching-queuing-and-retries) — comprehensive
current treatment of all exporter-helper knobs.

---

## 3. Recommended Configuration Profile for Wi-Fi Probe

Based on the theory above, the following exporter configuration is the starting
point for tuning on `analyseLaptop`'s Wi-Fi-attached collector nodes:

```yaml
# collector/config/otelcol-wifi.yaml  (Wi-Fi probe profile)
exporters:
  otlp/monitor:
    endpoint: "${MONITOR_ENDPOINT}:4317"
    tls:
      cert_file: /etc/collector/cert.pem
      key_file:  /etc/collector/key.pem
      ca_file:   /etc/collector/ca.pem
    timeout: 15s              # up from 5s — Wi-Fi RTT can spike to 200 ms

    retry_on_failure:
      enabled: true
      initial_interval: 5s
      multiplier: 1.5
      max_interval: 60s
      max_elapsed_time: 0     # retry forever — persistent queue keeps data safe

    sending_queue:
      enabled: true
      storage: file_storage/exporter_queue  # persist across restarts
      queue_size: 2000        # up from 1000 — absorb longer outages
      num_consumers: 4        # reduced from 10 — fewer concurrent retry loops
      sizer: requests

      batch:
        sizer: items
        min_size: 256         # down from 8192 — fits within Wi-Fi good-state burst
        max_size: 512
        flush_timeout: 5s     # up from 200 ms — allow time to accumulate under low rate

extensions:
  file_storage/exporter_queue:
    directory: /var/lib/otelcol/queue
    timeout: 2s

service:
  extensions: [file_storage/exporter_queue]
```

**Rationale for each change vs. default:**

| Parameter | Default | Wi-Fi value | Reason |
|---|---|---|---|
| `timeout` | 5 s | 15 s | Prevent false-timeout on 200 ms Wi-Fi RTT spike |
| `max_elapsed_time` | 300 s | 0 (∞) | Persistent queue handles storage; never throw away data |
| `queue_size` | 1 000 | 2 000 | Absorb 30+ min outage at 1 sample/collector-cycle |
| `num_consumers` | 10 | 4 | Reduce concurrent retry pile-up under long outage |
| `min_size` (batch) | 8 192 | 256 | Fit within Wi-Fi good-state burst; reduce per-batch loss impact |
| `flush_timeout` | 200 ms | 5 s | Allow small batches to coalesce during low-rate intervals |

---

## 4. Open Research Question: Optimal Tuning from Loss Traces

The configuration above is a *principled starting point* — not a validated optimum.
The actual optimal values depend on the measured loss rate and burst length
characteristics of the specific Wi-Fi environment.

### 4.1 Simulation Methodology

The `monitor/outage_monitor.py` module records timestamped loss events in its
SQLite database. A simulation study using those traces would:

1. **Extract loss traces** from `ping_samples` (is_loss = 1 rows) grouped by time
   window to reconstruct the Gilbert-Elliott state sequence.
2. **Fit Gilbert-Elliott parameters** (α, β, p_G, p_B) to the observed burst length
   distribution using maximum-likelihood estimation.
3. **Simulate OTLP pipeline** with varying `min_size` (128, 256, 512, 1024, 4096, 8192)
   and `flush_timeout` (1 s, 5 s, 10 s, 30 s) values, measuring:
   - Total data dropped (items that exceeded `max_elapsed_time` = 300 s)
   - Average AoI at the `monitor/` receiver (freshness of last received batch)
   - Effective retransmit overhead (bytes retried / bytes originally sent)
4. **Find the Pareto frontier** of (AoI, drop rate, retransmit overhead) and pick
   the configuration closest to the project's requirements:
   - Max tolerable AoI: 60 s (anomaly detection must see data within one minute)
   - Max tolerable drop rate: 0.1 % (lose at most 1 in 1000 probe results)

### 4.2 Required Data

Minimum dataset for the simulation to be statistically meaningful:
- At least **14 days** of `ping_samples` covering known Wi-Fi outages
  (both short ≤ 30 s roaming events and long ≥ 5 min outages)
- Ideally: data from multiple Wi-Fi environments (home 2.4 GHz, café, mobile hotspot)

### 4.3 Exit Criteria for Closing This Research Question

- [ ] Gilbert-Elliott parameters fitted from ≥ 14 days of `outage_monitor.py` traces
- [ ] Simulation run across the full (min_size × flush_timeout) grid
- [ ] Pareto-optimal configuration identified and documented in `config/otelcol-wifi.yaml`
- [ ] Configuration validated by a 72-hour live soak test on a Wi-Fi-attached
  collector node, confirming `otelcol_exporter_enqueue_failed_*` stays < 0.1 %

---

## 5. Related Work

| Reference | Relevance |
|---|---|
| Kadota 2020, MIT PhD Thesis — AoI in wireless networks | Theoretical bound on freshness vs. batch size under packet loss |
| Elliott 1963 / Mushkin & Bar-David 1989 — Gilbert-Elliott model | Burst-loss characterisation of Wi-Fi channels |
| Dash0 OTLP Batching Guide, June 2026 | Current OTel exporter-helper knobs, sizer semantics, persistent queue |
| OTel Collector issue #7359 — queue_size reduction | Background on default queue_size reduction from 5000 → 1000 |
| Broadcom DX O2 OTel best-practices, Jan 2025 | Example production batch configs (100–1000 items, 10 s timeout) |
| Kaul et al. IEEE INFOCOM 2012 — AoI original paper | Definition of Age of Information metric |
