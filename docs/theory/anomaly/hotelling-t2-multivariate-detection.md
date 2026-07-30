# Hotelling's T² Multivariate Anomaly Detection Theory
## Research Backlog Topic 12 — Basis for cross-metric anomaly detection in `monitor/` and `collector/`

> **Status:** Research document. Fills backlog item #12 ("Hotelling T² multivariate detection").
> **Scope:** Detecting anomalies that manifest across *combinations* of correlated network metrics (RTT, loss, jitter, interface errors, Wi-Fi RSSI) rather than any single metric crossing its own threshold — complementing, not replacing, the existing per-metric CUSUM/EWMA framework in `docs/anomaly-detection-theory.md`.

---

## Part 1 — Why Per-Metric Thresholds Are Insufficient

The project's existing anomaly-detection stack (CUSUM, EWMA, per `docs/anomaly-detection-theory.md`) evaluates each metric — RTT, loss %, jitter — independently against its own baseline. This is appropriate for detecting a single metric shifting, but network degradations frequently manifest as a *joint* shift across several correlated metrics simultaneously, each individually still within its own normal range, and univariate control charts "do not account for correlations among multiple sensor readings" (Melnikov et al., 2025, on WDN sensor monitoring, directly generalizable to network telemetry). A recent water-distribution-network anomaly framework (SICAMS, Melnikov et al., 2025, arXiv:2512.15685) demonstrates this exact class of problem and is the primary theoretical basis for this document, because network monitoring and pressurized-pipe-network monitoring share the same structural shape: sparse sensors, correlated readings, and the need to distinguish real faults from sensor malfunctions.

### 1.1 The Formal Statistic

Given a vector of correlated metrics \(\mathbf{x} \in \mathbb{R}^s\) (e.g. \(s=4\): RTT p95, loss %, jitter, interface error rate) with sample mean \(\bar{\mathbf{x}}\) and sample covariance \(\mathbf{S}\) estimated from a baseline window of \(n\) observations, Hotelling's \(T^2\) statistic is

\[
T^2 = (\mathbf{x} - \bar{\mathbf{x}})^{\mathsf{T}} \mathbf{S}^{-1} (\mathbf{x} - \bar{\mathbf{x}})
\]

which, provided \(n > s\), follows Hotelling's \(T^2\) distribution with \(s\) and \(n\) degrees of freedom, and can be rescaled to a Fisher \(F\)-statistic:

\[
T^2_F = \frac{n-s}{s(n-1)} T^2 \sim F(s, n-s)
\]

This rescaling is the practically important step — it lets the collector pick a critical threshold \(\theta_1 = F_{1-\alpha}(s, n-s)\) directly from a standard \(F\)-table for a chosen significance level \(\alpha\), rather than needing exact asymptotic chi-squared quantiles, which is more accurate for the modest baseline-window sizes (hundreds, not millions, of samples) realistic for a per-target monitor (Melnikov et al., 2025, §3.2).

As \(n \to \infty\), the statistic converges to \(\chi^2(s)\) — so for large baseline windows the simpler chi-squared threshold is an acceptable approximation, but for the collector's likely per-target sample sizes (tens to low hundreds of samples per adaptive-scheduling state, per `docs/mdp-adaptive-scheduling-theory.md`), the \(F\)-distribution form should be used to avoid understating the threshold and generating false positives.

### 1.2 Why Whitening (Not Raw PCA) Is the Right Preprocessing Step

Melnikov et al. (2025) explicitly compare their whitening-transform approach against the earlier PCA-based burst-detection method of Palau et al. (2012) and find two relevant differences: (1) whitening fully decorrelates all measured variables without requiring separate models per operating regime, whereas PCA-based dimensionality reduction requires segmenting by demand pattern; and (2) the whitened \(T^2\) statistic retains discriminative power even under multiple simultaneous anomalies, which a PCA subspace projection can lose. For this project, "operating regime" is the direct analogue of diurnal/weekly traffic patterns (already handled at the univariate level by the collector's planned time-of-day baselining) — a whitening-based multivariate detector avoids needing a *second*, separate regime-segmentation scheme on top of the one already used for RTT baselining.

---

## Part 2 — Practical Implementation Recipe for This Project

### 2.1 Metric Vector Definition

A reasonable initial vector for a single monitored target/interface: \(\mathbf{x} = (\text{rtt\_p95}, \text{loss\_pct}, \text{jitter}, \text{iface\_error\_rate})\). Wi-Fi-connected targets could add RSSI and retry rate as additional dimensions, consistent with the standalone monitor's existing Wi-Fi link-quality collection (`monitor/wifi_probe.py`).

### 2.2 Temporal Clustering (Reused Directly From the WDN Framework)

Melnikov et al.'s Stage 1 procedure — partition observations into temporal clusters (by hour-of-day/day-of-week plus statistical similarity) and estimate a separate \((\bar{\mathbf{x}}, \mathbf{S})\) pair per cluster — maps directly onto this project's existing need for diurnal-aware baselining, and should reuse the same time-bucketing already planned/implemented for RTT EMA baselines rather than introducing a parallel bucketing scheme.

### 2.3 Hysteresis Thresholding (Avoids Threshold-Flutter)

Rather than a single crossing threshold, use the two-threshold hysteresis rule from the source framework:
- Alarm ON when the moving average of \(T^2_F\) exceeds \(\theta_1(\alpha, k) = F_{1-\alpha}(s, n_k - s)\)
- Alarm OFF (resolved) when it falls back to \(\theta_0(k) = \frac{n_k - s}{n_k - s - 2}\) (the theoretical expected value of the \(F\)-distributed statistic, requiring \(n_k > s+2\))

This is directly analogous to the CUSUM ARL-based hysteresis already used in `docs/anomaly-detection-theory.md`, and should share the same alert-debounce infrastructure rather than introducing a separate alarm state machine.

### 2.4 Per-Sensor Contribution for Root-Cause Attribution

Because the whitened components \(z_i\) of \(\mathbf{z} = \mathbf{W}(\mathbf{x}-\bm{\mu})\) are independent standard normal variables under the null, any subset \(A\) of metrics has a partial sum \(Z^2_A = \sum_{i \in A} z_i^2 \sim \chi^2(|A|)\). This gives a principled way to answer "which metric(s) actually drove this multivariate alarm" — directly useful as an input feature to the existing RCA/causal-inference pipeline (`docs/rca-causal-inference.md`) rather than requiring a separate feature-attribution mechanism.

### 2.5 Change-Point Classification (Abrupt vs. Gradual Degradation)

Melnikov et al. use the PELT change-point algorithm on the \(T^2_F\) time series, then a heuristic paired t-test procedure to classify each detected change point as an "anomaly start"/"anomaly end" and distinguish an abrupt step change from a gradually worsening (incipient) trend. This is directly applicable to distinguishing a sudden link failure (abrupt) from a slowly degrading cable/interface (incipient) — a distinction the current per-metric CUSUM approach does not explicitly classify.

---

## Part 3 — Relationship to Existing Project Documents

| Existing document | Relationship |
|---|---|
| `docs/anomaly-detection-theory.md` (CUSUM/EWMA) | Complementary, not redundant: univariate detectors catch single-metric shifts; \(T^2\) catches joint shifts invisible to any single univariate chart. Both should run concurrently. |
| `docs/rca-causal-inference.md` | The per-sensor \(T^2\) contribution (§2.4) is a natural feature input to the causal-inference pipeline, not a replacement for it. |
| `docs/mdp-adaptive-scheduling-theory.md` | The temporal-cluster baseline windows (§2.2) should reuse the adaptive scheduler's existing state/window bookkeeping rather than duplicating it. |
| `docs/segment-health-arp-dhcp-theory.md` | If ARP/DHCP-derived segment health metrics are added to \(\mathbf{x}\), the same whitening/covariance-estimation machinery applies without modification. |

---

## Part 4 — Known Limitations (Explicitly Flagged, Per Source Paper's Own Caveats)

1. **Requires \(n > s\) baseline samples**, and ideally \(n_k \gg s\) per temporal cluster — a target with too few historical samples in a given time bucket (e.g. a newly added device) cannot yet be scored and should fall back to univariate-only detection until enough history accumulates.
2. **Assumes approximate multivariate normality** of the metric vector under normal conditions; the source paper notes this check "is less critical when the dimensionality of \(\mathbf{x}\) is high" due to the central limit theorem, but for a small 3–4-metric vector, normality of e.g. loss percentage (bounded, often zero-inflated) should be checked empirically before deployment, potentially requiring a transform (e.g. logit or Wilson-score transform of loss %) before whitening.
3. **Covariance matrix estimation from a single historical time series** (rather than repeated randomized simulation, as available in engineered systems like EPANET) constrains cluster granularity — exactly the same empirical-validation requirement already scoped for the MDP scheduler in `docs/gap-analysis/research-guide-for-gap-topics.md`, and the same 30-day backtest dataset can be reused for this purpose.
4. **Distinguishing a real anomaly from a sensor/probe malfunction** requires the same kind of secondary classification heuristic described in Part 2.5; this should not be assumed to "just work" without the paired-interval significance testing the source paper specifies.

---

## Part 5 — Implementation Checklist

| Item | File | Status |
|---|---|---|
| Define initial per-target metric vector (RTT p95, loss %, jitter, iface error rate) | `monitor/` aggregator | Add when building |
| Implement Cholesky whitening + \(T^2_F\) statistic per temporal cluster | new module, e.g. `monitor/multivariate_detector.py` | Add when building |
| Reuse existing diurnal time-bucketing rather than a new bucketing scheme | shared with RTT baselining code | Cross-check on implementation |
| Implement hysteresis alarm (§2.3) sharing debounce infra with CUSUM alerts | `monitor/outage_monitor.py` | Add when building |
| Feed per-metric \(Z^2_A\) contribution into RCA pipeline as an attribution feature | `docs/rca-causal-inference.md` pipeline | Cross-check on implementation |
| Validate multivariate-normality assumption empirically per metric before enabling in production | N/A (validation step) | Add before production enablement |

---

## References

1. Melnikov, O.; Dorofieiev, Y.; Shakhnovskiy, Y.; Truong, H.; Degeler, V. "A Multivariate Statistical Framework for Detection, Classification and Pre-localization of Anomalies in Water Distribution Networks." arXiv:2512.15685, 2025. https://arxiv.org/html/2512.15685v1
2. Palau, C.V. et al. "Burst Detection in Water Distribution Networks Using Multivariate Statistical Process Control." 2012 (cited via Melnikov et al. 2025 as the PCA-based predecessor approach).
3. dionresearch. "hotelling: Hotelling T² tests and multivariate control charts." https://github.com/dionresearch/hotelling
4. zenklinov. "Hotelling-T-Square: multivariate control chart with FAMD/Autoencoder dimension reduction for network intrusion detection." https://github.com/zenklinov/Hotelling-T-Square
5. Killick, R.; Fearnhead, P.; Eckley, I.A. "Optimal detection of changepoints with a linear computational cost" (PELT algorithm). Journal of the American Statistical Association, 2012.
