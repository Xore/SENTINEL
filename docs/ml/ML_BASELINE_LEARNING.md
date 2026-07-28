# Machine Learning — Baseline Learning & Anomaly Detection (v2)
## analyseLaptop · Academic Design Document

> **Date:** 2026-07-25 (revised against ARCHITECTURE-V2.md)  
> **Scope:** Full ML pipeline for learning normal network behaviour and detecting anomalies after a learning phase. Covers data storage strategy, model selection, training lifecycle, concept drift handling, and integration with the v2 service architecture.  
> **Architecture basis:** `docs/architecture/ARCHITECTURE-V2.md` — services are `backend/analyse/` (Python), `backend/ingest/` (Go), `backend/api/` (Go/Gin), storage is VictoriaMetrics + PostgreSQL, frontend is SvelteKit. **No Flask dashboard. No `monitor/` aggregator.**  
> **Academic basis:** Cited throughout — all design decisions are grounded in peer-reviewed literature.

---

## 1. Problem Statement

The analyseLaptop v2 system collects multivariate time-series data from collectors via OTLP/gRPC: RTT, packet loss %, interface counters, SNMP OIDs, Modbus register values, OS health metrics, and WiFi frame counters. These are stored in **VictoriaMetrics** (time-series) and **PostgreSQL** (events, anomalies, RCA results). The `backend/analyse/` service applies **static thresholds** (CUSUM + EWMA, Phase 3) and a **finite-state MDP** (Phase 5) to detect anomalies.

**The gap:** Static thresholds and fixed control limits do not adapt to:
- Diurnal and weekly traffic cycles (office hours vs. nights)
- Seasonal changes in OT production schedules
- Hardware aging (gradual RTT drift on aging Raspberry Pi storage)
- Legitimate network reconfigurations (new VLAN, new collector deployment)

**The v2 ML goal:** Extend `backend/analyse/` with a learned model of normal behaviour that:
1. Requires **no labelled attack data** to train (unsupervised — the system has no attack examples at training time)
2. Learns from a configurable **learning phase** (default: 7 days) before raising ML alerts
3. Produces a **continuous anomaly score** rather than binary on/off
4. **Adapts** to legitimate long-term changes (concept drift) without manual reconfiguration
5. Runs within the `backend/analyse/` Python process — no new service required

---

## 2. Academic Foundations

### 2.1 Model Family Selection

The literature converges on three model families for unsupervised time-series anomaly detection on network metrics:

| Model | How it detects anomalies | Strengths | Weaknesses | Key reference |
|---|---|---|---|---|
| **Statistical (Welford + control limits)** | Point deviates > k·σ from running mean | Zero training cost, interpretable, online | Assumes normality, misses structural patterns | Shewhart (1931), CUSUM (Page, 1954) |
| **LSTM Autoencoder (LSTM-AE)** | Reconstruction error on sequence > threshold | Captures temporal dependencies, unsupervised | Fixed-size window; training cost | Maleki et al. (2021, *Applied Soft Computing* 112:107763) |
| **Variational Autoencoder (VAE)** | KL-divergence + reconstruction error → anomaly score | Probabilistic; threshold from p-value, not heuristic | More complex to train and tune | Kingma & Welling (2019, *FnTML* 12(4)); UNSW-NB15 eval 2025 |
| **Isolation Forest (streaming)** | Path length in random trees | High-dimensional, no convergence required | Poor on temporal structure | Liu et al. (2008, ICDM) |
| **Half-Space Trees (streaming)** | Online density estimation in random subspaces | True online, O(1) per sample | Weaker on temporal patterns | Tan et al. (2011, IJCAI) |

**Design decision for v2:** Use a **two-tier approach**, both running inside `backend/analyse/`:

- **Tier 1 (online, always active):** Welford running statistics per metric stream → CUSUM/EWMA control limits → fast alerting, no training phase. This is the existing Phase 3 detector, unchanged.
- **Tier 2 (offline-trained, post-learning-phase):** LSTM Autoencoder per collector × metric group → reconstruction error → anomaly score. Activates after the learning phase completes.

The Maleki et al. (2021) LSTM-AE with statistical data-filtering was designed for exactly this use case: sliding window online operation, requires only normal data to train, linear time and constant space complexity. The CNN-BiLSTM-AE variant (Elsayed et al., 2025) achieved 98.1% accuracy on the InSDN dataset with a purely unsupervised training strategy.

### 2.2 Learning Phase Duration

The learning phase must capture the full periodicity of the system’s normal behaviour:

- **Minimum:** 7 days (captures the weekly office/weekend cycle)
- **Recommended:** 14 days (two full weekly cycles reduces variance in the baseline)
- **OT environments:** 28 days (captures production schedule cycles: shift patterns, maintenance windows)

Academic basis: The FLAME framework (Mavromatis et al., 2024) used 12 months of training data for a federated IoT anomaly detector. For lightweight edge deployments, the stabilisation criterion from FLAME is adopted: training is considered complete when `σ_validation_loss < σ_training_loss × (1 - β)` where β = 0.05 (5% tolerance).

### 2.3 Concept Drift

Network behaviour changes legitimately over time (new devices, reconfigurations, seasonal changes). Without drift adaptation, the model raises false positives on all legitimate changes.

**Drift taxonomy** (Frontiers in AI, 2024 survey):
- **Abrupt drift:** New router deployed, instant change in RTT baseline → triggers model retrain
- **Gradual drift:** Slow hardware aging → model should adapt continuously
- **Recurring drift:** Daily/weekly cycles → model captures this from training

**Chosen approach:** ADWIN (ADaptive WINdowing, Bifet & Gavaldà, 2007) as the drift detector.

Rationale from the 2024 ICT4S controlled experiment across 420 combinations of 7 drift detectors × 5 datasets × 6 base classifiers: ADWIN is classified as a **balanced detector** — low-to-medium energy consumption with good accuracy for both abrupt and gradual drift. Page-Hinkley and DDM were found to have “very poor accuracy” and are unsuitable.

ADWIN maintains an adaptive sliding window and fires when the mean of the old sub-window diverges significantly from the mean of the new sub-window. When ADWIN fires on a metric stream, it signals that the baseline has shifted and the LSTM-AE for that metric group should be retrained.

### 2.4 Threshold Derivation

For the LSTM-AE, the threshold is derived from the **validation set reconstruction error distribution** during training:
```
threshold = μ_validation_error + k × σ_validation_error
```
where k is configurable:
- k=2.0 → ~95th percentile (more sensitive, more false positives)
- k=3.0 → ~99.7th percentile (recommended default)
- k=4.0 → more conservative (OT environments where false alerts cause operational disruption)

This is consistent with the Shewhart 3σ control limit used in the existing Tier 1 CUSUM/EWMA pipeline, ensuring both tiers are **calibrated consistently**.

---

## 3. Data Storage Strategy

### 3.1 Where ML Data Lives in the v2 Architecture

All operational data in v2 is stored in VictoriaMetrics (time-series) and PostgreSQL (events/config). The ML pipeline adds a third storage layer: a **model store** on the local filesystem of the `backend/analyse/` container, and two new PostgreSQL tables.

| Data type | Format | Retention | Where |
|---|---|---|---|
| **Raw metric stream** (30s resolution) | Float32 + timestamp | VM retention (90d default) | **VictoriaMetrics** — queried by `backend/analyse/` via MetricsQL HTTP API |
| **ML training buffer** (windowed, normalised) | Float32 numpy `.npy` | 28 days (learning window + buffer) | `backend/analyse/` container volume: `ml/features/<collector_id>/<group>.npy` |
| **Trained model weights** | ONNX + PyTorch `.pt` | Indefinite (versioned) | `backend/analyse/` container volume: `ml/models/<collector_id>/<group>/<version>/` |
| **Training metadata** | JSON | Indefinite | `ml/models/.../meta.json` |
| **Threshold parameters** | JSON (μ, σ, percentile table) | Per model version | `ml/models/.../threshold.json` |
| **ADWIN state** | Serialised Python object | Rolling (overwrite on retrain) | `ml/drift/<collector_id>/<metric>.pkl` |
| **ML state per collector × group** | Row | Indefinite | **PostgreSQL** `ml_model_state` table |
| **Anomaly score stream** | MetricsQL labels + float value | 90 days | **VictoriaMetrics** (written by `backend/analyse/` via Prometheus remote-write) |
| **ML anomaly events** | Row (linked to `anomalies` table) | Indefinite | **PostgreSQL** `anomalies` table (existing schema, new `detector=ml_tier2` column value) |

**No new storage service is needed.** The `backend/analyse/` container volume stores models; VictoriaMetrics and PostgreSQL store everything operational. This is consistent with the v2 architecture constraint of no additional services below 500 collectors.

### 3.2 New PostgreSQL Tables

```sql
-- ML state per collector × metric group
CREATE TABLE ml_model_state (
    collector_id   TEXT        NOT NULL REFERENCES collectors(id),
    metric_group   TEXT        NOT NULL,
    state          TEXT        NOT NULL CHECK (state IN ('ACCUMULATING','TRAINING','ACTIVE','RETRAINING')),
    active_version TEXT,                     -- e.g. 'v003'
    learning_days  INT         NOT NULL DEFAULT 7,
    k_sigma        FLOAT       NOT NULL DEFAULT 3.0,
    data_start_ts  TIMESTAMPTZ,
    clean_windows  INT         DEFAULT 0,
    total_windows  INT         DEFAULT 0,
    last_trained_at TIMESTAMPTZ,
    last_retrain_trigger TEXT, -- 'adwin_drift' | 'manual' | 'initial'
    PRIMARY KEY (collector_id, metric_group)
);

-- ADWIN drift events log
CREATE TABLE ml_drift_events (
    id             BIGSERIAL   PRIMARY KEY,
    collector_id   TEXT        NOT NULL REFERENCES collectors(id),
    metric_group   TEXT        NOT NULL,
    metric_key     TEXT        NOT NULL,
    detected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    adwin_delta    FLOAT       NOT NULL,
    triggered_retrain BOOLEAN  DEFAULT FALSE
);
```

These tables are read by the `backend/api/` (Go/Gin) service and exposed at `GET /api/v1/ml/state` and `GET /api/v1/ml/drift-events` for the SvelteKit frontend.

### 3.3 Feature Engineering

Raw metrics are queried from VictoriaMetrics via MetricsQL HTTP API inside `backend/analyse/`. The preprocessing pipeline is **identical at training time and inference time** — the scaler parameters are serialised to `preprocessing.json` alongside the model weights.

**Per metric stream:**

1. **Detrending:** Subtract 1-period (24h) rolling mean → removes diurnal cycle from residuals. Without this, the model wastes capacity learning the daily pattern instead of anomaly structure.

2. **Normalisation:** Min-max scaling to [0, 1] using training-set min/max. Scaler parameters serialised to `preprocessing.json`.

3. **Cyclical time features:** Append `sin(2π·h/24)`, `cos(2π·h/24)`, `sin(2π·d/7)`, `cos(2π·d/7)` as additional input dimensions. This allows the model to learn that RTT at 3:00 AM is legitimately different from RTT at 14:00 on a Tuesday. Standard cyclical time encoding (Brownlee, 2017; used across network ML literature).

4. **Windowing:** Sliding windows of length W=128 (default), stride S=1 for training (stride=W for inference). At 30s resolution, W=128 is 64 minutes — sufficient to capture temporal dependencies such as latency and loss gradually degrading before an outage.

5. **Data contamination filter:** Before training, filter out windows where Tier 1 (CUSUM/EWMA) had already flagged an anomaly in the PostgreSQL `anomalies` table. This addresses the **data contamination problem** (Khoury et al., 2024, arXiv:2407.08838): if attack-period data accidentally enters the training set, the model learns anomalies as normal. By using Tier 1 flags from PostgreSQL as a contamination mask, training data is kept clean without requiring labels.

**Metric groupings** (separate LSTM-AE per group keeps input dimensionality manageable):

| Group | Metrics (MetricsQL label selectors) | Input dim |
|---|---|---|
| `network_latency` | RTT p50, p95, p99; loss % per target | 4–8 |
| `network_throughput` | RX bytes/s, TX bytes/s, errors/s, drops/s per interface | 4–12 |
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

Loss:      MSE(input, reconstruction)
Optimiser: Adam, lr=1e-3, weight_decay=1e-5
Batch:     64
Epochs:    50 (early stop: patience=5, monitor val_loss)
```

Architecture follows Maleki et al. (2021), whose 2-layer encoder/decoder with dropout=0.1 outperforms standalone LSTM, LSTM-AE, and vanilla AE baselines. **Hidden dim=64 rationale:** too large (>128) → model memorises noise; too small (<16) → insufficient capacity to model 64-minute windows. 64 is the empirically validated sweet spot (Choi et al., 2021, cited 95 times).

### 4.2 Training & Validation Split

- **70% train** (first 4.9 days of a 7-day learning window)
- **30% validation** (last 2.1 days)

The validation set is used for: (1) early stopping, (2) threshold derivation (μ + k·σ of validation reconstruction errors), (3) contamination check — if `val_loss < 0.8 × train_loss`, potential overfit → extend learning phase by 3 days.

### 4.3 Inference & Anomaly Score

Inference runs inside `backend/analyse/` on the 60s batch cycle (same cadence as CUSUM/EWMA). For each collector × metric group with an ACTIVE model:

```python
# backend/analyse/ml/inference.py

import onnxruntime as ort
import numpy as np
import scipy.stats

def compute_anomaly_score(
    window: np.ndarray,          # shape (W, input_dim)
    session: ort.InferenceSession,
    scaler_params: dict,
    threshold_params: dict
) -> dict:
    # 1. Preprocess (identical to training pipeline)
    x = min_max_scale(window, scaler_params)
    x = append_cyclic_time_features(x, window_timestamps)

    # 2. ONNX inference (CPU provider — no PyTorch at runtime)
    x_hat = session.run(None, {"input": x[np.newaxis]})[0][0]  # (W, input_dim)

    # 3. Reconstruction error per time step, recency-weighted
    errors = np.mean((x - x_hat) ** 2, axis=-1)  # (W,)
    weights = np.exp(np.linspace(-1, 0, len(errors)))
    score = float(np.dot(errors, weights) / weights.sum())

    # 4. Normalise to [0, 1] anomaly probability
    z = (score - threshold_params["mu"]) / threshold_params["sigma"]
    anomaly_score = float(scipy.stats.norm.cdf(z))

    # 5. Per-dimension breakdown for RCA
    dim_errors = np.mean((x - x_hat) ** 2, axis=0)  # (input_dim,) → RCA signal

    return {
        "anomaly_score": anomaly_score,
        "alert": anomaly_score > threshold_params["alert_percentile"],
        "reconstruction_error": score,
        "dim_errors": dim_errors.tolist(),  # per-metric breakdown
    }
```

**ONNX Runtime rationale:** Inference uses ONNX Runtime (CPU provider). PyTorch (~2 GB) is a training-only dependency; ONNX Runtime is ~20 MB. The `backend/analyse/` production container does not require PyTorch installed at runtime — only during the training job, which runs as a subprocess.

**Recency weighting:** Anomalies at the end of the 128-step window (most recent) are weighted more heavily than older steps. Reduces detection latency.

---

## 5. Learning Phase Lifecycle

### 5.1 State Machine

Per collector × metric group, persisted in the PostgreSQL `ml_model_state` table:

```
ACCUMULATING → TRAINING → ACTIVE → RETRAINING
     ↑                                   ↓
     └───────────── drift detected ───────┘
```

| State | Condition | Tier 1 alerts | Tier 2 alerts |
|---|---|---|---|
| `ACCUMULATING` | `clean_windows / total_windows` below `learning_days` target | ✅ Active | ❌ Suppressed |
| `TRAINING` | Async training subprocess running | ✅ Active | ❌ Suppressed |
| `ACTIVE` | Model trained, threshold derived, ONNX session loaded | ✅ Active | ✅ Active |
| `RETRAINING` | ADWIN drift confirmed; new training subprocess running | ✅ Active | ⚠️ Score from old model (flagged stale in PostgreSQL) |

State transitions are written to `ml_model_state` by `backend/analyse/`. The `backend/api/` (Go/Gin) service reads this table and exposes it at `GET /api/v1/ml/state` for the SvelteKit frontend. State changes are also published via **PostgreSQL LISTEN/NOTIFY** on channel `ml_state_channel` — the same mechanism used for anomaly push to WebSocket clients (per ARCHITECTURE-V2.md section 5).

### 5.2 Contamination-Safe Data Collection

During `ACCUMULATING`, the `backend/analyse/` ML module queries VictoriaMetrics for the last `learning_days` of data and **masks out** windows where:
- PostgreSQL `anomalies` table has a Tier 1 event overlapping the window
- VictoriaMetrics returns `NaN` or has a gap > 2× poll interval (collector offline)
- Operator declared a maintenance window via `POST /api/v1/maintenance` (stored in PostgreSQL `maintenance_windows` table)

If clean data falls below 80% of the learning window, accumulation is extended. Implements the contamination mitigation from Khoury et al. (2024): LSTM autoencoders degrade significantly above 5% contamination; the mask targets <5%.

### 5.3 Training Job

Training runs as a **Python subprocess** spawned by `backend/analyse/`, not blocking the main analysis loop. Triggered when:
- `ACCUMULATING` → `clean_windows` ≥ `learning_days` × (samples/day)
- `RETRAINING` → ADWIN drift confirmed on ≥ 2 metrics in the same group

Training artefacts written to the `backend/analyse/` container volume:
```
ml/models/<collector_id>/<metric_group>/<version>/
  ├── model.onnx          # ONNX export — used by production inference loop
  ├── model.pt            # PyTorch checkpoint — used for fine-tuning only
  ├── preprocessing.json  # Scaler params + feature config
  ├── threshold.json      # μ, σ, percentile table of validation reconstruction errors
  └── meta.json           # Training timestamp, dataset stats, epoch count, val_loss
```

On completion, the subprocess updates `ml_model_state` in PostgreSQL and writes `NOTIFY ml_state_channel` — the API service picks this up and pushes the state change to all open WebSocket sessions in the SvelteKit frontend.

### 5.4 Model Versioning

Each training run produces a new version directory `v001`, `v002`, etc. The active version is recorded in `ml_model_state.active_version`. Last 5 versions are retained by default (configurable); older versions are deleted by a cleanup job in `backend/analyse/`.

Rollback: operator calls `POST /api/v1/ml/rollback` → API service writes new `active_version` to PostgreSQL → `backend/analyse/` picks up the change on its next cycle and loads the previous ONNX session.

---

## 6. Concept Drift Detection & Model Retraining

### 6.1 ADWIN Integration

ADWIN runs **per metric stream** inside `backend/analyse/`, monitoring the **raw reconstruction error** stream (before anomaly score sigmoid). Drift manifests as a sustained shift in reconstruction error before it becomes visible as anomaly alerts.

```python
# backend/analyse/ml/drift_detector.py

from river.drift import ADWIN

class DriftMonitor:
    def __init__(self, delta: float = 0.002):
        # delta=0.002: Bifet & Gavaldà (2007) recommended default;
        # validated as best accuracy/energy tradeoff in ICT4S 2024 across 420 combinations.
        self.detectors: dict[str, ADWIN] = {}

    def update(self, metric_key: str, reconstruction_error: float) -> bool:
        if metric_key not in self.detectors:
            self.detectors[metric_key] = ADWIN(delta=self.delta)
        self.detectors[metric_key].update(reconstruction_error)
        if self.detectors[metric_key].drift_detected:
            # Write to PostgreSQL ml_drift_events
            return True
        return False
```

`river` is a pure-Python streaming ML library; it has no C++ build requirements and runs on ARM (Raspberry Pi, Pi 4). ADWIN’s time complexity is O(log n) per update.

### 6.2 Drift Response Policy

| Drift event | Response | Rationale |
|---|---|---|
| Single metric ADWIN fires | Write to `ml_drift_events`; no retrain | Single-metric fires are common noise |
| ≥ 2 metrics in same group drift within 10 min | Trigger RETRAINING on that group | Correlated shift = structural change |
| All metric groups drift simultaneously | Write topology-event to PostgreSQL `events`; notify operator via alert | Likely major network reconfiguration — operator should declare maintenance window |
| OT Modbus register group drifts | Alert operator; **do not auto-retrain** | IEC 62443 requires human approval for OT baseline changes |

### 6.3 Fine-Tuning vs. Full Retrain

**Fine-tuning** (warm start from `.pt` checkpoint, lr=1e-4, 20 epochs) when:
- < 30% of group metrics drifted
- ADWIN window was long when it fired (gradual drift)

**Full retrain from scratch** when:
- ≥ 30% of group metrics drifted
- ADWIN window was short when it fired (abrupt drift)
- Operator explicitly requests via `POST /api/v1/ml/retrain`

---

## 7. Anomaly Score Integration with the v2 Pipeline

### 7.1 Score Fusion (Tier 1 + Tier 2)

Both tiers run inside `backend/analyse/`. Fused result is written to PostgreSQL `anomalies` table with a `detector` column that distinguishes the source:

```python
# backend/analyse/ml/fusion.py

def fused_alert(
    tier1_alert: bool,
    tier2_score: float,
    tier2_threshold: float
) -> dict:
    tier2_alert = tier2_score > tier2_threshold

    if tier1_alert and tier2_alert:
        confidence, verdict = 0.95, "HIGH_CONFIDENCE_ANOMALY"
    elif tier2_alert and not tier1_alert:
        confidence, verdict = tier2_score, "ML_STRUCTURAL_ANOMALY"
    elif tier1_alert and not tier2_alert:
        confidence, verdict = 0.65, "THRESHOLD_BREACH"
    else:
        confidence, verdict = tier2_score, "NORMAL"

    return {
        "alert": confidence > 0.6,
        "confidence": confidence,
        "verdict": verdict,
        "detector": "tier1+tier2" if (tier1_alert and tier2_alert)
                    else "tier2" if tier2_alert
                    else "tier1"
    }
```

The `confidence` field maps to the alert routing thresholds already defined in the v2 architecture:
- confidence > 0.8 → auto-alert via all configured channels (written to PostgreSQL `alerts` table → `backend/api/` dispatches webhook/SMTP)
- confidence 0.6–0.8 → anomaly visible in SvelteKit dashboard only
- confidence < 0.6 → raw symptom, no notification

This confidence-gating logic lives entirely in `backend/analyse/`. The `backend/api/` (Go/Gin) service reads the `anomalies` and `alerts` tables and dispatches notifications — it does not implement scoring logic.

### 7.2 RCA Enhancement

The LSTM-AE reconstruction error is **per-dimension** (per metric within the group). The `dim_errors` array from inference is written to the PostgreSQL `anomalies.payload_json` column and surfaced in the RCA panel by the SvelteKit frontend via `GET /api/v1/rca`:

```json
{
  "anomaly_id": "...",
  "verdict": "ML_STRUCTURAL_ANOMALY",
  "confidence": 0.87,
  "detector": "tier2",
  "metric_group": "network_latency",
  "primary_metric": "rtt_p95_target_plc_main",
  "reconstruction_errors": {
    "rtt_p50": 0.003,
    "rtt_p95": 0.041,
    "rtt_p99": 0.018,
    "loss_pct": 0.002
  },
  "model_version": "v003",
  "ml_state": "ACTIVE"
}
```

The dimension with the highest reconstruction error is the **primary contributing metric**, enhancing the existing causal DAG RCA engine (Phase 4) with a per-metric signal that identifies *which* stream caused the anomaly.

### 7.3 Anomaly Score as VictoriaMetrics Metric

The continuous anomaly score (not just the binary alert) is written back to VictoriaMetrics by `backend/analyse/` via Prometheus remote-write:

```
analyselaptop_ml_anomaly_score{collector_id="homelab-pi4", metric_group="network_latency"} 0.87
analyselaptop_ml_model_state{collector_id="homelab-pi4", metric_group="network_latency", state="ACTIVE"} 1
```

This allows the SvelteKit frontend to plot anomaly score time-series directly from VictoriaMetrics (same as any other metric), using the existing `GET /api/v1/collectors/:id/metrics` endpoint — no new API endpoint needed for charts.

---

## 8. Implementation Plan

### 8.1 New Files in `backend/analyse/`

```
backend/analyse/
├── ml/
│   ├── __init__.py
│   ├── feature_engineering.py    # Detrending, normalisation, windowing, cyclical time features
│   ├── lstm_ae.py                 # LSTM Autoencoder model (PyTorch — training only)
│   ├── training_job.py            # Training subprocess entrypoint; reads VM, writes ONNX
│   ├── inference.py               # ONNX Runtime inference, anomaly scoring
│   ├── drift_detector.py          # ADWIN per-metric drift monitoring (river library)
│   ├── model_registry.py          # Version management, active symlink, cleanup
│   ├── contamination_filter.py    # Query PG anomalies table; build clean-window mask
│   └── fusion.py                  # Tier 1 + Tier 2 score fusion
│
├── ml_state.py                    # State machine driver; reads/writes ml_model_state via psycopg3
├── ml_config.py                   # Config schema: learning_days, k_sigma, adwin_delta, ot_manual_only
└── main.py                        # Existing analysis loop — extend to call ml_state.tick() each cycle
```

### 8.2 New `backend/api/` Endpoints (Go/Gin)

```
GET  /api/v1/ml/state                    — all collector × group states from ml_model_state table
GET  /api/v1/ml/state/:collector_id      — states for one collector
GET  /api/v1/ml/drift-events             — recent ADWIN drift events (paginated)
POST /api/v1/ml/retrain                  — trigger full retrain { collector_id, metric_group }
POST /api/v1/ml/rollback                 — roll back to previous model version
PATCH /api/v1/ml/config/:collector_id    — update learning_days, k_sigma, ot_manual_only
GET  /api/v1/ml/model/:id/meta           — training stats + validation loss curve for a version
```

All endpoints read from PostgreSQL via pgx. The `retrain` and `rollback` endpoints write a command row to a `ml_commands` table; `backend/analyse/` polls this table each cycle and acts on pending commands. This avoids any synchronous RPC from the API service into the analysis service (consistent with ARCHITECTURE-V2.md Rule 3: *API reads storage only*).

### 8.3 SvelteKit ML Dashboard View

New route: `/ml` in the SvelteKit `frontend/`.

**Fleet ML status table** (polling `GET /api/v1/ml/state` + WebSocket live updates via `ml_state_channel` NOTIFY):

| Collector | Metric Group | ML State | Data Accumulated | Model Version | Last Retrain | Drift Events (7d) | Actions |
|---|---|---|---|---|---|---|---|
| homelab-pi4 | network_latency | 🟢 ACTIVE | 14d | v003 | 3 days ago | 1 | [Retrain] [Rollback] |
| homelab-pi4 | os_health | 🟡 ACCUMULATING | 4d / 7d | — | — | — | [Skip to train] |
| remote-pi3 | ot_modbus | 🔵 ACTIVE (OT-locked) | 28d | v001 | 28 days ago | 0 | [Retrain — manual only] |

**Controls per row:**
- **[Retrain]:** calls `POST /api/v1/ml/retrain`
- **[Rollback]:** calls `POST /api/v1/ml/rollback`
- **[Skip to train]:** patches `learning_days` override with inline warning

**Accumulation progress bar:** For `ACCUMULATING` state, show `clean_windows / total_target_windows` with contamination mask stats: “3,240 / 20,160 windows masked (16%) — due to 4 Tier 1 events.”

**Anomaly score chart:** For `ACTIVE` models, query VictoriaMetrics via `GET /api/v1/collectors/:id/metrics?metric=analyselaptop_ml_anomaly_score` and render a Chart.js time-series with the alert threshold overlaid (last 24h by default).

**Model detail modal:** Click a model version row → `GET /api/v1/ml/model/:id/meta` → render:
- Training dataset stats (n samples, contamination %, feature means/stddevs)
- Validation loss curve (train vs. val by epoch)
- Validation reconstruction error histogram with threshold line
- ADWIN drift event timeline for this collector × group

**Global ML config** (per collector, editable):
- Learning days slider: 7 / 14 / 28
- kσ threshold: 2.0 / 3.0 / 4.0
- ADWIN delta: text input, default 0.002
- OT retrain mode: toggle manual-only vs. auto (default: manual-only for Modbus/SNMP groups)

---

## 9. New Python Dependencies (`backend/analyse/requirements.txt`)

```
# Already present (NumPy, scikit-learn, networkx, psycopg3, httpx for VM queries)

# ML additions
torch==2.3.*          # Training only (not imported at inference time)
onnx==1.16.*          # Model export
onnxruntime==1.18.*   # Inference — CPU provider, no CUDA, ~20 MB
river==0.21.*         # ADWIN drift detector — pure Python, O(log n), ARM-compatible
scipy==1.13.*         # CDF for anomaly score normalisation
```

**Container split:** The `backend/analyse/` Docker image has two variants:
- `analyse-runtime`: does NOT install `torch` (default production image, ~1.2 GB smaller)
- `analyse-train`: installs `torch` (used only for the training subprocess; spawned on-demand via `docker exec` or a sidecar container with shared volume)

This keeps the always-running analysis container lean while still supporting on-node training without a separate training server.

---

## 10. Data Contamination & Robustness

The most critical failure mode for unsupervised anomaly detection is **contaminated training data** — if a slow attack occurs during the learning phase, the model learns the attack as normal.

Khoury et al. (2024) evaluated contamination rates from 1% to 20% across DL models: LSTM autoencoders degrade significantly above 5% contamination; below 5%, degradation is graceful.

**Mitigations:**

1. **PostgreSQL anomaly mask** (Section 5.2): Tier 1 CUSUM/EWMA events from the `anomalies` table mask training windows. Expected to keep contamination below 5% even during a slow, ongoing attack.

2. **Welford outlier removal:** Any VictoriaMetrics sample > 4σ from the running mean (computed by the existing CUSUM path) is excluded from the training buffer.

3. **Validation loss sanity check:** If `val_loss / train_loss > 1.5` (overfit) or `val_loss < 0.5 × train_loss` (contamination) → training rejected; learning phase extended by 3 days; event written to PostgreSQL.

4. **Operator review gate (optional):** Config flag `require_operator_approval_before_activation` (default: `false`; recommended `true` for OT environments) → model enters `TRAINING_COMPLETE` state, visible in SvelteKit `/ml` view; operator calls `POST /api/v1/ml/activate` to promote it to `ACTIVE`.

---

## 11. Academic References

| Reference | What it grounds |
|---|---|
| Maleki et al. (2021). Unsupervised anomaly detection with LSTM autoencoders using statistical data-filtering. *Applied Soft Computing* 112:107763. | LSTM-AE architecture choice; sliding window; contamination filtering |
| Khoury et al. (2024). Deep Learning for Network Anomaly Detection under Data Contamination. arXiv:2407.08838. | Contamination problem; 5% degradation threshold; mask strategy |
| Bifet & Gavaldà (2007). Learning from Time-Changing Data with Adaptive Windowing. *SIAM ICDM*. | ADWIN algorithm; delta=0.002 default |
| Mavromatis et al. (2024). FLAME: Adaptive and Reactive Concept Drift Mitigation. arXiv:2410.01386. | ADWIN vs. KSWIN vs. PHT comparison; stabilisation criterion |
| IEEE ICT4S (2024). How to Sustainably Monitor ML-Enabled Systems? | ADWIN as best balanced drift detector across 420 combinations |
| Kingma & Welling (2019). An Introduction to Variational Autoencoders. *FnTML* 12(4). | VAE probabilistic threshold alternative |
| Zabala et al. (2023). MDP-based network monitoring agent. *Mathematics* 11(3):610. | Integration: MDP scheduler can consume ML anomaly score as observation |
| Elsayed et al. (2025). CNN-BiLSTM-AE unsupervised IDS on UNSW-NB15. | 98.1% accuracy, purely unsupervised training validation |
| IEC 62443-3-3 (2013). System security requirements and security levels. | OT manual retrain approval requirement |
| Choi et al. (2021). LSTM-Based Autoencoder Survey. *Electronics* 10(13):1598. | hidden_dim=64 sweet spot for time-series of this window length |
