# Anomaly Detection Theory: Holt-Winters & CUSUM ARL
## Academic Research for `monitor/` Implementation

> **Status:** Research document — feeds directly into `monitor/residuals.py` and `backend/analyse/detector.py`  
> **Priority:** High — parameter choices here determine false positive rate and detection latency for the entire system.

---

## Part 1 — Holt-Winters Exponential Smoothing

### 1.1 Why Holt-Winters for Network Traffic

Network traffic time series have three simultaneously active components that make naive thresholding impossible:

- **Level** — absolute volume that shifts over days/weeks (new device added, link upgraded)
- **Trend** — slow directional drift (traffic growing week-over-week)
- **Seasonality** — deterministic repeating pattern (daily peak at 09:00, weekend dip)

Holt-Winters triple exponential smoothing decomposes all three, producing a **residual** that is approximately stationary and zero-mean during normal operation. CUSUM/EWMA are then applied to the residual, not the raw metric — this is the core insight from Münz (TU Munich, 2010) and validated on network data by Brügner et al. (TU Munich, 2017).

**Key reference:** Brügner, H. et al. "Holt-Winters Traffic Prediction on Aggregated Flow Data." TU Munich NET-2017-09-1.  
https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2017-09-1/NET-2017-09-1_04.pdf

**Key reference:** Aboode, A. "Anomaly Detection in Time Series Data Based on Holt-Winters." Diva Portal, 2018.  
https://www.diva-portal.org/smash/get/diva2:1198551/FULLTEXT02.pdf

---

### 1.2 The Additive Model — Equations

For network metrics, the **additive** model is correct (not multiplicative). Seasonality adds a fixed offset at each hour-of-day, it does not multiply the level. Multiplicative seasonality is for economic data where seasonal swings are proportional to the level.

The additive Holt-Winters recurrences (Aboode 2018, equations 2.11–2.14):

**Level:**
```
ℓ_t = α(y_t − s_{t−m}) + (1 − α)(ℓ_{t−1} + b_{t−1})
```

**Trend:**
```
b_t = β(ℓ_t − ℓ_{t−1}) + (1 − β)b_{t−1}
```

**Seasonal:**
```
s_t = γ(y_t − ℓ_{t−1} − b_{t−1}) + (1 − γ)s_{t−m}
```

**Forecast (h steps ahead):**
```
ŷ_{t+h} = ℓ_t + h·b_t + s_{t+h−m(k+1)}
```

**Residual (what CUSUM/EWMA operate on):**
```
e_t = y_t − ŷ_{t|t−1}
```

Where:
- `m` = season length in intervals (for 60s buckets and 24h season: m = 1440)
- `k` = floor((h−1)/m)
- α, β, γ ∈ (0, 1)

---

### 1.3 Parameter Semantics

| Parameter | Controls | Low value (→ 0) | High value (→ 1) |
|---|---|---|---|
| **α** (level) | How fast level tracks new observations | Stable, slow to adapt to step changes | Reactive, tracks every fluctuation (noisy baseline) |
| **β** (trend) | How fast trend adapts | Nearly constant trend assumed | Trend reverses rapidly (unstable for slow-trending network data) |
| **γ** (seasonal) | How fast seasonal pattern updates | Fixed seasonal pattern (good if pattern is stable) | Seasonal pattern updates every cycle (adapts to shifting usage patterns) |

**For network metrics specifically:**
- **α = 0.1–0.3** — network traffic levels shift slowly (new devices, link changes); moderate adaptation
- **β = 0.01–0.1** — trends are very slow in home/lab networks; a near-zero β is common
- **γ = 0.1–0.3** — daily patterns are relatively stable but shift over weeks (work schedule changes, holidays)

The Brügner (2017) study on real NetFlow data found that **lower α values** (0.1–0.2) produced the most stable residuals for anomaly detection, because high α causes the level to track anomalies themselves, suppressing them from the residual — the detector then misses them.

---

### 1.4 Parameter Optimisation Strategy

Two approaches, in order of preference:

#### A. MSE Minimisation (Standard, Recommended)

Minimise the one-step-ahead squared prediction error over a training window:

```python
# monitor/residuals.py — parameter fitting
from scipy.optimize import minimize
import numpy as np

def fit_holtwinters_params(series: np.ndarray, m: int = 1440) -> tuple:
    """
    Fit α, β, γ by minimising MSE on training series.
    series: array of metric values at 60s intervals
    m: season length (default 1440 = 24h at 60s buckets)
    Returns: (alpha, beta, gamma, initial_level, initial_trend, initial_seasonals)
    """
    def mse(params):
        a, b, g = params
        if not (0 < a < 1 and 0 < b < 1 and 0 < g < 1):
            return 1e10
        _, residuals = holtwinters_fit(series, a, b, g, m)
        return np.mean(residuals**2)

    # Start from known-good network defaults (Brügner 2017)
    result = minimize(
        mse,
        x0=[0.2, 0.05, 0.2],
        method='L-BFGS-B',
        bounds=[(0.01, 0.5), (0.001, 0.2), (0.01, 0.5)]
    )
    return result.x  # (alpha, beta, gamma)
```

**Bounds rationale:** The upper bound of 0.5 for α and γ is a deliberate constraint. Unconstrained optimisation on short training windows frequently selects α > 0.7, which causes anomalies to be absorbed into the baseline (Aboode 2018, Section 4.3). Capping at 0.5 is a regularisation that prevents this.

#### B. Per-Metric Adaptive Parameters (Advanced)

Different metric types have different optimal parameters:

| Metric | Recommended α | Recommended β | Recommended γ | Rationale |
|---|---|---|---|---|
| RTT p95 (ms) | 0.15 | 0.02 | 0.20 | Slow level shifts; moderate seasonal (time-of-day pattern) |
| Loss % | 0.10 | 0.01 | 0.15 | Very stable in healthy network; low α preserves sensitivity |
| rx_bps / tx_bps | 0.25 | 0.05 | 0.30 | Faster level adaptation to traffic pattern changes |
| CPU ratio | 0.20 | 0.03 | 0.25 | Moderate adaptation; clear daily pattern |
| Error rate | 0.10 | 0.01 | 0.10 | Should be near-zero; ultra-stable baseline needed |
| Flow count | 0.20 | 0.05 | 0.25 | Follows traffic closely; moderate adaptation |

Start with MSE-optimised parameters during the 7-day warm-up period, then switch to the per-metric bounds above if the optimiser produces unstable results.

---

### 1.5 Initialisation

Holt-Winters is a recursive algorithm and requires initialisation of ℓ₀, b₀, and s₋ₘ₊₁…s₀. Poor initialisation causes a transient (the first few cycles produce large residuals) — this is often mistaken for real anomalies.

**Recommended initialisation (Hyndman & Athanasopoulos, 2021):**

```python
def init_holtwinters(series: np.ndarray, m: int) -> tuple:
    """
    Hyndman decomposition-based initialisation.
    Requires at least 2 full seasons (2*m samples).
    """
    # Level: mean of first season
    l0 = np.mean(series[:m])

    # Trend: average change per period across first two seasons
    b0 = (np.mean(series[m:2*m]) - np.mean(series[:m])) / m

    # Seasonal indices: deviation of each period from its season mean
    season_means = [np.mean(series[i*m:(i+1)*m]) for i in range(2)]
    s0 = []
    for j in range(m):
        s0.append(np.mean([
            series[i*m + j] - season_means[i]
            for i in range(2)
        ]))
    return l0, b0, s0
```

**Warm-up period:** Do not emit CUSUM/EWMA alarms for the first `2 * m` intervals (48h at 60s buckets). Log residuals but suppress alarms until the model has converged.

---

### 1.6 Additive vs Multiplicative: Decision Rule for Network Metrics

```python
# Quick empirical test: if coefficient of variation (CV = σ/μ) of the
# seasonal component is roughly constant across levels → additive.
# If CV grows with level → multiplicative.

def select_seasonality_type(series: np.ndarray, m: int) -> str:
    season_means = [np.mean(series[i*m:(i+1)*m]) for i in range(len(series)//m)]
    season_stds  = [np.std(series[i*m:(i+1)*m])  for i in range(len(series)//m)]
    cvs = [s/max(mu, 1e-9) for mu, s in zip(season_means, season_stds)]
    # If CV variance is low, seasonal amplitude is constant → additive
    return 'additive' if np.std(cvs) < 0.3 else 'multiplicative'
```

For all metrics in this system (RTT, loss, bandwidth, CPU), additive is correct. Multiplicative would only be relevant if you expected traffic to scale by an order of magnitude between seasons — not applicable here.

---

### 1.7 Multi-Seasonality (Weekly + Daily)

Network traffic has *two* overlapping seasons: **daily** (24h) and **weekly** (weekday vs weekend). Standard Holt-Winters handles only one.

**Options:**
1. **Single season, m=10080** (week at 60s buckets) — captures both, but requires 3 weeks of training data and very long seasonal state vector. Not practical for initial deployment.
2. **TBATS / Multiple seasonal Holt-Winters** (Taylor 2003, de Livera et al. 2011) — handles multiple seasons natively but significantly more complex.
3. **Recommended pragmatic approach:** Use **m=1440** (daily) + **per-slot sigma** (168 slots = 7×24 hours-of-week). This handles the weekly pattern via the adaptive control limits in `detector.py` rather than in the forecasting model itself.

```python
# monitor/detector.py — per-slot control limits
hour_of_week = (now.weekday() * 24 + now.hour)  # 0–167
sigma_slot = rolling_sigma[hour_of_week]  # updated only during stable periods
k_effective = k * sigma_slot  # dynamic threshold, not global sigma
```

This is simpler than TBATS and handles the weekend/weekday difference without requiring 3 weeks of training data.

---

## Part 2 — CUSUM ARL Theory

### 2.1 What ARL Means and Why It Matters

The **Average Run Length (ARL)** is the expected number of observations before the CUSUM chart signals an alarm:

- **ARL₀** = ARL when the process is *in control* (no anomaly). You want this **high** — it is the reciprocal of the false positive rate. ARL₀ = 500 means on average 500 intervals between false alarms.
- **ARL₁** = ARL when the process is *out of control* (anomaly present at shift size δ). You want this **low** — it is the detection latency.

The fundamental CUSUM design problem: **choose h (decision interval) and k (slack/reference value) to achieve target ARL₀ while minimising ARL₁ for the shifts you care about.**

**Key reference:** NIST Engineering Statistics Handbook, Section 6.3.2.3.1 — CUSUM ARL.  
https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc3231.htm

---

### 2.2 CUSUM Mechanics (Standardised Form)

The one-sided CUSUM statistics (Münz 2010; Page 1954):

```
C⁺_t = max(0, C⁺_{t-1} + (x_t − μ₀)/σ − k_s)     [detects upward shifts]
C⁻_t = max(0, C⁻_{t-1} − (x_t − μ₀)/σ − k_s)     [detects downward shifts]
```

Alarm when `C⁺_t > h_s` or `C⁻_t > h_s`, where:
- `k_s` = slack (standardised, in units of σ) — half the detectable shift: `k_s = δ/2`
- `h_s` = decision interval (standardised, in units of σ)
- `x_t` = residual from Holt-Winters at time t
- `μ₀` = 0 (residuals are zero-mean by construction)
- `σ` = residual standard deviation from stable periods

---

### 2.3 ARL Tables for CUSUM Design

The following ARL values come from the NIST handbook and Hawkins & Olwell (1998), computed via Markov chain approximation for Gaussian residuals:

#### ARL₀ (false positive frequency) as a function of h_s and k_s:

| k_s (slack) | h_s = 3 | h_s = 4 | h_s = 5 | h_s = 6 | h_s = 8 |
|---|---|---|---|---|---|
| 0.25 | 109 | 282 | 723 | 1837 | 11733 |
| 0.50 | 139 | 370 | 931 | 2341 | 14846 |
| 0.75 | 167 | 450 | 1140 | 2885 | 18436 |
| 1.00 | 200 | 540 | 1368 | 3474 | 22193 |

#### ARL₁ (detection latency, intervals) for a 2σ shift with k_s=0.5:

| h_s | ARL₀ | ARL₁ at δ=1σ | ARL₁ at δ=2σ | ARL₁ at δ=3σ |
|---|---|---|---|---|
| 3 | 139 | 6.5 | 2.8 | 1.7 |
| 4 | 370 | 8.1 | 3.2 | 1.9 |
| 5 | 931 | 10.4 | 3.8 | 2.1 |
| 6 | 2341 | 13.0 | 4.5 | 2.3 |

**Interpretation for this system (60s buckets):**  
- ARL₀ = 370 → false alarm every 370 × 60s = **6.2 hours** (h_s=4, k_s=0.5)
- ARL₁ = 3.2 at 2σ shift → detection in 3.2 × 60s = **~3.2 minutes** for a 2σ anomaly

This is a reasonable operating point for a home/lab monitoring system.

---

### 2.4 Parameter Selection for This System

**Recommended parameters (derived from ARL theory):**

```python
# monitor/detector.py — CUSUM parameters with ARL justification

# k_s = 0.5: detects shifts ≥ 1σ (half the target shift size)
# Chosen because network RTT/loss anomalies typically manifest as 2–5σ shifts
# Sensitivity: k_s=0.5 is the standard choice for shift detection at δ=1σ (Page 1954)
cusum_k = 0.5  # slack in units of sigma

# h_s = 5: ARL₀ ≈ 931 (false alarm every ~15h at 60s buckets)
# ARL₁ = 3.8 intervals at 2σ shift (~4 minutes detection latency)
# Rationale: h_s=4 produces too many false alarms for overnight unattended operation
# h_s=6 produces excessive detection latency for fast fault detection
cusum_h = 5.0  # decision interval in units of sigma
```

**When to use different parameters:**

| Scenario | k_s | h_s | ARL₀ | ARL₁ at 2σ |
|---|---|---|---|---|
| High-sensitivity (detect small drifts, tolerate more false positives) | 0.25 | 4 | 282 | ~2.5 min |
| **Default (balanced — recommended)** | **0.50** | **5** | **931** | **~4 min** |
| Low-noise (unattended overnight, minimise wakeups) | 0.50 | 6 | 2341 | ~5 min |
| Critical path (detect anything fast, operator watching) | 0.25 | 3 | 109 | ~2 min |

---

### 2.5 Non-Gaussian Residuals — The Practical Problem

All the ARL values above assume Gaussian residuals. Network traffic residuals are typically **not Gaussian**: they have heavier tails (excess kurtosis), especially for packet loss % (which clusters at zero then spikes to 100%) and flow counts.

**Effect on ARL:** Non-Gaussian heavy tails inflate the false positive rate. A CUSUM designed for ARL₀=931 on Gaussian data may achieve only ARL₀=200 on real traffic residuals.

**Mitigations:**

#### A. Winsorisation (Recommended, Simple)

Clip extreme residuals before feeding to CUSUM:

```python
# Winsorise at ±3σ before CUSUM update
# This eliminates outlier residuals that inflate the CUSUM statistic without
# representing a true sustained shift
winsorised = np.clip(residual, -3 * sigma, 3 * sigma)
# Then feed winsorised value to CUSUM
```

Winsorisation is explicitly supported in the R `CUSUMdesign` package's `getARL` function and is the recommended approach for non-Gaussian data in the SPC literature.

#### B. Robust Sigma Estimation (Required)

Do not estimate σ from the mean of squared residuals — outliers will inflate it, causing the control limits to widen and miss real anomalies:

```python
# Use Median Absolute Deviation (MAD) — robust to outliers
# σ_MAD = 1.4826 × MAD (the 1.4826 factor makes it consistent with σ for Gaussian data)
from scipy.stats import median_abs_deviation
sigma_robust = 1.4826 * median_abs_deviation(residuals_window, scale=1.0)
```

The 1.4826 scaling constant (Rousseeuw & Croux 1993) ensures that for Gaussian data, σ_MAD = σ_sample, maintaining the ARL calibration.

#### C. Metric-Specific Transformations

For metrics with strongly non-Gaussian distributions, apply a variance-stabilising transform before Holt-Winters:

| Metric | Distribution | Transform |
|---|---|---|
| Loss % | Zero-inflated [0,100] | `arcsin(sqrt(loss/100))` — Freeman-Tukey transform |
| Flow count | Poisson-like (count data) | `sqrt(count)` — variance-stabilising for Poisson |
| rx_bps / tx_bps | Log-normal | `log1p(bps)` |
| RTT p95 | Right-skewed | `log(rtt)` or leave as-is if σ is stable |
| CPU ratio | Beta-distributed [0,1] | `logit(cpu)` = log(cpu/(1-cpu)) |

Apply transform before fitting Holt-Winters; apply inverse transform for display only.

---

### 2.6 CUSUM Reset Policy

After an alarm fires, the CUSUM statistic must be reset. Two options:

```python
# Option A: Reset to zero (Page 1954 — standard)
# Pro: Clean state; each alarm is independent
# Con: If the anomaly persists, the CUSUM takes k_s/1 intervals to re-arm
self.cusum_pos = 0.0
self.cusum_neg = 0.0

# Option B: Reset to h/2 (Lucas & Crosier 1982 — "Fast Initial Response")
# Pro: Faster re-detection if anomaly continues
# Con: More sensitive to noise immediately after alarm
self.cusum_pos = self.cusum_h / 2
self.cusum_neg = self.cusum_h / 2
```

**Recommendation for this system:** Use Option A (reset to zero). The combined CUSUM+EWMA alarm policy (Christodoulou 2015) means that if an anomaly persists, the EWMA will sustain the alarm state even while CUSUM re-arms. The reset to zero avoids double-counting.

---

### 2.7 EWMA Control Limits — Parameter Selection

The EWMA control limit (Christodoulou 2015; Montgomery 2009):

```
UCL = μ₀ + L·σ·√(λ/(2−λ))
LCL = μ₀ − L·σ·√(λ/(2−λ))
```

| λ | L | ARL₀ (approx) | ARL₁ at 1σ shift | Characteristic |
|---|---|---|---|---|
| 0.05 | 2.615 | 500 | 10.3 | Very smooth, slow to respond |
| 0.10 | 2.814 | 500 | 6.0 | Balanced |
| **0.20** | **3.001** | **500** | **4.0** | **Recommended — standard choice** |
| 0.40 | 3.054 | 500 | 3.1 | Fast, less smoothing |

**Recommended: λ=0.2, L=3.0** — this achieves ARL₀≈500 and detects a 1σ shift in ~4 intervals (4 minutes), comparable to CUSUM. The combination (CUSUM AND EWMA) then has an effective ARL₀ ≈ ARL₀_CUSUM × ARL₀_EWMA / (some correlation factor), significantly higher than either alone — the Christodoulou 2015 empirical result.

---

## Part 3 — Implementation Checklist

Direct mapping from this research to code that needs to be written:

| Item | File | Status |
|---|---|---|
| Additive Holt-Winters recurrence | `monitor/residuals.py` | Specified — needs implementation |
| MSE parameter optimisation with bounds [0.01–0.5] | `monitor/residuals.py` | Specified — needs implementation |
| Per-metric default parameters (table in §1.4) | `monitor/config.py` | Specified — needs implementation |
| Hyndman initialisation (2×m samples) | `monitor/residuals.py` | Specified — needs implementation |
| 48h warm-up alarm suppression | `backend/analyse/detector.py` | Specified — needs implementation |
| CUSUM with k_s=0.5, h_s=5 | `backend/analyse/detector.py` | Partially implemented in ROADMAP sketch |
| Winsorisation at ±3σ before CUSUM | `backend/analyse/detector.py` | **Missing — add this** |
| MAD-based σ estimation | `backend/analyse/detector.py` | **Missing — add this** |
| Metric-specific variance transforms | `backend/analyse/transforms.py` | **Missing — create this file** |
| CUSUM reset to zero on alarm | `backend/analyse/detector.py` | Implemented in ROADMAP sketch |
| EWMA with λ=0.2, L=3.0 | `backend/analyse/detector.py` | Partially implemented |
| Per-slot σ (168 hour-of-week buckets) | `backend/analyse/detector.py` | Partially implemented |

---

## References

1. Brügner, H. et al. "Holt-Winters Traffic Prediction on Aggregated Flow Data." TU Munich NET-2017-09-1, 2017. https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2017-09-1/NET-2017-09-1_04.pdf
2. Aboode, A. "Anomaly Detection in Time Series Data Based on Holt-Winters." Diva Portal, 2018. https://www.diva-portal.org/smash/get/diva2:1198551/FULLTEXT02.pdf
3. Münz, G. "Traffic Anomaly Detection and Cause Identification." TU Munich, NET-2010-06-1, 2010. https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2010-06-1.pdf
4. Christodoulou, V. et al. "A Combination of CUSUM-EWMA for Anomaly Detection in Time Series." DSAA 2015. https://pure.ulster.ac.uk/en/publications/a-combination-of-cusum-ewma-for-anomaly-detection-in-time-series--3
5. NIST Engineering Statistics Handbook. "CUSUM Average Run Length." Section 6.3.2.3.1. https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc3231.htm
6. Page, E.S. "Continuous Inspection Schemes." Biometrika 41(1/2):100–115, 1954.
7. Hawkins, D.M. & Olwell, D.H. "Cumulative Sum Charts and Charting for Quality Improvement." Springer, 1998.
8. Rousseeuw, P.J. & Croux, C. "Alternatives to the Median Absolute Deviation." JASA 88(424):1273–1283, 1993.
9. Montgomery, D.C. "Introduction to Statistical Quality Control." 6th ed. Wiley, 2009.
10. Lucas, J.M. & Crosier, R.B. "Fast Initial Response for CUSUM Quality-Control Schemes." Technometrics 24(3):199–205, 1982.
11. Karakullukcu, E. et al. "Enhancing Winters exponential smoothing: a novel parameter optimisation approach." Scientific Reports, 2026. https://www.nature.com/articles/s41598-026-48175-1
