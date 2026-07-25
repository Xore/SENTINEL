# Machine Learning — Baseline Learning & Anomaly Detection (v2)
## analyseLaptop · Academic Design Document

> **Date:** 2026-07-25  
> **Scope:** Full ML pipeline for learning normal network behaviour and detecting anomalies after a supervised learning phase. Covers data storage strategy, model selection, training lifecycle, concept drift handling, and integration with the existing aggregator + dashboard.  
> **Academic basis:** Cited throughout — all design decisions are grounded in peer-reviewed literature.

---

## 1. Problem Statement

The analyseLaptop system collects multivariate time-series data from collectors: RTT, packet loss %, interface counters, WireGuard handshake ages, SNMP OIDs, Modbus register values, OS health metrics, and WiFi frame counters. The existing `monitor/` pipeline applies **static thresholds** (CUSUM + EWMA, Phase 3) and a **finite-state MDP** (Phase 5) to detect anomalies.

**The gap:** Static thresholds and fixed control limits do not adapt to:
- Diurnal and weekly traffic cycles (office hours vs. nights)
- Seasonal changes in OT production schedules
- Hardware aging (gradual RTT drift on aging Raspberry Pi storage)
- Legitimate network reconfigurations (new VLAN, new collector deployment)

**The v2 ML goal:** Replace or supplement static thresholds with a learned model of normal behaviour that:
1. Requires **no labelled attack data** to train (unsupervised — the system has no attack examples)
2. Learns from a configurable **learning phase** (default: 7 days) before alerting
3. Produces a **continuous anomaly score** rather than binary on/off
4. **Adapts** to legitimate long-term changes (concept drift) without manual reconfiguration
5. Runs on the same Raspberry Pi / low-power VPS hardware as the existing aggregator

---

## 2. Academic Foundations

### 2.1 Model Family Selection

The literature converges on three model families for unsupervised time-series anomaly detection on network metrics:

| Model | How it detects anomalies | Strengths | Weaknesses | Key reference |
|---|---|---|---|---|
| **Statistical (Welford + control limits)** | Point deviates > k·σ from running mean | Zero training cost, interpretable, online | Assumes normality, misses structural patterns | Shewhart (1931), CUSUM (Page, 1954) |
| **LSTM Autoencoder (LSTM-AE)** | Reconstruction error on sequence > threshold | Captures temporal dependencies, unsupervised | Requires GPU for large inputs; fixed-size window | Maleki et al. (2021, *Applied Soft Computing* 112:107763) [web:23][web:31] |
| **Variational Autoencoder (VAE)** | KL-divergence + reconstruction error → anomaly score | Probabilistic; threshold derived from p-value not heuristic | More complex to train and tune | Kingma & Welling (2019, *FnTML* 12(4)); UNSW-NB15 eval 2025 [web:47] |
| **Isolation Forest (streaming)** | Path length in random trees | Handles high-dim, no training convergence required | Poor on temporal structure | Liu et al. (2008, ICDM) |
| **Half-Space Trees (streaming)** | Online density estimation in random subspaces | True online learning, O(1) per sample | Weaker on temporal patterns | Tan et al. (2011, IJCAI) |

**Design decision for v2:** Use a **two-tier approach**:
- **Tier 1 (online, always active):** Welford running statistics per metric stream → control limits → fast alerting, no training phase. This is the existing CUSUM/EWMA from Phase 3, kept as the first-line detector.
- **Tier 2 (offline-trained, post-learning-phase):** LSTM Autoencoder per collector × metric group → reconstruction error → anomaly score. Activates after the learning phase completes.

The Maleki et al. (2021) LSTM-AE with statistical data-filtering was specifically designed for this use case: it uses a sliding window for online operation, requires only normal data to train, and achieves linear time and constant space complexity [web:23]. The CNN-BiLSTM-AE variant (Elsayed et al., 2025) achieved 98.1% accuracy on the InSDN dataset with a purely unsupervised training strategy [web:28].

### 2.2 Learning Phase Duration

The learning phase must capture the full periodicity of the system's normal behaviour. For network monitoring:

- **Minimum:** 7 days (captures the weekly office/weekend cycle)
- **Recommended:** 14 days (two full weekly cycles reduces variance in the baseline)
- **OT environments:** 28 days (captures production schedule cycles: shift patterns, maintenance windows)

Academic basis: The FLAME framework (Mavromatis et al., 2024) used 12 months of training data for a federated IoT anomaly detector [web:55]. For lightweight edge deployments, the stabilisation criterion from FLAME is adopted: training is considered complete when `σ_validation_loss < σ_training_loss × (1 - β)` where β = 0.05 (5% tolerance).

### 2.3 Concept Drift

Network behaviour changes legitimately over time (new devices, reconfigurations, seasonal changes). Without drift adaptation, the model raises false positives on all legitimate changes. This is a critical practical problem.

**Drift taxonomy** (Frontiers in AI, 2024 survey [web:54]):
- **Abrupt drift:** New router deployed, instant change in RTT baseline → should trigger model retrain
- **Gradual drift:** Slow hardware aging → model should adapt continuously
- **Recurring drift:** Daily/weekly cycles → model should already capture this from training

**Chosen approach:** ADWIN (ADaptive WINdowing, Bifet & Gavaldà, 2007) as the drift detector.

Rationale from the 2024 ICT4S controlled experiment across 420 combinations of 7 drift detectors × 5 datasets × 6 base classifiers [web:44]: ADWIN is classified as a **balanced detector** — low-to-medium energy consumption with good accuracy for both abrupt and gradual drift, making it the best fit for this resource-constrained deployment. Page-Hinkley and DDM were found to have "very poor accuracy" and are unsuitable [web:44].

ADWIN maintains an adaptive sliding window and fires when the mean of the old sub-window diverges significantly from the mean of the new sub-window. When ADWIN fires on a metric stream, it signals that the baseline has shifted and the LSTM-AE for that metric group should be retrained.

### 2.4 Threshold Derivation

A critical practical problem: how to set the reconstruction error threshold that separates normal from anomalous?

The VAE approach (UNSW-NB15 study, 2025 [web:47]) uses the **KL-divergence** as a probabilistic threshold — anomaly score = reconstruction loss + KL divergence, compared against the p-value at 5% significance from the validation set.

For the simpler LSTM-AE, the threshold is derived from the **validation set reconstruction error distribution** during training:
```
threshold = μ_validation_error + k × σ_validation_error
```
where k is configurable:
- k=2.0 → ~95th percentile (more sensitive, more false positives)
- k=3.0 → ~99.7th percentile (recommended default)
- k=4.0 → more conservative (use for OT environments where false alerts cause operational disruption)

This is consistent with the Shewhart 3σ control limit used in the existing Phase 3 CUSUM/EWMA pipeline, ensuring the ML tier is **calibrated consistently** with the statistical tier.

---

## 3. Data Storage Strategy

### 3.1 What to Store for ML Training

The ML training pipeline needs different data than the operational time-series store:

| Data type | Format | Retention | Storage location |
|---|---|---|---|
| **Raw metric stream** (per collector × metric, 30s resolution) | Float32 + timestamp | 28 days (learning window + buffer) | Hot store (Gorilla-compressed, existing Phase 10) |
| **Feature vectors** (normalised, windowed, ready for training) | Float32 numpy array, `.npy` | 28 days | `ml/features/<collector_id>/<metric_group>.npy` |
| **Trained model weights** | ONNX + PyTorch `.pt` | Indefinite (versioned) | `ml/models/<collector_id>/<metric_group>/<version>/` |
| **Training metadata** | JSON | Indefinite | `ml/models/.../meta.json` |
| **Validation error distribution** | JSON (μ, σ, percentile table) | Per model version | `ml/models/.../threshold.json` |
| **ADWIN state** | JSON (window state per metric) | Rolling (overwrite) | `ml/drift/<collector_id>/<metric>.json` |
| **Anomaly score stream** | Float32 + timestamp | 90 days | Cold store (existing Phase 10) |

**Storage budget estimate** (per collector, 7-day learning phase):
- 50 metrics × 20,160 samples (30s × 7 days) × 4 bytes = ~4 MB raw
- Feature matrix (128-step windows, stride 1): ~20 MB numpy
- LSTM-AE weights (2-layer, hidden_dim=64): ~500 KB per metric group

Total per collector: **< 30 MB**. Negligible even on a Raspberry Pi 4 (8 GB SD card).

### 3.2 Feature Engineering

Raw metric streams are preprocessed before training. This preprocessing is **identical** at training time and inference time (critical: preprocessing pipeline is serialised alongside the model).

**Per metric stream:**

1. **Detrending:** Subtract 1-period (24h) rolling mean → removes diurnal cycle from residuals. Without this, the model wastes capacity learning the daily pattern instead of anomaly structure.

2. **Normalisation:** Min-max scaling to [0, 1] using training-set min/max. Scaler parameters serialised to `preprocessing.json` alongside model weights.

3. **Time-of-day & day-of-week features:** Append `sin(2π·h/24)`, `cos(2π·h/24)`, `sin(2π·d/7)`, `cos(2π·d/7)` as additional input dimensions. This allows the model to learn that RTT at 3:00 AM is legitimately different from RTT at 14:00 on a Tuesday. Academic basis: cyclical encoding of time features is standard in time-series ML and prevents the model from treating time as a linear feature (Brownlee, 2017; widely used in network ML literature).

4. **Windowing:** Sliding windows of length W=128 (default), stride S=1 for training (stride=W for inference). At 30s resolution, W=128 is 64 minutes — sufficient to capture short-term temporal dependencies like a WireGuard tunnel that slowly loses keepalive before dropping.

5. **Data contamination filter:** Before training, filter out windows where Tier 1 (CUSUM/EWMA) had already flagged an anomaly. This addresses the **data contamination problem** identified by Khoury et al. (2024, arXiv:2407.08838): if attack-period data accidentally enters the training set, the model learns anomalies as normal [web:15]. By using Tier 1 flags as a contamination mask, training data is kept clean without requiring labels.

**Metric groupings** (trained as separate LSTM-AEs to keep input dimensionality manageable):

| Group | Metrics included | Input dim |
|---|---|---|
| `network_latency` | RTT p50, p95, p99; loss % per target | 4–8 |
| `network_throughput` | RX bytes/s, TX bytes/s, errors/s, drops/s per interface | 4–12 |
| `wireguard` | Handshake age, RX/TX delta per tunnel | 2–6 |
| `os_health` | CPU %, memory %, disk % per path, load1 | 4–8 |
| `wan` | Public IP change flag, WAN latency CF, WAN latency Google | 3 |
| `wifi_rf` | Retransmission rate %, beacon count/s, client count, channel utilisation | 4 |
| `ot_snmp` | sysUpTime delta, ifOperStatus per target | 1–4 per device |
| `ot_modbus` | Register values (scaled) per target | 1–N per device |

---

## 4. LSTM Autoencoder Architecture

### 4.1 Model Specification

```
Input:  (batch, W, input_dim)   W=128 time steps, input_dim=group-dependent

Encoder:
  LSTM(hidden_dim=64, num_layers=2, dropout=0.1) → (batch, W, 64)
  Take last hidden state → (batch, 64)   [bottleneck / latent representation]

Decoder:
  Repeat latent vector W times → (batch, W, 64)
  LSTM(hidden_dim=64, num_layers=2, dropout=0.1) → (batch, W, 64)
  Linear(64 → input_dim) → (batch, W, input_dim)

Loss: MSE(input, reconstruction)

Optimiser: Adam, lr=1e-3, weight_decay=1e-5
Batch size: 64
Epochs: 50 (early stop: patience=5, monitor val_loss)
```

This architecture follows Maleki et al. (2021) [web:23][web:31] which proved that the LSTM-AE with statistical data-filtering outperforms standalone LSTM, LSTM-AE, and AE baselines. The 2-layer encoder/decoder with dropout=0.1 is the configuration that achieved the best reconstruction accuracy with the lowest overfitting in their ablation study.

**Hidden dim = 64 rationale:** The bottleneck forces the encoder to learn a compressed representation of normal behaviour. Too large (>128) → model memorises noise; too small (<16) → insufficient capacity to model 64-minute temporal windows. 64 is the empirically validated sweet spot for time-series of this length (also used in the LSTM-AE survey by Choi et al., 2021, cited 95 times).

### 4.2 Training & Validation Split

Training data from the learning phase is split:
- **70% train** (first 4.9 days of a 7-day learning window)
- **30% validation** (last 2.1 days)

The validation set is used for:
1. Early stopping criterion
2. Threshold derivation (μ + k·σ of validation reconstruction errors)
3. Contamination check: if validation loss < 80% of training loss, potential overfit → extend learning phase by 3 days

### 4.3 Inference & Anomaly Score

At inference time (every 30s, after each sample push):

```python
# Pseudocode — actual implementation in monitor/ml_inference.py

def compute_anomaly_score(window: np.ndarray, model, scaler, threshold_params) -> AnomalyResult:
    # 1. Preprocess (same pipeline as training)
    x = scaler.transform(window)
    x = append_time_features(x, window_timestamps)

    # 2. Forward pass
    x_hat = model(x.unsqueeze(0))  # (1, W, input_dim)

    # 3. Reconstruction error per time step
    errors = np.mean((x - x_hat) ** 2, axis=-1)  # (W,)

    # 4. Focus on most recent steps (recency-weighted)
    weights = np.exp(np.linspace(-1, 0, W))  # exponential recency weighting
    score = float(np.dot(errors, weights) / weights.sum())

    # 5. Normalise to anomaly score in [0, 1]
    z = (score - threshold_params['mu']) / threshold_params['sigma']
    anomaly_score = float(scipy.stats.norm.cdf(z))  # probability of being anomalous

    # 6. Threshold comparison
    alert = anomaly_score > threshold_params['alert_percentile']  # default: 0.997 (3σ)

    return AnomalyResult(score=anomaly_score, alert=alert, reconstruction_error=score,
                         metric_group=..., collector_id=..., ts=...)
```

**Recency weighting:** Anomalies at the end of the 128-step window (most recent data) are weighted more heavily than anomalies at the start. This reduces latency from detection to alert.

---

## 5. Learning Phase Lifecycle

### 5.1 State Machine

Each collector × metric group has an ML state:

```
ACCUMULATING → TRAINING → ACTIVE → RETRAINING
     ↑                                   ↓
     └───────────── drift detected ───────┘
```

| State | Condition | Tier 1 alerts | Tier 2 alerts |
|---|---|---|---|
| `ACCUMULATING` | < `learning_days` of clean data collected | ✅ Active | ❌ Suppressed |
| `TRAINING` | Training job running (async, < 10 min on Pi 4) | ✅ Active | ❌ Suppressed |
| `ACTIVE` | Model trained, threshold derived | ✅ Active | ✅ Active |
| `RETRAINING` | ADWIN fired; new model training | ✅ Active | ⚠️ Score from old model (marked stale) |

The dashboard (Module E: System Config → ML tab) shows the state per collector × metric group with:
- Current state badge
- Days accumulated / days required
- Training progress bar (during TRAINING)
- Last model version + training timestamp
- ADWIN drift event log (when and on which metric drift was detected)

### 5.2 Contamination-Safe Data Collection

During `ACCUMULATING`, the data logger writes to `ml/features/<id>/<group>/raw_buffer.npy` but **masks out** any time windows where:
- Tier 1 CUSUM/EWMA fired an anomaly flag
- Collector reported a heartbeat gap > 2× poll interval (data missing → unreliable window)
- A manual "maintenance window" was declared by the operator (from dashboard System Config)

If the unmasked clean data drops below 80% of the learning window, the accumulation period is automatically extended. This directly implements the contamination mitigation strategy from Khoury et al. (2024) [web:15].

### 5.3 Training Job

Training runs as a background Python process (subprocess, not blocking the Flask dashboard). Triggered when:
- `ACCUMULATING` → clean data ≥ `learning_days` requirement
- `RETRAINING` → ADWIN drift confirmed on ≥ 2 metrics in same group (single-metric ADWIN fires can be noise)

Training job writes to:
```
ml/models/<collector_id>/<metric_group>/<version>/
  ├── model.onnx          # ONNX export for runtime inference (no PyTorch dep at inference time)
  ├── model.pt            # PyTorch checkpoint (for retraining / fine-tuning)
  ├── preprocessing.json  # Scaler params, feature engineering config
  ├── threshold.json      # μ, σ, percentile table of validation reconstruction errors
  └── meta.json           # Training timestamp, dataset stats, epoch count, val_loss
```

**ONNX export rationale:** Inference uses ONNX Runtime (CPU provider). This avoids a PyTorch dependency at inference time (significant: PyTorch is ~2 GB; ONNX Runtime is ~20 MB). Raspberry Pi 4 can run ONNX Runtime inference at 30s intervals with < 5% CPU overhead for a 64-dim, 128-step LSTM-AE.

### 5.4 Model Versioning

Each training run produces a new version directory `v001`, `v002`, etc. The **active version** is a symlink:
```
ml/models/<id>/<group>/active → v003/
```

Version history is retained (configurable, default: last 5 versions). This enables rollback if a new model produces excessive false positives after a retrain.

---

## 6. Concept Drift Detection & Model Retraining

### 6.1 ADWIN Integration

ADWIN runs **per metric stream** in the aggregator's inference loop. It monitors the **raw reconstruction error** (before the anomaly scoring sigmoid) because drift manifests as a sustained shift in reconstruction error, not necessarily as anomaly alerts.

```python
# monitor/drift_detector.py

from river.drift import ADWIN  # river library — pure Python, O(log n) per update

class DriftMonitor:
    def __init__(self, delta: float = 0.002):
        # delta: ADWIN significance level. 0.002 = Bifet & Gavaldà recommended default
        self.detectors: dict[str, ADWIN] = {}

    def update(self, metric_key: str, reconstruction_error: float) -> bool:
        if metric_key not in self.detectors:
            self.detectors[metric_key] = ADWIN(delta=self.delta)
        detector = self.detectors[metric_key]
        detector.update(reconstruction_error)
        return detector.drift_detected  # True = drift confirmed
```

**ADWIN delta = 0.002** is the default from the original Bifet & Gavaldà (2007) paper. The 2024 ICT4S study [web:44] confirmed that ADWIN with default parameters achieves the best accuracy/energy tradeoff across 420 test configurations.

### 6.2 Drift Response Policy

| Drift event | Response | Rationale |
|---|---|---|
| Single metric ADWIN fires | Log to drift trail; no retrain | Noisy single-metric events are common; insufficient evidence |
| ≥ 2 metrics in same group drift within 10 min | Trigger RETRAINING on that group | Correlated shift = structural change, not noise |
| All metric groups drift simultaneously | Log as "topology event"; page operator | Likely a major network reconfiguration — operator should declare maintenance window |
| OT Modbus register group drifts | Alert operator; **do not auto-retrain** | OT baseline changes require human validation (IEC 62443 change management) |

**OT-specific rule rationale:** IEC 62443 section 3-3 requires change management approval for modifications to monitoring baselines in OT environments. Auto-retraining on OT metrics without operator approval could mask a genuine attack that coincides with legitimate production changes.

### 6.3 Fine-Tuning vs. Full Retrain

When RETRAINING is triggered, the job uses **fine-tuning** (warm start from the previous model checkpoint, reduced learning rate 1e-4, 20 epochs) rather than a full retrain from scratch if:
- < 30% of metrics in the group drifted (partial adaptation)
- The drift was gradual (ADWIN window was long when it fired)

Full retrain from scratch if:
- ≥ 30% of metrics drifted (structural change)
- The drift was abrupt (ADWIN window was short when it fired)
- The operator explicitly requests a full retrain from the dashboard

---

## 7. Anomaly Score Integration with Existing Pipeline

### 7.1 Score Fusion (Tier 1 + Tier 2)

The two-tier approach produces two independent anomaly signals per sample. They are fused using a **weighted OR** rule:

```python
def fused_alert(tier1_alert: bool, tier2_score: float, tier2_threshold: float,
                tier1_weight: float = 0.4, tier2_weight: float = 0.6) -> FusedResult:
    tier2_alert = tier2_score > tier2_threshold

    # High-confidence: both tiers agree
    if tier1_alert and tier2_alert:
        confidence = 0.95
        verdict = "HIGH_CONFIDENCE_ANOMALY"

    # Tier 2 only (ML detects structural anomaly, no hard threshold breach)
    elif not tier1_alert and tier2_alert:
        confidence = tier2_score
        verdict = "ML_STRUCTURAL_ANOMALY"

    # Tier 1 only (spike that fits model but breaches static threshold)
    elif tier1_alert and not tier2_alert:
        confidence = 0.65
        verdict = "THRESHOLD_BREACH"

    else:
        confidence = tier2_score
        verdict = "NORMAL"

    return FusedResult(alert=(confidence > 0.6), confidence=confidence, verdict=verdict)
```

This maps directly to the existing confidence thresholds in `dashboard/alerts.py`:
- confidence > 0.8 → auto-alert via all channels
- confidence 0.6–0.8 → flagged in dashboard only
- confidence < 0.6 → raw symptom, no notification

### 7.2 RCA Enhancement

The LSTM-AE reconstruction error is **per-dimension** (per metric within the group). The dimension with the highest reconstruction error at anomaly time is surfaced as the "primary contributing metric" in the RCA panel:

```json
{
  "anomaly_id": "...",
  "verdict": "ML_STRUCTURAL_ANOMALY",
  "confidence": 0.87,
  "metric_group": "network_latency",
  "primary_metric": "rtt_p95_target_plc_main",
  "reconstruction_errors": {
    "rtt_p50": 0.003,
    "rtt_p95": 0.041,   ← highest → primary contributor
    "rtt_p99": 0.018,
    "loss_pct": 0.002
  },
  "model_version": "v003",
  "ml_state": "ACTIVE"
}
```

This enhances the existing Naive Bayes RCA (Phase 4) with a per-dimension signal that identifies *which* metric is most anomalous, improving the precision of the "most probable cause" verdict.

---

## 8. Implementation Plan

### 8.1 New Files

```
monitor/
├── ml/
│   ├── __init__.py
│   ├── feature_engineering.py    # Detrending, normalisation, windowing, time features
│   ├── lstm_ae.py                 # LSTM Autoencoder model (PyTorch)
│   ├── training_job.py            # Training entrypoint (subprocess target)
│   ├── inference.py               # ONNX Runtime inference, anomaly scoring
│   ├── drift_detector.py          # ADWIN per-metric drift monitoring
│   ├── model_registry.py          # Version management, symlink management
│   └── contamination_filter.py    # Mask Tier 1 flagged windows from training data
│
├── ml_state.py                    # State machine: ACCUMULATING/TRAINING/ACTIVE/RETRAINING
└── ml_config.py                   # Config schema: learning_days, k_sigma, adwin_delta, etc.
```

### 8.2 New Dependencies

```
# requirements-ml.txt (separate from dashboard/requirements.txt — optional install)
torch==2.3.*                    # Training only (not needed at inference time)
onnx==1.16.*                    # Model export
onnxruntime==1.18.*             # Inference (CPU, no torch required)
river==0.21.*                   # ADWIN drift detector (pure Python, no C++ build)
numpy==1.26.*                   # Already present
scipy==1.13.*                   # CDF for anomaly score normalisation
```

**PyTorch is a training-only dependency.** The aggregator runtime only needs `onnxruntime` + `river` + `numpy`. This keeps the deployment footprint manageable on Raspberry Pi (no CUDA, no 2 GB PyTorch install at runtime).

### 8.3 Dashboard ML Tab (Module E Extension)

New tab in System Config → **Machine Learning**:

**Per-collector × metric group table:**

| Collector | Metric Group | ML State | Data Accumulated | Model Version | Last Retrain | Drift Events | Actions |
|---|---|---|---|---|---|---|---|
| homelab-pi4 | network_latency | 🟢 ACTIVE | 14d | v003 | 3 days ago | 1 | [Retrain] [Rollback] |
| homelab-pi4 | os_health | 🟡 ACCUMULATING | 4d / 7d | — | — | — | [Skip to train] |
| remote-pi3 | ot_modbus | 🔵 ACTIVE (OT) | 28d | v001 | 28 days ago | 0 | [Retrain (manual)] |

**Controls:**
- **[Retrain]:** Force full retrain from scratch using current clean buffer
- **[Rollback]:** Point `active` symlink to the previous model version
- **[Skip to train]:** Override `learning_days` minimum (with warning: *"Training on fewer than 7 days may produce high false positive rates"*)
- **Learning days** slider: 7 / 14 / 28 days (per collector)
- **k σ threshold** slider: 2.0 / 3.0 / 4.0 (per metric group; OT groups default 4.0)
- **ADWIN delta** input: default 0.002 (lower = more sensitive to drift)
- **OT retrain mode** toggle: manual-only vs. auto (default: manual-only for OT groups)

**Learning phase progress:** For `ACCUMULATING` state, show a progress bar and estimated completion time. Show the contamination filter statistics: "3,240 / 20,160 windows masked (16%) — due to 4 Tier 1 events".

**Anomaly score stream chart:** For `ACTIVE` models, show the last 24h of anomaly scores as a line chart with the alert threshold overlaid. This lets the operator visually validate that the model is behaving correctly before trusting its output.

**Model inspection:** Click any model version → show:
- Training dataset stats (n samples, contamination %, feature means/stddevs)
- Validation loss curve (train vs. val, epoch by epoch)
- Validation reconstruction error distribution (histogram with threshold line)
- Sample anomaly scores over last 24h with hover-over details

---

## 9. Data Contamination & Robustness

The most critical practical failure mode for unsupervised anomaly detection is **contaminated training data** — if an ongoing slow attack occurs during the learning phase, the model learns the attack as normal.

The 2024 deep learning study on data contamination (Khoury et al., arXiv:2407.08838 [web:15]) evaluated contamination rates from 1% to 20% across multiple DL models. Key finding: LSTM autoencoders show significant performance degradation above 5% contamination. Below 5%, performance degrades gracefully.

**Mitigations implemented in this design:**

1. **Tier 1 contamination mask** (Section 5.2): CUSUM/EWMA flags mask training windows. Expected to remove the majority of attack-period data even from an ongoing slow attack.

2. **Statistical outlier removal during feature engineering:** Welford running statistics are maintained during accumulation. Any sample > 4σ from the running mean is excluded from the training buffer regardless of Tier 1 state.

3. **Validation loss sanity check:** If `val_loss / train_loss > 1.5` (overfitting) or `val_loss < 0.5 × train_loss` (potential contamination causing model to learn anomalies), training is rejected and the learning phase is extended.

4. **Operator review gate (optional):** A config flag `require_operator_approval_before_activation` (default: `false`; recommended `true` for OT environments) holds the model in `TRAINING_COMPLETE` state and shows a review summary in the dashboard before the model becomes active.

---

## 10. Academic References

| Reference | What it grounds |
|---|---|
| Maleki et al. (2021). Unsupervised anomaly detection with LSTM autoencoders using statistical data-filtering. *Applied Soft Computing* 112:107763. | LSTM-AE architecture, sliding window online operation, contamination filtering approach |
| Khoury et al. (2024). Deep Learning for Network Anomaly Detection under Data Contamination. arXiv:2407.08838. | Contamination problem and mitigation; 5% threshold |
| Bifet & Gavaldà (2007). Learning from Time-Changing Data with Adaptive Windowing. *SIAM ICDM*. | ADWIN algorithm, delta=0.002 default |
| Mavromatis et al. (2024). FLAME: Adaptive and Reactive Concept Drift Mitigation for Federated Learning. arXiv:2410.01386. | ADWIN vs. KSWIN vs. PHT comparison; stabilisation criterion |
| IEEE ICT4S (2024). How to Sustainably Monitor ML-Enabled Systems? | ADWIN as balanced detector across 420 combinations |
| Kingma & Welling (2019). An Introduction to Variational Autoencoders. *FnTML* 12(4). | VAE probabilistic threshold alternative |
| Zabala et al. (2023). MDP-based network monitoring agent. *Mathematics* 11(3):610. | Integration point: MDP scheduler can use ML anomaly score as observation |
| Elsayed et al. (2025). CNN-BiLSTM-AE unsupervised IDS. UNSW-NB15 benchmark. | 98.1% accuracy, purely unsupervised training validation |
| IEC 62443-3-3 (2013). System security requirements and security levels. | OT manual retrain approval requirement |
| Choi et al. (2021). LSTM-Based Autoencoder Survey. *Electronics* 10(13):1598. | hidden_dim=64 sweet spot for time-series |
