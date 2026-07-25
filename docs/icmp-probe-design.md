# ICMP RTT Probe Design: Statistics & Implementation
## Academic Research for `collector/` ICMP Checks

> **Status:** Research document — feeds into `collector/checks/icmp.go`  
> **Priority:** High — ICMP RTT is the foundation of every health check in the system. Correct probe design determines whether RTT distributions are statistically meaningful.

---

## 1. Why Multi-Packet Probing Is Required

A **single ICMP ping** produces a single RTT sample. This is statistically meaningless for:
- Detecting **packet loss** (you need N probes to estimate loss rate with confidence)
- Computing **RTT percentiles** (p95/p99 requires at least ~20 samples for reasonable accuracy)
- Distinguishing **transient spikes** from sustained degradation

**OneProbe (Luo et al., USENIX 2009)** demonstrated that TCP data probes give richer metrics than ICMP, but ICMP remains the universal fallback (works to any IP, no port required, no TCP handshake overhead).

**Key reference:** Luo, X. et al. "Design and Implementation of TCP Data Probes for Reliable and Metric-Rich Network Path Monitoring (OneProbe)." USENIX 2009.  
https://www.usenix.org/legacyurl/design-and-implementation-tcp-data-probes-reliable-and-metric-rich-network-path-monitoring

---

## 2. Probe Count & Statistical Confidence

### How Many Probes per Cycle?

For loss rate estimation with 95% confidence interval ±5%:

```
n = z² × p(1-p) / e²

Where:
  z = 1.96 (95% confidence)
  p = 0.05 (5% loss rate — worst case that matters for home networks)
  e = 0.05 (desired ±5% margin)

n = (1.96)² × 0.05 × 0.95 / (0.05)² = 3.84 × 0.0475 / 0.0025 = 73 probes
```

For a home network where loss > 1% is already alarming, a tighter confidence interval is useful. **Practical recommendation: 20 probes per cycle minimum, 50 probes for critical targets.**

With 20 probes:
- Loss detection: can detect ≥5% loss with 95% confidence
- RTT p95: reasonable accuracy (actual p95 ± one sample)
- RTT p99: unreliable (needs ≥100 samples)

With 50 probes:
- Loss detection: can detect ≥2% loss with 95% confidence
- RTT p95: reliable
- RTT p99: reasonable accuracy

```go
// collector/checks/icmp.go — recommended defaults
const (
    ProbesDefault   = 20   // standard targets (gateways, DNS servers)
    ProbesCritical  = 50   // critical targets (WAN endpoint, primary GW)
    ProbesMinimum   = 5    // MDP STABLE state — heartbeat only
)
```

---

## 3. Inter-Probe Timing: Why Poisson Arrival Matters

### The Problem with Periodic Probes

Sending probes at fixed intervals (e.g. exactly every 20ms) can synchronise with periodic queue-draining events in routers, producing **artificially low RTT** estimates (the probe always arrives when the queue is empty). This is called the **phase-sampling problem**.

### The Solution: Poisson-Distributed Inter-Probe Intervals

Use **exponentially distributed inter-probe delays** (Poisson arrival process). This ensures probes arrive at uniformly random queue states, giving an unbiased sample of queue delay:

```go
// collector/checks/icmp.go
package checks

import (
    "math/rand"
    "time"
)

// PoissonDelay returns an exponentially distributed delay with mean = targetInterval.
// This implements a Poisson probe arrival process, avoiding phase-sampling bias.
// Reference: RFC 2330 (Framework for IP Performance Metrics) Section 11.1
func PoissonDelay(mean time.Duration) time.Duration {
    // Exponential distribution: -mean * ln(U) where U ~ Uniform(0,1)
    lambda := 1.0 / float64(mean)
    delay := -1.0 / lambda * math.Log(rand.Float64())
    return time.Duration(delay)
}

// ProbeTarget sends n ICMP echo requests to target with Poisson-distributed
// inter-probe intervals and returns the RTT distribution.
func ProbeTarget(target string, n int, meanInterval time.Duration) RTTResult {
    rtts := make([]float64, 0, n)
    lost := 0

    for i := 0; i < n; i++ {
        if i > 0 {
            // Poisson inter-probe interval (mean = meanInterval)
            time.Sleep(PoissonDelay(meanInterval))
        }
        rtt, err := sendICMPEcho(target)
        if err != nil {
            lost++
            continue
        }
        rtts = append(rtts, rtt.Seconds()*1000) // convert to ms
    }

    return computeRTTResult(rtts, n, lost)
}
```

**RFC 2330** (Framework for IP Performance Metrics) explicitly mandates Poisson probe arrivals for unbiased one-way delay measurement. Section 11.1 proves that periodic probing introduces systematic bias proportional to queue oscillation amplitude.

---

## 4. RTT Distribution Statistics

### Which Percentiles to Report and Why

| Statistic | What it measures | Implementation |
|---|---|---|
| **p50 (median)** | Typical user experience | `sort(rtts)[n//2]` |
| **p95** | Worst-case for 95% of users — SLO boundary | `sort(rtts)[int(0.95*n)]` |
| **p99** | Tail latency — worst 1% | `sort(rtts)[int(0.99*n)]` |
| **mean** | Affected by outliers — **do not use for anomaly detection** | `sum(rtts)/len(rtts)` |
| **stddev** | Jitter (variation) | `std(rtts)` |
| **loss %** | Packet loss rate | `(lost/n) * 100` |

**Why p95 is the primary anomaly detection metric (not mean):**  
Network RTT distributions are right-skewed — the mean is pulled up by rare large outliers (retransmits, buffer events). The mean of 20 samples with one 500ms spike is misleading. p95 is resistant to the top 5% of outliers while still capturing degradation. This is why all major cloud SLOs (AWS, GCP, Azure) use p99 for network latency.

```go
// collector/checks/icmp.go — RTT result computation
func computeRTTResult(rtts []float64, total int, lost int) RTTResult {
    if len(rtts) == 0 {
        return RTTResult{LossPct: 100.0}
    }
    sort.Float64s(rtts)
    n := len(rtts)
    p := func(pct float64) float64 {
        idx := int(math.Ceil(pct/100.0*float64(n))) - 1
        if idx < 0 { idx = 0 }
        if idx >= n { idx = n - 1 }
        return rtts[idx]
    }
    return RTTResult{
        P50:     p(50),
        P95:     p(95),
        P99:     p(99),
        Mean:    stat.Mean(rtts, nil),
        Stddev:  stat.StdDev(rtts, nil),
        LossPct: float64(lost) / float64(total) * 100.0,
        N:       total,
        Lost:    lost,
    }
}
```

---

## 5. RTT Distribution Model: What to Expect on a Healthy Network

On a healthy LAN/WAN path, RTT samples follow approximately a **log-normal distribution** (right-skewed, always positive, multiplicative noise sources):

```
RTT ~ LogNormal(μ, σ)

Typical values for a healthy home LAN (wired):
  p50:  0.3–1.5 ms
  p95:  0.8–3.0 ms
  p99:  1.5–5.0 ms
  loss: 0.0%

Typical values for a healthy WAN (ISP, <10ms baseline):
  p50:  5–15 ms
  p95:  8–25 ms
  p99: 12–40 ms
  loss: 0–0.1%

Anomalous conditions:
  Bufferbloat:   p95 >> 3×p50, p99 >> 10×p50, loss = 0
  Congestion:    p95 elevated + loss > 0.5%
  Physical fault: loss > 5%, p95 erratic
  QoS shaping:   p50 stable, p99 = exactly at shaping ceiling
```

**Implication for Holt-Winters:** Apply `log(rtt_p95)` transform before fitting Holt-Winters (as documented in `docs/anomaly-detection-theory.md`). This converts the log-normal distribution to approximately Gaussian, making CUSUM/EWMA parameter calibration valid.

---

## 6. Probe Scheduling: MDP Integration

The probe count per cycle should vary by MDP state (Phase 5 of ROADMAP):

```go
// Probe count by MDP target state
// Academic basis: Zabala et al. Mathematics 11(3):610, 2023
func probeCountForState(state MDPState, targetType TargetType) int {
    base := ProbesDefault
    if targetType == TargetTypeCritical {
        base = ProbesCritical
    }
    switch state {
    case MDPStateStable:
        return base / 4  // 5 probes — heartbeat only, conserve bandwidth
    case MDPStateSuspect:
        return base      // full probe count — need reliable distribution
    case MDPStateDegraded:
        return base      // full probe count sustained
    case MDPStateDown:
        return ProbesMinimum  // 3 probes — detect recovery, minimal overhead
    }
    return base
}
```

This means in STABLE state, a 20-probe default target uses only 5 probes per cycle — 4× bandwidth saving. In SUSPECT/DEGRADED, the full 20 probes are used to get a reliable RTT distribution for anomaly detection.

---

## 7. Loss Rate Confidence Interval

Always report the Wilson score confidence interval for loss rate, not just the point estimate:

```go
// Wilson score interval for binomial proportion (loss rate)
// More accurate than normal approximation for small n and extreme p
// Reference: Wilson (1927); Agresti & Coull (1998)
func wilsonCI(lost, total int, z float64) (lower, upper float64) {
    if total == 0 { return 0, 1 }
    p := float64(lost) / float64(total)
    n := float64(total)
    z2 := z * z
    center := (p + z2/(2*n)) / (1 + z2/n)
    margin := (z / (1 + z2/n)) * math.Sqrt(p*(1-p)/n + z2/(4*n*n))
    return math.Max(0, center-margin), math.Min(1, center+margin)
}

// Usage (z=1.96 for 95% CI):
// lower, upper := wilsonCI(lost, n, 1.96)
// Report: loss_pct = p*100, loss_ci_lower = lower*100, loss_ci_upper = upper*100
```

With n=20 probes and 1 lost (5% loss), the Wilson 95% CI is [0.9%, 23.6%] — very wide. This is honest: 20 probes cannot reliably distinguish 1% from 20% loss. The CI should be included in the JSON push envelope to prevent the monitor from over-reacting to statistically uncertain loss estimates.

---

## 8. ICMP Rate Limiting: Router Behaviour

Many routers and firewalls **rate-limit ICMP echo replies** (commonly to 100 pps or 1 pps for management plane ICMP). Sending 50 probes in rapid succession may trigger this, producing **artificial loss** that looks like network degradation.

**Mitigations:**

1. **Minimum inter-probe interval:** 5ms (200 pps max). Even Poisson-distributed probes should have a minimum floor.
2. **Detect rate limiting:** If loss is exactly N/50 (e.g. 40/50 = 80%), suspect rate limiting. Real packet loss is not this regular.
3. **ICMP TTL exceeded detection:** If RTT varies by exactly integer multiples of a base value, a hop is rate-limiting responses (each nth probe gets a reply, others get TTL exceeded from a closer hop).

```go
// Minimum floor on Poisson inter-probe interval
const MinInterProbeInterval = 5 * time.Millisecond

func PoissonDelayBounded(mean time.Duration) time.Duration {
    d := PoissonDelay(mean)
    if d < MinInterProbeInterval {
        return MinInterProbeInterval
    }
    return d
}
```

---

## 9. Implementation Checklist

| Item | File | Status |
|---|---|---|
| Poisson inter-probe delays (exponential distribution) | `collector/checks/icmp.go` | **Missing — implement** |
| `ProbeTarget(n, meanInterval)` function | `collector/checks/icmp.go` | **Missing — implement** |
| p50/p95/p99/stddev/loss computation | `collector/checks/icmp.go` | Partially spec’d |
| Wilson score CI for loss rate | `collector/checks/icmp.go` | **Missing — add** |
| Probe count by MDP state | `collector/checks/icmp.go` | **Missing — add** |
| ICMP rate-limit detection heuristic | `collector/checks/icmp.go` | **Missing — add** |
| log(rtt_p95) transform before Holt-Winters | `monitor/transforms.py` | Specified in anomaly-detection-theory.md |
| RTT CI in JSON push envelope | `collector/push.go` | **Missing — add fields** |

---

## References

1. Luo, X. et al. "Design and Implementation of TCP Data Probes for Reliable and Metric-Rich Network Path Monitoring." USENIX 2009. https://www.usenix.org/legacyurl/design-and-implementation-tcp-data-probes-reliable-and-metric-rich-network-path-monitoring
2. Paxson, V. et al. "RFC 2330: Framework for IP Performance Metrics." IETF, 1998. https://www.rfc-editor.org/rfc/rfc2330
3. Zabala, L. et al. "Optimality of a Network Monitoring Agent." Mathematics 11(3):610, 2023. https://doi.org/10.3390/math11030610
4. Wilson, E.B. "Probable Inference, the Law of Succession, and Statistical Inference." JASA 22(158):209–212, 1927.
5. Agresti, A. & Coull, B.A. "Approximate Is Better than Exact for Interval Estimation of Binomial Proportions." The American Statistician 52(2):119–126, 1998.
6. Münz, G. "Traffic Anomaly Detection and Cause Identification." TU Munich NET-2010-06-1, 2010. https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2010-06-1.pdf
