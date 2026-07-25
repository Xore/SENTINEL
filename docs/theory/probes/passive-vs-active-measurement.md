# Passive vs Active Network Measurement
## Academic Research for `collector/` Measurement Strategy

> **Status:** Research document — informs the hybrid measurement architecture of `collector/checks/`  
> **Priority:** High — determines which RTT values are trustworthy, what coverage gaps exist, and how eBPF passive and ICMP active measurements complement each other.

---

## 1. Definitions (IETF RFC 7799bis)

The IETF IPPM working group defines three measurement paradigms (Fioccola et al., draft-fioccola-ippm-rfc7799bis): [web:190]

| Type | Mechanism | Traffic | Observer Position |
|---|---|---|---|
| **Active** | Inject probe packets | Synthetic (adds load) | End-host or dedicated probe |
| **Passive** | Observe existing traffic | Zero overhead | Any on-path device |
| **Hybrid** | Tag or timestamp subset of real traffic | Near-zero overhead | On-path with tagging capability |

This system uses all three:
- **Active:** ICMP echo probes (`collector/checks/icmp.go`)
- **Passive:** eBPF TCP RTT extraction via `tcp_close` kprobe or TC hook (`collector/ebpf/`)
- **Hybrid:** ePPing TCP timestamp matching (planned Phase 2)

---

## 2. Key Comparison: Active ICMP vs Passive eBPF RTT

**Key reference:** Sundberg, T. et al. "Efficient Continuous Latency Monitoring with eBPF (ePPing)." PAM 2023. Springer LNCS 13882.  
https://link.springer.com/chapter/10.1007/978-3-031-28486-1_9

| Dimension | Active ICMP | Passive eBPF (ePPing) |
|---|---|---|
| **What it measures** | Idle path latency (ICMP management plane) | Real application RTT (TCP data plane) |
| **Traffic added** | Yes — synthetic probes | None |
| **Coverage** | Any IP reachable (no TCP required) | Only TCP-speaking hosts with active flows |
| **QoS treatment** | ICMP may be deprioritised or rate-limited | TCP data packets get production QoS |
| **Accuracy** | Affected by router ICMP rate limiting | Accurate to actual application experience |
| **Connectivity detection** | Yes — works even with zero app traffic | No — silent hosts appear down |
| **WAN-side visibility** | Yes — can ping outside the LAN | Yes — if collector sees WAN-bound TCP |
| **Throughput** | Up to 200 pps (safe) | >1 Mpps on single core (ePPing evaluation) |
| **Implementation** | `net.ICMP`, raw sockets | eBPF TC/kprobe + ring buffer |

### The Critical Asymmetry

> **Active ICMP measures the network as it treats ICMP. Passive eBPF measures the network as it treats your actual application traffic. These can differ significantly.**

From Sundberg et al. 2023 (ePPing paper): "Active monitoring is unable to directly infer the latency application traffic experiences. The network probes may be treated differently from application traffic by the network, due to for example active queue management and load balancing."

**Practical example:** A router with fq_codel or CAKE AQM will rate-limit ICMP echoes and deprioritise them relative to TCP flows. An ICMP probe may show 2ms RTT while an active TCP stream experiences 180ms (bufferbloat). The passive eBPF measurement catches this; the ICMP probe misses it.

---

## 3. Coverage Matrix: When to Use Which

| Target Type | Use Active ICMP | Use Passive eBPF | Reason |
|---|---|---|---|
| Default gateway | **Yes** | **Yes** | Cross-validate; detect ICMP rate limiting |
| WireGuard peer | **Yes** (ICMP through tunnel) | **Yes** (if WG traffic seen) | Tunnel RTT = ICMP; eBPF sees post-decrypt |
| DNS server | **Yes** | Optional | DNS is UDP, eBPF sees TCP fallback only |
| Remote WAN target | **Yes** | No | Collector rarely on WAN path |
| LAN devices (IoT) | **Yes** | No | No meaningful TCP flows |
| Application servers | **Yes** + TCP probe | **Yes** (primary) | eBPF measures real app latency |
| Modbus/OT devices | **Yes** | No | No TCP RTT meaningful for polling devices |

**Decision rule:** For any TCP-capable target with regular app traffic, passive eBPF RTT is the **primary** measurement. Active ICMP is the **secondary** (connectivity check and fallback when no TCP flows exist).

---

## 4. ePPing: The Hybrid Passive Measurement

ePPing (evolved Passive Ping, Sundberg PAM 2023) uses **TCP timestamps** (RFC 1323) as identifiers to match outgoing packets with their ACKs, computing RTT from the kernel's TC hook:

```
Outgoing packet: timestamp TSval = T1 saved in eBPF hash map (key: flow_4tuple + T1)
Incoming ACK:    TSecr = T1 echoed back → RTT = now - T1
```

**Performance (Sundberg 2023 evaluation):**
- Handles >1 Mpps on a single core (>10 Gbps)
- CPU overhead: ~30% of PPing (libpcap-based passive tool)
- RTT accuracy: within 1–5 μs of ground truth
- Limitation: TCP timestamp update rate limits sample frequency (~1 sample per RTT per flow)

**Integration plan for this system:**

```go
// collector/ebpf/epping.go (Phase 2)
// ePPing produces per-flow RTT samples. Aggregate into per-target statistics.

type EPPingSample struct {
    FlowKey  FlowKey   // src_ip, dst_ip, src_port, dst_port, proto
    RTT_ns   uint64    // nanoseconds
    Timestamp uint64   // when measured
}

// Aggregate per-target (collapse all flows to the same dst_ip)
func (a *Aggregator) AddEPPingSample(s EPPingSample) {
    target := s.FlowKey.DstIP.String()
    a.mu.Lock()
    defer a.mu.Unlock()
    a.samples[target] = append(a.samples[target], float64(s.RTT_ns)/1e6) // ms
}

// Report p50/p95 for each target every collection cycle
func (a *Aggregator) Flush() map[string]RTTResult {
    a.mu.Lock()
    defer a.mu.Unlock()
    results := make(map[string]RTTResult)
    for target, rtts := range a.samples {
        if len(rtts) > 0 {
            results[target] = computeRTTResult(rtts, len(rtts), 0)
        }
    }
    a.samples = make(map[string][]float64) // reset
    return results
}
```

---

## 5. Anomaly Detection: Which Metric to Use as Primary

For the Holt-Winters + CUSUM pipeline (`monitor/`), the primary input metric per target should be selected in this priority order:

1. **Passive eBPF RTT p95** (ePPing) — if ≥10 samples in collection window: most accurate reflection of app experience
2. **Active ICMP RTT p95** — if eBPF unavailable or <10 samples: reliable fallback
3. **TCP probe RTT** (OneProbe-style) — for targets where ICMP is blocked
4. **Synthetic SNMP/API poll latency** — for devices with no ICMP or TCP RTT visibility

Store both passive and active RTT as separate Prometheus metrics. The **delta** between them is itself an anomaly signal:

```
# Prometheus label differentiation
collector_rtt_p95_ms{target="192.168.1.1", method="icmp"}    ← active
collector_rtt_p95_ms{target="192.168.1.1", method="epping"}  ← passive

# Derived anomaly signal:
rtt_method_delta = epping_p95 - icmp_p95
# Large positive delta: bufferbloat or AQM deprioritising ICMP
# Large negative delta: ICMP rate limiting inflating icmp_p95
```

---

## 6. Compact Data Structures for High-Rate Passive Telemetry

For networks with many flows (>10k concurrent), per-flow eBPF hash maps become impractical. The academic solution is **sketches** — probabilistic data structures that trade exactness for memory efficiency.

**Key reference:** Gember-Jacobson, A. et al. "Compact Data Structures for Network Telemetry." arXiv:2311.02636, 2025.  
https://arxiv.org/pdf/2311.02636.pdf

| Sketch | Use case | Error guarantee |
|---|---|---|
| **Count-Min Sketch** | Per-flow packet/byte counts | ε additive error with probability 1−δ |
| **HyperLogLog** | Distinct flow count (cardinality) | ~2% error, O(log log n) memory |
| **Histogram sketch** | RTT percentile approximation | q-digest or t-digest |
| **Bloom filter** | Fast "have we seen this flow?" | False positives, no false negatives |

For the collector's flow table at home/lab scale (<1k concurrent flows), **exact hash maps are fine**. Sketches become relevant if the system is deployed at edge/campus scale.

---

## 7. Implementation Checklist

| Item | File | Status |
|---|---|---|
| Dual-metric collection (ICMP + eBPF) per target | `collector/checks/` | Partially spec’d |
| ePPing aggregator (per-target RTT from flows) | `collector/ebpf/epping.go` | **New — Phase 2** |
| Prometheus labels: `method="icmp"` vs `method="epping"` | `collector/metrics.go` | **Missing — add** |
| RTT method delta as anomaly signal | `monitor/detector.py` | **Missing — add** |
| Coverage matrix decision logic (when to use which) | `collector/checks/scheduler.go` | **Missing — add** |

---

## References

1. Sundberg, T. et al. "Efficient Continuous Latency Monitoring with eBPF (ePPing)." PAM 2023 (Passive and Active Measurement). https://link.springer.com/chapter/10.1007/978-3-031-28486-1_9
2. Fioccola, G. et al. "Active, Passive, and Hybrid Metrics and Methods." IETF draft-fioccola-ippm-rfc7799bis. https://datatracker.ietf.org/doc/draft-fioccola-ippm-rfc7799bis/00/
3. Bertrone, M. et al. "COP2: Continuously Observing Protocol Performance." arXiv:1902.04280, 2019. https://arxiv.org/pdf/1902.04280.pdf
4. Gember-Jacobson, A. et al. "Compact Data Structures for Network Telemetry." arXiv:2311.02636, 2025. https://arxiv.org/pdf/2311.02636.pdf
5. Paxson, V. et al. "RFC 2330: Framework for IP Performance Metrics." IETF, 1998.
6. RedHat Research. "Lightweight Always-On Network Latency Monitoring with eBPF." RHRD22, 2022. https://research.redhat.com/wp-content/uploads/2022/09/RHRD22_Lightweight-always-on-network-latency-monitoring-with-eBPF_Simon-Sundberg.pdf
