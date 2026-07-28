# Root Cause Analysis: Causal Inference vs Correlation
## Academic Research for `monitor/rca/`

> **Status:** Research document — feeds into `monitor/rca/graph.py` and `monitor/rca/engine.py`  
> **Priority:** High — the current naive Bayes DAG assumes conditional independence between symptoms, which is a known weakness. This document provides the theoretical grounding and practical fixes.

---

## 1. The Core Problem: Correlation Is Not Causation

The current RCA engine uses a **Causal Bayesian Network (CBN)** with naive Bayes inference:

```
P(cause | s1, s2, ...) ∝ P(cause) × ∏ P(si | cause)
```

This works when symptoms are **conditionally independent given the cause** — i.e., knowing the cause explains away any correlation between symptoms. In practice, network symptoms are often correlated for *structural* reasons unrelated to the cause:

- **RTT spike** and **loss spike** are correlated because both are caused by congestion *and* they affect each other (loss forces retransmits, which increases apparent RTT)
- **Multiple collectors reporting the same anomaly** could be because they share a WAN uplink (structural) or because there's a widespread attack (causal)
- **SNMP uptime regression** and **ICMP loss** co-occur during a reboot, but the loss *causes* SNMP unavailability, not the other way around — direction matters

**Key reference:** Li, M. et al. "Causal Inference-Based Root Cause Analysis for Online Service Systems with Intervention Recognition." CIRCA, arXiv:2206.05871, 2022. Cited 186+.  
https://arxiv.org/abs/2206.05871

**Key reference:** Abeille, S. et al. "A Comparative Study of Causality Detection Methods in Root Cause Diagnosis." MDPI Sensors 24(15):4908, 2024.  
https://www.mdpi.com/1424-8220/24/15/4908

---

## 2. The Three Levels of Causal Reasoning (Pearl's Ladder)

Judea Pearl's causal hierarchy defines three levels of reasoning (Pearl 2009; Honavar, Penn State 2023):

| Level | Operation | Question | Network Example |
|---|---|---|---|
| **L1: Association** | P(y ∣ x) | "What is?" | RTT and loss are both high — what is probable? |
| **L2: Intervention** | P(y ∣ do(x)) | "What if I do X?" | If I fix the cable, will loss drop? |
| **L3: Counterfactual** | P(y_x ∣ x', y') | "What would have happened?" | Would the outage have occurred without the firmware update? |

The current naive Bayes engine operates at **L1 only** — it observes correlations. CIRCA (Li et al. 2022) operates at **L2** by modelling the *do-operator*: it asks whether intervening on a node (fixing the cause) would remove the symptom.

**Practical implication for this system:** For a home/lab monitoring system with a pre-defined DAG (not learned from data), the key improvement is ensuring the DAG edges represent *interventional* relationships, not merely correlational ones. The naive Bayes multiplication is then approximately correct.

---

## 3. The CIRCA Approach — Intervention Recognition

CIRCA's core insight: a monitoring variable `v` is a root cause indicator if its conditional distribution *changes* relative to its parents in the CBN when an anomaly occurs. Formally:

```
v is a root cause ⇔ P_anomaly(v | parents(v)) ≠ P_normal(v | parents(v))
```

Variables whose conditional distribution does **not** change (i.e., they are affected downstream but not perturbed at their source) are symptoms, not causes.

**Implementation for this system:**

For each monitored node, maintain a **rolling conditional distribution** of each symptom given its parents in the DAG. During an anomaly event, check which nodes show distribution shift:

```python
# monitor/rca/circa.py
from scipy.stats import ks_2samp
import numpy as np
from collections import deque

class CIRCADetector:
    """
    Lightweight CIRCA implementation for network RCA.
    Identifies root cause nodes by detecting distribution shift
    in their residuals conditioned on parent node values.
    Reference: Li et al. arXiv:2206.05871, 2022.
    """
    def __init__(self, window_normal: int = 1440, window_anomaly: int = 10):
        # window_normal: number of intervals to use as baseline (24h at 60s)
        # window_anomaly: number of anomalous intervals to compare
        self.window_normal = window_normal
        self.window_anomaly = window_anomaly
        # Per-node residual history: deque of recent residuals
        self.history: dict[str, deque] = {}

    def record(self, node: str, residual: float):
        """Record a residual observation for a node."""
        if node not in self.history:
            self.history[node] = deque(maxlen=self.window_normal)
        self.history[node].append(residual)

    def score_root_cause(self, node: str, anomaly_residuals: list[float]) -> float:
        """
        Returns KS test p-value: low p = distribution shifted = likely root cause.
        Compares recent anomaly window vs historical normal window.
        """
        if node not in self.history or len(self.history[node]) < 60:
            return 1.0  # insufficient history
        normal = list(self.history[node])
        ks_stat, p_value = ks_2samp(normal, anomaly_residuals)
        return p_value  # low = significant shift = root cause candidate

    def rank_root_causes(self, active_nodes: list[str],
                         anomaly_windows: dict[str, list[float]]) -> list[tuple]:
        """
        Rank all active anomaly nodes by CIRCA score (ascending p-value = most likely root cause first).
        active_nodes: nodes currently in anomaly state
        anomaly_windows: {node: [recent residuals during anomaly]}
        """
        scores = []
        for node in active_nodes:
            p = self.score_root_cause(node, anomaly_windows.get(node, []))
            scores.append((node, p))
        return sorted(scores, key=lambda x: x[1])  # lowest p-value = most likely root cause
```

**Integration with existing RCA engine:** Run CIRCA scoring first to identify which metric nodes are root cause *candidates*, then use the Bayesian DAG to translate from metric nodes to human-readable cause labels.

---

## 4. Confounders in Network RCA

A **confounder** is a variable that causally affects both the observed symptom and the apparent cause, creating a spurious correlation. In network monitoring:

### Known Confounders

| Apparent Relationship | Confounder | Effect |
|---|---|---|
| High RTT → high loss | Congestion (common cause of both) | Both symptoms are effects, not cause-effect pair |
| SNMP timeout → device down | CPU overload on the collector itself | Collector is slow, not the target |
| DNS failures → DNS server outage | Clock skew (DNSSEC validation rejects signatures) | NTP is the true root cause |
| Multiple collectors report loss → network attack | Shared upstream link failure | Infrastructure, not attack |
| DNS latency → app slowdown | Target DNS server under load from unrelated cause | Not the monitored network |

### Handling Confounders in the DAG

The fix is to **model confounders as explicit intermediate nodes** in the DAG, rather than having a direct edge between the two confounded symptoms:

```python
# WRONG: Direct edge between correlated symptoms
G.add_edge("WAN_CONGESTION", "SYM_RTT_HIGH")
G.add_edge("WAN_CONGESTION", "SYM_LOSS_HIGH")
# This is correct — both are effects of the same cause. OK.

# WRONG pattern to avoid: symptom → symptom edges
# G.add_edge("SYM_RTT_HIGH", "SYM_LOSS_HIGH")  # DON'T DO THIS
# This implies RTT causes loss, conflating cause and effect.

# CORRECT: model the confounder explicitly
G.add_node("CONGESTION", node_type="intermediate")  # intermediate state
G.add_edge("WAN_CONGESTION", "CONGESTION")          # cause → state
G.add_edge("CONGESTION", "SYM_RTT_HIGH")            # state → symptom A
G.add_edge("CONGESTION", "SYM_LOSS_HIGH")           # state → symptom B
# Now RTT and LOSS are conditionally independent given CONGESTION → naive Bayes is valid
```

### The Backdoor Criterion (Pearl 2009)

For the DAG to support valid causal inference, it must satisfy the **backdoor criterion**: all backdoor paths (paths that enter the cause node through an arrow into it) must be blocked by the observed variables.

For the current DAG with pre-defined cause nodes and no latent confounders, this is satisfied by construction — cause nodes are root nodes (no incoming edges), so there are no backdoor paths. **This is the key reason why the pre-defined DAG approach is sound for this system**: we are not trying to learn causal structure from data, we are encoding known engineering relationships.

---

## 5. Updated DAG: Fixing the Conditional Independence Violations

The following changes are needed in `monitor/rca/graph.py` to fix the three main conditional independence violations identified above:

### 5a. Split CONGESTION from WAN_CONGESTION

```python
# Add CONGESTION as intermediate node
G.add_node("CONGESTION", node_type="intermediate", label="Network congestion state")

# WAN_CONGESTION causes CONGESTION
G.add_edge("WAN_CONGESTION", "CONGESTION", {"p": 0.90})
# BUFFERBLOAT also causes CONGESTION (local)
G.add_edge("BUFFERBLOAT", "CONGESTION", {"p": 0.85})

# CONGESTION causes both RTT and LOSS (now conditionally independent given CONGESTION)
G.add_edge("CONGESTION", "SYM_RTT_HIGH",  {"p": 0.85})
G.add_edge("CONGESTION", "SYM_LOSS_HIGH", {"p": 0.70})

# Direct effect: WAN_CONGESTION without local congestion can still cause RTT
G.add_edge("WAN_CONGESTION", "SYM_WAN_UNREACHABLE", {"p": 0.40})
```

### 5b. Add NTP_FAILURE as a cause node

```python
# NTP failure can cause DNSSEC validation failures
G.add_node("NTP_FAILURE", node_type="cause",
           label="NTP clock skew — DNSSEC validation rejected",
           prior=0.03,
           remediation="Check NTP sync: 'timedatectl status'. Restart systemd-timesyncd.")
G.add_edge("NTP_FAILURE", "SYM_DNS_LATENCY", {"p": 0.20})  # DNSSEC validation fails under clock skew
```

### 5c. Add COLLECTOR_OVERLOAD as a cause node

```python
# Collector CPU overload causes spurious timeouts
G.add_node("COLLECTOR_OVERLOAD", node_type="cause",
           label="Collector node CPU/memory overload",
           prior=0.04,
           remediation="Check collector CPU ratio. Kill competing processes. Reduce probe frequency.")
G.add_edge("COLLECTOR_OVERLOAD", "SYM_RTT_HIGH",    {"p": 0.60})  # probe scheduling delay
G.add_edge("COLLECTOR_OVERLOAD", "SYM_LOSS_HIGH",   {"p": 0.30})  # missed probe windows
G.add_edge("COLLECTOR_OVERLOAD", "SYM_DNS_LATENCY", {"p": 0.40})  # local resolver contention

# Discriminator: COLLECTOR_OVERLOAD affects ALL targets equally
# WAN_CONGESTION also affects all targets but is corroborated by external ping from another collector
# This cross-collector check is done in the decision tree, not the DAG
```

---

## 6. Observational vs Interventional Data in this System

All data collected by the monitoring system is **observational** — we passively measure; we do not inject faults to test causal structure. This means:

1. **We cannot learn causal structure from data** — correlation mining on observational network metrics will find spurious causal links. The DAG must be constructed from **engineering knowledge**, not data.

2. **We cannot estimate intervention effects** (P(y | do(x))) without additional assumptions. The pre-defined DAG encodes these assumptions explicitly via the P(symptom | cause) edge probabilities.

3. **The dropped-connection decision tree** (Phase 4c of ROADMAP) is a form of **active causal probing** — by sequentially testing (pinging GW, then WAN, then target from another collector), we are approximating do-calculus experiments in real time. This is the right approach and aligns with the CIRCA paper's "intervention recognition" framework.

**Practical recommendation:** Keep the pre-defined DAG. Do not attempt to learn DAG structure from monitoring data. The DAG encoding engineering knowledge is more reliable and interpretable than a data-learned DAG on observational network metrics, which will be dominated by spurious correlations (Abeille et al. 2024).

---

## 7. Multi-Collector Evidence Fusion — Dempster-Shafer

When multiple collectors report anomalies simultaneously, combining their evidence correctly matters. Naive Bayes assumes independent observations — but two collectors on the same LAN segment are **not** independent (they share the upstream link).

**Dempster-Shafer Theory of Evidence** provides a framework for combining non-independent belief masses:

```python
# monitor/rca/fusion.py

def dempster_combine(belief_a: dict, belief_b: dict) -> dict:
    """
    Dempster-Shafer combination of two belief functions.
    belief_a, belief_b: {cause_id: mass} where masses sum to <= 1.0
    Remainder mass (1 - sum) assigned to the 'unknown' hypothesis.
    Reference: Shafer (1976); Sentz & Ferson (2002).
    """
    combined = {}
    conflict = 0.0

    for h1, m1 in belief_a.items():
        for h2, m2 in belief_b.items():
            if h1 == h2:
                combined[h1] = combined.get(h1, 0.0) + m1 * m2
            else:
                conflict += m1 * m2  # conflicting evidence

    # Normalise by (1 - K) where K = conflict mass
    if conflict >= 1.0:
        return {"UNKNOWN": 1.0}  # total conflict — collectors disagree completely
    norm = 1.0 - conflict
    return {h: m / norm for h, m in combined.items()}


def fuse_collector_beliefs(collector_results: list[dict]) -> dict:
    """
    Fuse RCA posteriors from multiple collectors using Dempster-Shafer.
    collector_results: list of {cause_id: posterior_probability} dicts
    Returns: fused belief dict
    """
    if not collector_results:
        return {}
    fused = collector_results[0]
    for result in collector_results[1:]:
        fused = dempster_combine(fused, result)
    return fused
```

**When to use DS fusion vs naive averaging:**
- Use **Dempster-Shafer** when collectors are on different network segments (independent observations of a shared upstream failure)
- Use **simple averaging** of posteriors when collectors are on the same segment (they share the same evidence base)
- Use **maximum** (most alarmed collector wins) for physical-layer faults that are local to one segment

---

## 8. Implementation Checklist

| Item | File | Status |
|---|---|---|
| CIRCA distribution-shift scoring (KS test) | `monitor/rca/circa.py` | **New file — create** |
| Intermediate CONGESTION node in DAG | `monitor/rca/graph.py` | **Missing — add** |
| NTP_FAILURE cause node | `monitor/rca/graph.py` | **Missing — add** |
| COLLECTOR_OVERLOAD cause node | `monitor/rca/graph.py` | **Missing — add** |
| Dempster-Shafer multi-collector fusion | `monitor/rca/fusion.py` | **New file — create** |
| Symptom→symptom edges removed | `monitor/rca/graph.py` | Check — verify none exist |
| Cross-collector discriminator in decision tree | `monitor/rca/engine.py` | Partially spec’d in ROADMAP |

---

## References

1. Li, M. et al. "Causal Inference-Based Root Cause Analysis for Online Service Systems with Intervention Recognition (CIRCA)." arXiv:2206.05871, 2022. https://arxiv.org/abs/2206.05871
2. Abeille, S. et al. "A Comparative Study of Causality Detection Methods in Root Cause Diagnosis." MDPI Sensors 24(15):4908, 2024. https://www.mdpi.com/1424-8220/24/15/4908
3. Pearl, J. "Causality: Models, Reasoning and Inference." 2nd ed. Cambridge University Press, 2009.
4. Tikumporn, W. et al. "Automated Root Cause Analysis of Network Failures in IP Networks." IEEE Access, 2025. https://doi.org/10.1109/ACCESS.2025.11053841
5. Shafer, G. "A Mathematical Theory of Evidence." Princeton University Press, 1976.
6. Honavar, V. "Principles of Causal Inference — Do-Calculus and Causal Identifiability." Penn State University, 2023. https://faculty.ist.psu.edu/vhonavar/Courses/causality/studyguide.html
7. Sentz, K. & Ferson, S. "Combination of Evidence in Dempster-Shafer Theory." Sandia Report SAND2002-0835, 2002.
