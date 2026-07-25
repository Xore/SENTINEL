# Repository Roadmap
## analyseLaptop — Network Health & Anomaly Detection System

> **Updated:** 2026-07-25  
> **Scope:** Entire repository — `collector/`, `monitor/`, `dashboard/`, `config/`, `scripts/`, `tests/`  
> Phases are additive. Each builds directly on the previous. The collector roadmap (`docs/collector/ROADMAP.md`) is the implementation detail for Phase 1–3 of this document.

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        analyseLaptop System                         │
│                                                                     │
│  ┌──────────────┐   push JSON   ┌─────────────────────────────┐    │
│  │  collector/  │ ─────────────▶│         monitor/            │    │
│  │  (Go agent)  │               │  (aggregator + analyser)    │    │
│  │              │◀───check plan─│                             │    │
│  └──────────────┘               │  ┌─────────────────────┐   │    │
│   runs on each                  │  │  Anomaly Detection  │   │    │
│   monitored node                │  │  CUSUM / EWMA / PCA │   │    │
│                                 │  └─────────────────────┘   │    │
│                                 │  ┌─────────────────────┐   │    │
│                                 │  │   Root Cause Engine │   │    │
│                                 │  │   (causal graph)    │   │    │
│                                 │  └─────────────────────┘   │    │
│                                 └──────────────┬──────────────┘    │
│                                                │                   │
│                                                ▼                   │
│                              ┌────────────────────────────────┐   │
│                              │         dashboard/             │   │
│                              │   (web UI + Grafana + alerts)  │   │
│                              └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Academic Research Basis

| Paper | Key Contribution |
|---|---|
| Sundberg et al. **"Efficient Continuous Latency Monitoring with eBPF"** PAM 2023, LNCS 13882. https://doi.org/10.1007/978-3-031-28486-1_9 | ePPing eBPF design; 1 Mpps / 10 Gbps on a single core; TCP timestamp matching for passive RTT |
| Rezvani et al. **"Characterizing In-Kernel Observability of Latency-Sensitive Workloads"** ISPASS 2024. https://danielwong.org/files/eBPF-ISPASS2024.pdf | Per-request latency breakdown (kernel stack, scheduler delay, NIC queue) using eBPF kprobes |
| Red Hat / Sundberg **"netstacklat: eBPF-powered network stack latency"** 2026. https://developers.redhat.com/articles/2026/04/29/ | In-kernel per-packet latency at each network stack layer — identifies *where* latency is introduced |
| Bertrone et al. **"COP2: Continuously Observing Protocol Performance"** arXiv:1902.04280, 2019. https://arxiv.org/abs/1902.04280 | eBPF kprobes on Linux TCP stack internals; extracts `srtt_us`, retransmit count, cwnd from `tcp_sock`; negligible overhead |
| Münz, G. **"Traffic Anomaly Detection and Cause Identification Using Flow-Level Measurements"** TU Munich, NET-2010-06-1. https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2010-06-1.pdf | CUSUM + Shewhart control charts; PCA anomaly detection; automated cause identification |
| Christodoulou et al. **"A Combination of CUSUM-EWMA for Anomaly Detection in Time Series"** DSAA 2015. https://pure.ulster.ac.uk/en/publications/a-combination-of-cusum-ewma | Combined CUSUM-EWMA outperforms either alone; reduces false positives |
| Tikumporn et al. **"Automated Root Cause Analysis of Network Failures in IP Networks"** IEEE Access 2025. https://doi.org/10.1109/ACCESS.2025.11053841 | Causal DAG RCA; symptom-to-cause mapping; 92% accuracy on real failure corpus |
| Zabala et al. **"Optimality of a Network Monitoring Agent"** Mathematics 11(3):610, 2023. https://doi.org/10.3390/math11030610 | MDP optimal scheduling; adaptive intervals outperform fixed by 40–60% |
| Amjad et al. **"Optimal Probing with Statistical Guarantees"** arXiv:2109.07743, 2021. https://doi.org/10.48550/arXiv.2109.07743 | A-optimal probe budget; Frank-Wolfe approximation; 50% probe reduction |
| Hinz et al. **"TCP's Third Eye: eBPF for Telemetry-Powered Congestion Control"** ACM SIGCOMM 2023. https://dl.acm.org/doi/10.1145/3609021.3609295 | eBPF-extracted TCP congestion signals (cwnd, rtt_var, retransmit rate) |
| Zhao et al. **"Wasm-bpf: Streamlining eBPF Deployment in Cloud Environments"** arXiv:2408.04856, 2024. https://arxiv.org/abs/2408.04856 | eBPF in containerised environments; BTF CO-RE portability; minimal overhead vs native |

---

## Component & Reference Documentation

The detailed, per-component specifications live under `docs/`. This roadmap is the
top-level plan; the documents below are its implementation detail and research
backing.

| Document | What it covers |
|---|---|
| [`docs/collector/ROADMAP.md`](docs/collector/ROADMAP.md) | Collector implementation roadmap — the phase-by-phase Go agent spec (check inventory, eBPF, MDP scheduling) that Phases 1–5 above build on |
| [`docs/collector/SUGGESTIONS.md`](docs/collector/SUGGESTIONS.md) | Collector design suggestions — file layout, per-check OIDs/methods, OT safety rules, OS-support matrix |
| [`docs/theory/`](docs/theory/) | Research documents grounding each phase: anomaly detection, eBPF deployment constraints, probe scheduling, OT/segment-health theory |
| [`docs/gap-analysis/`](docs/gap-analysis/) | Collector-vs-standalone parity analysis and the research guide for open gap topics |
| [`docs/guides/`](docs/guides/) | Operator guides: setup, capture & Wi-Fi, operations, research & decisions |
| [`docs/setup/00-setup.md`](docs/setup/00-setup.md) | Menu-driven installer walkthrough |

---

## Phase 1 — Collector: Complete Check Inventory (Weeks 1–5)

**Component:** `collector/`  
**Detail:** See `docs/collector/ROADMAP.md` Phases 0–1 for full implementation specification.

### What this phase delivers
- Multi-packet ICMP with RTT distribution (p50/p95/p99) and loss %
- Interface counters (rx/tx bytes, errors, drops) as rates per cycle
- Default GW + WAN checks (public IP tracking, Cloudflare/Google baseline latency)
- OS health (CPU, memory, swap, disk, load average, temperature)
- SNMP v2c/v3 GET with `sysUpTime` regression detection
- Modbus TCP read-only (FC01, FC03 only — IEC 62443 compliant)
- WireGuard peer handshake age + throughput delta
- TLS certificate expiry countdown

### Key output format for downstream analysis

Every check cycle produces a structured JSON envelope pushed to the `monitor/` aggregator:

```json
{
  "collector_id": "homelab-pi4",
  "ts": "2026-07-25T13:00:00Z",
  "cycle_ms": 312,
  "streams": {
    "icmp_targets": [ {"target": "192.168.1.1", "rtt_p50": 1.2, "rtt_p95": 3.8, "loss_pct": 0.0} ],
    "net_interfaces": [ {"name": "eth0", "rx_bps": 124000, "tx_bps": 48000, "rx_error_rate": 0.0} ],
    "os_health": {"cpu_ratio": 0.12, "mem_avail_bytes": 3221225472},
    "snmp_hosts": [ {"host": "192.168.1.254", "sysUpTime_s": 432000, "uptime_regression": false} ],
    "wireguard_peers": [ {"pubkey": "abc...", "handshake_age_s": 23, "rx_bps": 8200} ]
  }
}
```

### Folded-in tasks from the prior roadmap

These operational checks from the earlier field-probe roadmap live in this phase
because they are collector-side data acquisition (the raw streams the `monitor/`
maths later consumes).

- [ ] **#54 — SNMPv3 read + STP observation.** Extend the SNMP GET check to full
  SNMPv3 (authPriv, credentials from the dashboard settings store, never Git).
  Read the Bridge-MIB / RSTP objects (`dot1dStpTopChanges`, port states,
  designated root) so a topology change becomes an observable stream field.
  Emit `stp_topology_changes` and per-port state into the `snmp_hosts` envelope;
  a rising `dot1dStpTopChanges` is a symptom Phase 4 RCA can map to a cause.

---

## Phase 2 — eBPF Passive Latency Layer (Weeks 5–7)

**Component:** `collector/` (Linux nodes only)  
**Academic basis:** Sundberg PAM 2023; Rezvani ISPASS 2024; Bertrone COP2 2019; Red Hat netstacklat 2026

### 2a. eBPF Kprobes for TCP RTT — Go Implementation

The `cilium/ebpf` library (the standard Go eBPF toolchain) provides two complementary approaches for TCP RTT extraction. The following is the concrete implementation path, grounded in the COP2 paper (Bertrone 2019) and the `cilium/ebpf` `tcp_close` example.

#### Approach A: Kprobe on `tcp_close` (RTT at connection end)

This kprobe fires when a TCP connection closes and reads the smoothed RTT (`srtt_us`) directly from the kernel's `tcp_sock` struct. It is the approach used in the `cilium/ebpf` official examples and in COP2.

**BPF C program** (`collector/ebpf/tcprtt.c`):

```c
// +build ignore
#include <linux/bpf.h>
#include <linux/tcp.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_core_read.h>   // CO-RE: portable across kernel versions

// Ring buffer for user-space consumption
struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 256 * 1024);
} events SEC(".maps");

// Event struct shared with Go
struct rtt_event {
    __u32 saddr;      // source IP (network byte order)
    __u32 daddr;      // dest IP
    __u16 sport;
    __u16 dport;
    __u32 srtt_us;    // smoothed RTT in microseconds (kernel value is srtt_us >> 3)
    __u32 retransmits;
    __u32 lost;
};

SEC("kprobe/tcp_close")
int BPF_KPROBE(tcp_close, struct sock *sk) {
    struct tcp_sock *ts = (struct tcp_sock *)sk;
    struct rtt_event *e;

    // Only IPv4 for now
    if (BPF_CORE_READ(sk, sk_family) != AF_INET)
        return 0;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) return 0;

    e->saddr      = BPF_CORE_READ(sk, __sk_common.skc_rcv_saddr);
    e->daddr      = BPF_CORE_READ(sk, __sk_common.skc_daddr);
    e->sport      = BPF_CORE_READ(sk, __sk_common.skc_num);
    e->dport      = BPF_CORE_READ(sk, __sk_common.skc_dport);
    // srtt_us stores 8x the actual smoothed RTT — right-shift by 3 to get µs
    e->srtt_us    = BPF_CORE_READ(ts, srtt_us) >> 3;
    e->retransmits = BPF_CORE_READ(ts, total_retrans);
    e->lost       = BPF_CORE_READ(ts, lost_out);

    bpf_ringbuf_submit(e, 0);
    return 0;
}

char LICENSE[] SEC("license") = "GPL";
```

**Key design notes (CO-RE):**
- `BPF_CORE_READ` uses BTF (BPF Type Format) to read struct fields portably across kernel versions without recompilation. This is essential for running the same binary on kernel 5.10 (Raspberry Pi OS Bookworm) and kernel 6.x (Ubuntu 24.04).
- `BPF_MAP_TYPE_RINGBUF` is preferred over `perf_event_array` for kernel ≥ 5.8: lower overhead, no per-CPU buffers, no event loss on slow consumers.

**Go user-space loader** (`collector/ebpf/tcprtt_loader.go`):

```go
//go:generate go run github.com/cilium/ebpf/cmd/bpf2go -cc clang -cflags "-O2 -g -Wall" TcpRtt ./tcprtt.c

package ebpf

import (
    "encoding/binary"
    "net"
    "time"

    ciliumebpf "github.com/cilium/ebpf"
    "github.com/cilium/ebpf/link"
    "github.com/cilium/ebpf/ringbuf"
    "github.com/cilium/ebpf/rlimit"
)

type RTTEvent struct {
    SrcIP      net.IP
    DstIP      net.IP
    SrcPort    uint16
    DstPort    uint16
    SrttUs     uint32   // smoothed RTT in microseconds
    Retransmits uint32
    Lost       uint32
    Ts         time.Time
}

func StartTCPRTTCollector(events chan<- RTTEvent) (stop func(), err error) {
    // Remove memlock rlimit (required for BPF maps on kernel < 5.11)
    if err := rlimit.RemoveMemlock(); err != nil {
        return nil, err
    }

    // Load pre-compiled BPF objects (generated by bpf2go)
    objs := TcpRttObjects{}
    if err := LoadTcpRttObjects(&objs, nil); err != nil {
        return nil, err
    }

    // Attach kprobe to tcp_close
    kp, err := link.Kprobe("tcp_close", objs.TcpClose, nil)
    if err != nil {
        objs.Close()
        return nil, err
    }

    // Open ring buffer reader
    rd, err := ringbuf.NewReader(objs.Events)
    if err != nil {
        kp.Close()
        objs.Close()
        return nil, err
    }

    go func() {
        var raw struct {
            Saddr, Daddr     uint32
            Sport, Dport     uint16
            SrttUs           uint32
            Retransmits, Lost uint32
        }
        for {
            rec, err := rd.Read()
            if err != nil {
                return // reader closed
            }
            binary.Read(bytes.NewReader(rec.RawSample), binary.LittleEndian, &raw)
            events <- RTTEvent{
                SrcIP:       intToIP(raw.Saddr),
                DstIP:       intToIP(raw.Daddr),
                SrcPort:     raw.Sport,
                DstPort:     raw.Dport,
                SrttUs:      raw.SrttUs,
                Retransmits: raw.Retransmits,
                Lost:        raw.Lost,
                Ts:          time.Now(),
            }
        }
    }()

    return func() { rd.Close(); kp.Close(); objs.Close() }, nil
}
```

**Build pipeline:** `go generate ./collector/ebpf/` runs `bpf2go` which invokes `clang`, compiles `tcprtt.c` to BPF bytecode, and generates `tcprtt_bpfeb.o` + `tcprtt_bpfel.o` + Go bindings. The `.o` files are embedded in the binary via `go:embed` — no external BPF compiler needed at runtime.

#### Approach B: TC Hook for Passive Timestamp-Based RTT (ePPing)

For per-flow RTT on *all* TCP connections (not just those closed on this host), use the TC ingress hook with TCP timestamp matching — this is the ePPing approach covered in `docs/collector/ROADMAP.md` Phase 2. The kprobe approach (Approach A) is complementary: it gives higher-fidelity per-connection RTT including `srtt_us` variance, while ePPing gives lower-overhead aggregate flow RTTs.

**Recommendation:** implement Approach A first (simpler, no BPF C for TC classifier needed), then add ePPing for passive aggregate monitoring.

### 2b. netstacklat — Per-Layer Stack Latency

The Red Hat `netstacklat` tool (2026) uses eBPF kprobes to measure where inside the kernel latency is added:

| Measurement point | What it reveals |
|---|---|
| NIC driver → socket buffer arrival | NIC queue depth, interrupt coalescence delay |
| Socket buffer → `tcp_rcv` | Kernel scheduler preemption delay |
| `tcp_rcv` → `recvmsg()` return | Application wakeup latency (epoll delay) |

**Implementation:** vendor `netstacklat` BPF C program; load via `cilium/ebpf`; expose per-layer histograms as `stack_latency` stream.

### 2c. High-Latency Client Detection

Using the per-flow RTT events from the kprobe collector (Phase 2a), detect clients with anomalously high RTT relative to the subnet baseline:

```go
// Maintain per-subnet rolling EMA of SrttUs over last 5 minutes
// For each RTTEvent:
//   ratio = event.SrttUs / subnet_baseline_us
//   if ratio > 3.0: emit HighLatencyClientEvent{SrcIP, DstIP, SrttUs, Baseline, Ratio}
// Aggregated and forwarded to monitor/ in the push envelope as "high_latency_clients" stream
```

### 2d. eBPF in Containerized and Kubernetes Environments

**Academic basis:** Zhao et al., Wasm-bpf, arXiv:2408.04856, 2024; DevConf.CZ 2024 (bpfman); Tigera eBPF for Kubernetes guide.

Deploying eBPF agents alongside containerized workloads requires specific patterns that differ from bare-metal deployment.

#### Capability Requirements (Minimum Privilege)

```yaml
# Kubernetes DaemonSet securityContext — minimum required for eBPF collector
securityContext:
  capabilities:
    add:
      - CAP_BPF        # load/query BPF programs and maps (kernel >= 5.8)
      - CAP_NET_ADMIN  # attach TC/XDP hooks
      - CAP_PERFMON    # perf_event_open for kprobes (kernel >= 5.8)
    drop:
      - ALL            # drop everything else
  readOnlyRootFilesystem: true
  runAsNonRoot: false  # BPF loading still requires uid 0 on most kernels
```

On kernels < 5.8: `CAP_SYS_ADMIN` was required for all BPF operations (blunt instrument). On ≥ 5.8: the split `CAP_BPF` + `CAP_PERFMON` allows least-privilege deployment.

#### BTF CO-RE: Write Once, Run Anywhere

The critical portability mechanism for containerized deployment is **BTF CO-RE (BPF Type Format, Compile Once – Run Everywhere)**:

```
Traditional BPF (pre-CO-RE):         CO-RE BPF:
  Compile on target kernel     vs.     Compile once with clang + libbpf
  Brittle: breaks on upgrade           BTF records field offsets in .o file
  Requires kernel headers              Kernel exposes BTF at /sys/kernel/btf/vmlinux
  Cannot ship pre-compiled binary      Loader relocates field accesses at load time
                                       Same .o runs on kernels 5.4 – 6.x
```

For the collector, this means:
- Build `tcprtt.o` once in CI (Ubuntu 24.04 + clang 17)
- Embed in Go binary with `go:embed`
- Binary runs on Raspberry Pi OS (kernel 6.1), Ubuntu 22.04 (kernel 5.15), Debian 12 (kernel 6.1) without recompilation
- Verify BTF availability at runtime: `os.Stat("/sys/kernel/btf/vmlinux")` — disable eBPF module gracefully if absent

#### Docker Deployment Pattern

```dockerfile
# collector/Dockerfile
FROM golang:1.22-alpine AS build
RUN apk add --no-cache clang llvm libbpf-dev linux-headers
WORKDIR /src
COPY . .
RUN go generate ./collector/ebpf/    # compile BPF C → bytecode
RUN CGO_ENABLED=0 go build -o /collector ./collector/

FROM debian:bookworm-slim
# Mount host /sys and /proc for BPF and metrics access
COPY --from=build /collector /collector
ENTRYPOINT ["/collector"]
```

```yaml
# docker-compose.yml — host network + minimal caps
services:
  collector:
    image: analyselaptop/collector:latest
    network_mode: host          # required: BPF maps are per-netns; host-ns needed for TC hooks
    pid: host                   # required: kprobes observe host kernel, not container kernel
    volumes:
      - /sys/kernel/btf:/sys/kernel/btf:ro   # BTF type information
      - /sys/fs/bpf:/sys/fs/bpf              # BPF pinned objects (optional)
      - /proc:/proc:ro                       # /proc/net/dev, /proc/net/arp etc.
    cap_add:
      - CAP_BPF
      - CAP_NET_ADMIN
      - CAP_PERFMON
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
```

**Critical constraints:**
- `network_mode: host` is mandatory — TC hooks and kprobes attach to the host kernel's network namespace. A containerized network namespace would only see container-internal traffic.
- `pid: host` is mandatory for kprobes — they observe kernel symbols in the host PID namespace.
- `/sys/kernel/btf` must be mounted read-only for CO-RE relocation to work.

#### Kubernetes DaemonSet Pattern

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: analyselaptop-collector
spec:
  template:
    spec:
      hostNetwork: true          # same as network_mode: host
      hostPID: true              # same as pid: host
      containers:
      - name: collector
        image: analyselaptop/collector:latest
        securityContext:
          privileged: false      # never use privileged if avoidable
          capabilities:
            add: [CAP_BPF, CAP_NET_ADMIN, CAP_PERFMON]
            drop: [ALL]
        volumeMounts:
        - name: btf
          mountPath: /sys/kernel/btf
          readOnly: true
        - name: bpffs
          mountPath: /sys/fs/bpf
        - name: proc
          mountPath: /proc
          readOnly: true
      volumes:
      - name: btf
        hostPath: { path: /sys/kernel/btf }
      - name: bpffs
        hostPath: { path: /sys/fs/bpf, type: DirectoryOrCreate }
      - name: proc
        hostPath: { path: /proc }
```

#### Graceful Degradation Strategy

The collector must run usefully even when eBPF is unavailable (older kernels, restricted environments, Windows nodes):

```go
func (c *Collector) initEBPF() {
    if runtime.GOOS != "linux" {
        log.Info("eBPF disabled: non-Linux OS")
        return
    }
    if _, err := os.Stat("/sys/kernel/btf/vmlinux"); err != nil {
        log.Info("eBPF disabled: BTF not available (kernel too old or CONFIG_DEBUG_INFO_BTF not set)")
        return
    }
    if err := rlimit.RemoveMemlock(); err != nil {
        log.Info("eBPF disabled: cannot remove memlock rlimit (missing CAP_BPF?)")
        return
    }
    // All checks passed — start eBPF collector
    stop, err := ebpf.StartTCPRTTCollector(c.rttEvents)
    if err != nil {
        log.Warnf("eBPF startup failed: %v — falling back to active ICMP", err)
        return
    }
    c.ebpfStop = stop
    log.Info("eBPF TCP RTT collector active")
}
```

---

## Phase 3 — Monitor: Time-Series Anomaly Detection (Weeks 7–11)

**Component:** `monitor/` (Python)  
**Academic basis:** Münz TU Munich 2010; Christodoulou et al. DSAA 2015

The `monitor/` process receives JSON from all collectors and runs statistical change detection on every metric time series. No ML training required — these are parameter-light control chart methods proven on real ISP data.

### 3a. Metric Time-Series Pipeline

```
Raw JSON stream → timeseries.py (60s bucketing, 8 metrics per stream)
  → residuals.py (Holt-Winters seasonal decomposition: α=0.2, β=0.1, γ=0.3, period=24h)
  → detector.py  (3-layer: Shewhart k=3 | CUSUM h=5, slack=0.5 | EWMA λ=0.2, L=3)
  → alarm only if CUSUM + EWMA both trigger (Christodoulou 2015: reduces false positives)
```

### 3b. CUSUM + EWMA Implementation (Python)

```python
# monitor/detector.py
import numpy as np
from dataclasses import dataclass, field

@dataclass
class ControlChartState:
    """Stateful detector per metric per source. Call update() each interval."""
    # CUSUM parameters (Münz 2010: h=5*sigma, slack=0.5*sigma typical for network metrics)
    cusum_h: float = 5.0       # decision interval (in units of sigma)
    cusum_slack: float = 0.5   # allowance (k) — half of detectable shift size
    # EWMA parameters (Christodoulou 2015: lambda=0.2 balances responsiveness vs noise)
    ewma_lambda: float = 0.2
    ewma_L: float = 3.0        # control limit width (sigma multiplier)
    # Shewhart
    shewhart_k: float = 3.0

    # State (updated each call)
    mu: float = 0.0            # rolling mean of residuals (updated during stable periods)
    sigma: float = 1.0         # rolling std of residuals
    cusum_pos: float = 0.0     # C+
    cusum_neg: float = 0.0     # C-
    ewma_z: float = 0.0        # Z_t
    n_stable: int = 0          # consecutive stable intervals (for baseline update)
    alarm_history: list = field(default_factory=list)

    def update(self, residual: float) -> dict:
        """Returns alarm dict if triggered, else empty dict."""
        alarms = {}

        # Shewhart: immediate large-shift detection
        if abs(residual) > self.shewhart_k * self.sigma:
            alarms['shewhart'] = True

        # CUSUM: cumulative drift detection
        slack = self.cusum_slack * self.sigma
        h = self.cusum_h * self.sigma
        self.cusum_pos = max(0, self.cusum_pos + residual - slack)
        self.cusum_neg = max(0, self.cusum_neg - residual - slack)
        if self.cusum_pos > h or self.cusum_neg > h:
            alarms['cusum'] = True
            # Reset after alarm (Page 1954 recommendation)
            self.cusum_pos = 0.0
            self.cusum_neg = 0.0

        # EWMA: smoothed trend
        lam = self.ewma_lambda
        self.ewma_z = lam * residual + (1 - lam) * self.ewma_z
        ewma_limit = self.ewma_L * self.sigma * np.sqrt(lam / (2 - lam))
        if abs(self.ewma_z) > ewma_limit:
            alarms['ewma'] = True

        # Combined alarm: only fire if CUSUM + EWMA both triggered
        # Shewhart fires independently (instantaneous large anomaly)
        triggered = alarms.get('shewhart') or (
            alarms.get('cusum') and alarms.get('ewma')
        )

        # Update baseline only during stable periods (prevent contamination)
        if not triggered:
            self.n_stable += 1
            if self.n_stable > 10:  # update after 10 stable intervals
                alpha = 0.05  # slow adaptation of baseline
                self.mu = (1 - alpha) * self.mu + alpha * residual
                # Welford online variance update for sigma
                delta = residual - self.mu
                self.sigma = max(0.001, (1 - alpha) * self.sigma + alpha * abs(delta))
        else:
            self.n_stable = 0

        return {'triggered': triggered, 'alarms': alarms} if triggered else {}
```

### 3c. Multi-Metric PCA Anomaly Detection

```python
# monitor/pca_detector.py — incremental PCA for multi-metric correlation
from sklearn.decomposition import IncrementalPCA
from scipy.stats import chi2
import numpy as np

class PCADetector:
    """
    Hotelling T² anomaly detection on 8-dimensional metric vector.
    Incremental PCA update (no full retraining).
    Academic basis: Münz TU Munich 2010, Chapter 9.
    """
    def __init__(self, n_components=3, alpha=0.001):
        self.pca = IncrementalPCA(n_components=n_components)
        self.threshold = chi2.ppf(1 - alpha, df=n_components)
        self.fitted = False
        self.n_seen = 0

    def update(self, x: np.ndarray) -> bool:
        """x: shape (8,) — one metric vector. Returns True if anomaly detected."""
        self.n_seen += 1
        if self.n_seen < 100:  # accumulate 100 samples before detecting
            self.pca.partial_fit(x.reshape(1, -1))
            return False
        self.fitted = True
        scores = self.pca.transform(x.reshape(1, -1))[0]
        lambdas = self.pca.explained_variance_
        t2 = float(np.sum((scores ** 2) / lambdas))
        if t2 > self.threshold:
            return True  # multivariate anomaly
        self.pca.partial_fit(x.reshape(1, -1))  # update only on non-anomalous samples
        return False
```

### 3d. Adaptive Per-Slot Control Limits

```python
# Per metric, per hour-of-week bucket (168 buckets = 7 days × 24 hours)
# sigma_slot[hour_of_week] = rolling stddev of residuals in that slot
# Control limit = k * sigma_slot — eliminates peak-hour false positives
hour_of_week = (now.weekday() * 24 + now.hour)  # 0–167
```

### Folded-in tasks from the prior roadmap

Both prior-roadmap items are trend-detection over the collector streams and so
belong to this phase's detector stack rather than the data plane.

- [ ] **#50 — TCP retransmission/reset + DNS failure trends.** Feed the eBPF
  `retransmits`/`lost` counters (Phase 2) and the Phase 1 DNS-check
  success/latency into the CUSUM+EWMA detectors as their own series. Alert on a
  sustained rise in retransmit ratio or DNS failure/SERVFAIL rate, not a single
  spike. Emit `tcp_retransmit_ratio` and `dns_failure_rate` as detector inputs;
  both become Phase 4 RCA symptoms.
- [ ] **#51 — Baselines by segment / hour / production state.** Generalise the
  168-bucket hour-of-week control limits above so the residual sigma is keyed by
  `(metric, subnet_segment, hour_of_week, production_state)`. `production_state`
  is an operator-set label (e.g. `production` vs `maintenance-window`) so a
  planned change window does not read as an anomaly. Fall back to the coarser
  bucket when a fine-grained slot has too few samples.

---

## Phase 4 — Monitor: Automated Root Cause Analysis (Weeks 11–14)

**Component:** `monitor/` (Python)  
**Academic basis:** Tikumporn et al. IEEE Access 2025; Münz TU Munich 2010 Chapter 10

### 4a. Causal DAG Architecture — Python Implementation

The `monitor/` service is Python-based. The RCA engine uses `networkx` for the DAG and `pgmpy` (or plain dict-based conditional probability tables) for belief propagation.

```
monitor/rca/
├── __init__.py
├── graph.py        — NetworkX DiGraph definition: symptom nodes → cause nodes
├── symptoms.py     — maps anomaly detector output dicts to symptom node IDs
├── causes.py       — cause definitions: id, label, remediation_hint, prior_prob
└── engine.py       — Bayesian belief propagation + decision tree for dropped connections
```

**DAG construction** (`monitor/rca/graph.py`):

```python
import networkx as nx

def build_rca_graph() -> nx.DiGraph:
    """
    Causal DAG: edges go FROM causes TO symptoms.
    Belief propagation traverses in reverse (symptoms → causes).
    Based on Tikumporn et al. 2025 causal chain taxonomy.
    """
    G = nx.DiGraph()

    # --- Cause nodes (root nodes — no incoming edges) ---
    causes = [
        ("BUFFERBLOAT",       {"label": "Bufferbloat / AQM issue",            "prior": 0.10}),
        ("WAN_CONGESTION",    {"label": "Upstream WAN congestion",             "prior": 0.15}),
        ("PHYSICAL_FAULT",    {"label": "Physical layer fault",               "prior": 0.10}),
        ("HOST_OVERLOAD",     {"label": "Target host overloaded",             "prior": 0.10}),
        ("DEVICE_REBOOT",     {"label": "Device reboot / crash",              "prior": 0.08}),
        ("NEW_DEVICE",        {"label": "New/rogue device on segment",        "prior": 0.05}),
        ("PORT_SCAN",         {"label": "Port scan / brute-force",            "prior": 0.05}),
        ("DNS_FAILURE",       {"label": "DNS resolver failure",               "prior": 0.08}),
        ("WG_TUNNEL_DROP",    {"label": "WireGuard tunnel dropped",           "prior": 0.07}),
        ("CERT_EXPIRY",       {"label": "TLS certificate expiring",           "prior": 0.05}),
        ("POWER_LOSS",        {"label": "Target powered off / cable pull",   "prior": 0.12}),
        ("ROUTING_FAILURE",   {"label": "Routing / default GW failure",       "prior": 0.05}),
    ]
    for node_id, attrs in causes:
        G.add_node(node_id, node_type="cause", **attrs)

    # --- Symptom nodes (leaf nodes — observed) ---
    symptoms = [
        "SYM_RTT_HIGH", "SYM_LOSS_HIGH", "SYM_LOSS_TOTAL",
        "SYM_ARP_GONE", "SYM_UPTIME_REGRESS", "SYM_RX_ERRORS",
        "SYM_NEW_SRC_IPS", "SYM_DST_CONCENTRATION",
        "SYM_DNS_LATENCY", "SYM_WG_STALE", "SYM_CERT_EXPIRING",
        "SYM_GW_UNREACHABLE", "SYM_WAN_UNREACHABLE",
    ]
    for s in symptoms:
        G.add_node(s, node_type="symptom")

    # --- Causal edges with P(symptom | cause) ---
    edges = [
        # BUFFERBLOAT: RTT very high, loss zero, BW normal
        ("BUFFERBLOAT",     "SYM_RTT_HIGH",          {"p": 0.90}),
        # WAN_CONGESTION: RTT up + loss up, affects all targets
        ("WAN_CONGESTION",  "SYM_RTT_HIGH",          {"p": 0.80}),
        ("WAN_CONGESTION",  "SYM_LOSS_HIGH",         {"p": 0.75}),
        ("WAN_CONGESTION",  "SYM_WAN_UNREACHABLE",   {"p": 0.40}),
        # PHYSICAL_FAULT: error rate spike
        ("PHYSICAL_FAULT", "SYM_RX_ERRORS",         {"p": 0.85}),
        ("PHYSICAL_FAULT", "SYM_RTT_HIGH",           {"p": 0.50}),
        ("PHYSICAL_FAULT", "SYM_LOSS_HIGH",          {"p": 0.60}),
        # POWER_LOSS: total loss + ARP gone
        ("POWER_LOSS",     "SYM_LOSS_TOTAL",         {"p": 0.95}),
        ("POWER_LOSS",     "SYM_ARP_GONE",           {"p": 0.90}),
        # DEVICE_REBOOT: sysUpTime regression
        ("DEVICE_REBOOT",  "SYM_UPTIME_REGRESS",     {"p": 0.99}),
        ("DEVICE_REBOOT",  "SYM_LOSS_HIGH",          {"p": 0.30}),
        # NEW_DEVICE: new src IPs on segment
        ("NEW_DEVICE",     "SYM_NEW_SRC_IPS",        {"p": 0.85}),
        # PORT_SCAN: high flow count to single dst
        ("PORT_SCAN",      "SYM_DST_CONCENTRATION",  {"p": 0.90}),
        ("PORT_SCAN",      "SYM_NEW_SRC_IPS",        {"p": 0.40}),
        # DNS_FAILURE
        ("DNS_FAILURE",    "SYM_DNS_LATENCY",        {"p": 0.95}),
        # WG_TUNNEL_DROP
        ("WG_TUNNEL_DROP", "SYM_WG_STALE",           {"p": 0.99}),
        # CERT_EXPIRY
        ("CERT_EXPIRY",    "SYM_CERT_EXPIRING",      {"p": 1.00}),
        # ROUTING_FAILURE
        ("ROUTING_FAILURE","SYM_GW_UNREACHABLE",     {"p": 0.90}),
        ("ROUTING_FAILURE","SYM_LOSS_HIGH",          {"p": 0.70}),
    ]
    G.add_edges_from([(u, v, d) for u, v, d in edges])
    return G
```

**Belief propagation engine** (`monitor/rca/engine.py`):

```python
from dataclasses import dataclass
from typing import List
import networkx as nx

@dataclass
class RCAResult:
    cause: str
    label: str
    confidence: float
    evidence_chain: List[str]
    remediation_hint: str

REMEDIATION = {
    "BUFFERBLOAT":    "Enable fq_codel / CAKE AQM on router. Check buffer size settings.",
    "WAN_CONGESTION": "Check ISP status. Run traceroute to identify congested hop.",
    "PHYSICAL_FAULT": "Check cable, SFP, switch port. Check wireless RSSI.",
    "POWER_LOSS":     "Check device power, PDU, UPS. Verify cable connection.",
    "DEVICE_REBOOT":  "Check device logs for crash reason. Check UPS/power stability.",
    "NEW_DEVICE":     "Verify device against whitelist. Check DHCP logs.",
    "PORT_SCAN":      "Check firewall logs. Block source if unauthorized.",
    "DNS_FAILURE":    "Restart resolver. Check /etc/resolv.conf. Test alternate DNS.",
    "WG_TUNNEL_DROP": "Check WireGuard logs. Verify endpoint reachability and PSK.",
    "CERT_EXPIRY":    "Renew TLS certificate immediately. Check auto-renewal (certbot).",
    "ROUTING_FAILURE":"Run 'ip route'. Check default GW. Verify DHCP lease.",
    "HOST_OVERLOAD":  "Check CPU/memory on target. Kill runaway process.",
}

class RCAEngine:
    def __init__(self, graph: nx.DiGraph, confidence_threshold: float = 0.6):
        self.G = graph
        self.threshold = confidence_threshold

    def analyse(self, active_symptoms: List[str]) -> RCAResult:
        """
        Naive Bayes belief propagation over causal DAG.
        P(cause | symptoms) ∝ P(cause) × ∏ P(symptom | cause)
        """
        cause_nodes = [n for n, d in self.G.nodes(data=True) if d.get('node_type') == 'cause']
        scores = {}

        for cause in cause_nodes:
            prior = self.G.nodes[cause].get('prior', 0.1)
            likelihood = 1.0
            for sym in active_symptoms:
                if self.G.has_edge(cause, sym):
                    p = self.G.edges[cause, sym].get('p', 0.5)
                else:
                    p = 0.05  # low base probability of symptom given unrelated cause
                likelihood *= p
            scores[cause] = prior * likelihood

        # Normalise to get posterior probabilities
        total = sum(scores.values()) or 1.0
        posteriors = {c: s / total for c, s in scores.items()}
        best_cause = max(posteriors, key=posteriors.get)
        confidence = posteriors[best_cause]

        return RCAResult(
            cause=best_cause,
            label=self.G.nodes[best_cause].get('label', best_cause),
            confidence=confidence,
            evidence_chain=[f"{sym} → {best_cause}" for sym in active_symptoms
                            if self.G.has_edge(best_cause, sym)],
            remediation_hint=REMEDIATION.get(best_cause, "No automated remediation defined."),
        )
```

### 4b. Symptom → Cause Mapping Table

| Observed Symptoms | Most Probable Cause | Confidence |
|---|---|---|
| RTT p95 ↑ + loss = 0 + BW normal | Bufferbloat / AQM | High |
| RTT p95 ↑ + loss ↑ + all targets | WAN congestion | High |
| RTT p95 ↑ + loss ↑ + one target | Host overload / cable | High |
| loss = 100% + ARP gone | Power loss / cable pull | High |
| sysUpTime regression | Device reboot | High |
| rx_error spike | Physical layer fault | Medium |
| new src_ips + flow count ↑ | New/rogue device | Medium |
| dst_ip concentration + high flows | Port scan | Medium |
| DNS latency ↑ + WAN RTT normal | DNS resolver failure | High |
| WG handshake_age > 3 min | WireGuard tunnel drop | High |
| TLS days_remaining < 7 | Certificate expiry | Certain |
| GW unreachable + loss ↑ | Routing failure | High |

### 4c. Dropped Connection Decision Tree

```
Dropped connection detected
  ├─ ARP entry still present?  No  → POWER_LOSS
  ├─ Default GW reachable?     No  → ROUTING_FAILURE
  ├─ WAN reachable?            No  → WAN_CONGESTION / ISP failure
  ├─ Target reachable from another collector?  No → HOST failure
  │                                            Yes → PATH_SPECIFIC (asymmetric routing)
  └─ RTT elevated before drop? Yes → Congestion-induced timeout (not hard failure)
                               No  → Application crash / firewall session timeout
```

---

## Phase 5 — Monitor: MDP Adaptive Scheduling + Probe Budget (Weeks 14–17)

**Component:** `monitor/` → `collector/` (check plan delivery)  
**Academic basis:** Zabala et al. Mathematics 2023; Amjad et al. arXiv 2021  
**Detail:** See `docs/collector/ROADMAP.md` Phases 4–5

The `monitor/` process computes the optimal check plan and pushes it back to each collector:

```
monitor/ (control plane):
  1. Receive probe results from collector
  2. Update MDP state per target: STABLE → SUSPECT → DEGRADED → DOWN
  3. Compute probe weight ∝ RTT variance (Welford online, Amjad 2021)
  4. Generate updated check_plan.json (probe intervals per target)
  5. POST check_plan to collector /config endpoint

Probe interval by state:
  STABLE    → base_interval      (default 30s)
  SUSPECT   → base_interval / 6  (5s — accelerated)
  DEGRADED  → base_interval / 3  (10s — sustained)
  DOWN      → base_interval      (30s — heartbeat only)
```

---

## Phase 6 — Dashboard: Visualisation & Alerting (Weeks 17–20)

**Component:** `dashboard/`

- **Topology map:** NetworkX graph rendered to SVG/D3; nodes colour-coded by MDP state; edges annotated with RTT p95 + loss %
- **Anomaly timeline:** swim-lane chart per collector; one marker per anomaly event; RCA result in tooltip
- **High-latency client table:** live table from eBPF kprobe events (Phase 2c); sortable by RTT ratio
- **Alert routing:** webhook / email / Alertmanager; confidence-gated: >0.8 auto-alert, 0.6–0.8 flagged probable, <0.6 raw symptoms only

### Folded-in tasks from the prior roadmap

Operator-facing reporting and notification surfaces land here, on the dashboard.

- [ ] **#53 — Webhook/email alerting on sustained state changes.** The concrete
  implementation of the "Alert routing" bullet above: dashboard-configurable
  webhook and SMTP targets, fired only on a *sustained* MDP state change
  (STABLE→SUSPECT→DEGRADED/DOWN held past a debounce window), never on a single
  cycle. Confidence-gated as above; deliveries recorded in the audit trail.
- [ ] **#48 — Session/acceptance report (JSON/CSV/HTML) with hashes.** A
  one-click export summarising a monitoring session: targets, uptime, anomaly
  events with RCA verdicts, baseline deviations, and config in effect. Emit
  JSON + CSV + a self-contained HTML report, each with a SHA-256 content hash so
  the artefact is tamper-evident for an acceptance hand-off.
- [ ] **#47 (trigger) — Freeze-evidence action.** A dashboard button that snapshots
  the current stream buffers + active anomaly/RCA context into a timestamped,
  hashed evidence bundle. Snapshots collected JSON telemetry only — full PCAP
  stays out of scope per the architecture. The disk-reserve policy that backs it
  is a Phase 8 config concern (below).

---

## Phase 7 — Prometheus + Grafana Integration (Weeks 20–21)

**Component:** `monitor/` + `dashboard/`

Prometheus metrics from `monitor/`:

```
anomaly_events_total{collector, metric, detector}    counter
anomaly_active{collector, target, state}             gauge
rca_cause_total{cause}                               counter
rca_confidence_histogram                             histogram
network_rtt_p95_seconds{src_collector, dst_target}  gauge
network_loss_ratio{src_collector, dst_target}        gauge
high_latency_clients_total{subnet}                   gauge
```

Pre-built Grafana dashboard JSON in `dashboard/grafana/`.

---

## Phase 8 — Hardening, Tests, Deployment (Weeks 21–24)

**Component:** `tests/`, `scripts/`, `config/`

```
tests/
├── unit/
│   ├── test_detector_cusum.py      — CUSUM correctness with synthetic anomaly series
│   ├── test_detector_ewma.py       — EWMA false positive rate validation
│   ├── test_pca_detector.py        — T² statistic threshold validation
│   ├── test_rca_engine.py          — DAG traversal and belief propagation
│   ├── test_rca_graph.py           — symptom→cause edge coverage
│   └── collector/mdp_scheduler_test.go  — MDP state machine transitions (Go)
├── integration/
│   ├── test_collector_push.py      — Full push cycle with mock aggregator
│   └── test_rca_multinode.py       — Cross-collector correlation scenarios
└── load/
    └── collector_load_test.go      — 1000-target, 5s intervals, <50ms cycle time
```

Deployment scripts:
```
scripts/
├── install-collector.sh    — systemd unit; grants CAP_BPF/NET_ADMIN/PERFMON if eBPF enabled
├── install-monitor.sh      — Python venv + systemd unit + reverse proxy
├── install-dashboard.sh    — static build or Docker Compose
└── update.sh               — rolling update with health check gate
```

### Folded-in tasks from the prior roadmap

- [ ] **#47 (policy) — Disk reserve / capture policy.** The config + hardening half
  of the freeze-evidence feature (dashboard trigger in Phase 6): a `config/`
  schema for a reserved evidence partition/quota, retention and rotation of
  evidence bundles, and a hard floor that refuses a snapshot when free space
  would drop below the reserve. Keeps evidence capture from ever filling the
  disk and taking the collector/monitor down.

---

## Full Timeline

| Phase | Component | Description | Start | Duration |
|---|---|---|---|---|
| **1** | `collector/` | Complete check inventory (ICMP, SNMP, Modbus, WG, TLS, OS, routes) | Now | 5 weeks |
| **2** | `collector/` | eBPF: kprobe TCP RTT (cilium/ebpf + bpf2go), netstacklat, high-latency client detection, container deployment | Wk 5 | 2 weeks |
| **3** | `monitor/` | CUSUM+EWMA+PCA anomaly detection (Python); Holt-Winters residuals; adaptive slots | Wk 7 | 4 weeks |
| **4** | `monitor/` | Causal DAG RCA (networkx + naive Bayes); dropped connection decision tree | Wk 11 | 3 weeks |
| **5** | `monitor/`→`collector/` | MDP adaptive scheduling + Frank-Wolfe probe budget | Wk 14 | 3 weeks |
| **6** | `dashboard/` | Topology map, anomaly timeline, high-latency client table, alert routing | Wk 17 | 3 weeks |
| **7** | `monitor/`+`dashboard/` | Prometheus metrics + Grafana dashboard JSON | Wk 20 | 1 week |
| **8** | `tests/`+`scripts/`+`config/` | Full test suite, config schemas, systemd + Docker deployment | Wk 21 | 3 weeks |

**Total: 24 weeks (~6 months)**

---

## Prior-Roadmap Reconciliation

The open items from the earlier field-probe roadmap are folded into the phases
above by capability (not by their old priority label). Each is a `- [ ]` task in
its phase's *"Folded-in tasks from the prior roadmap"* subsection.

| Prior item | Folded into | Rationale |
|---|---|---|
| **#54** SNMPv3 read + STP observation | Phase 1 | Collector-side data acquisition; STP change becomes a stream field |
| **#50** TCP retransmission/reset + DNS failure trends | Phase 3 | Trend detection over collector streams via CUSUM+EWMA |
| **#51** Baselines by segment / hour / production state | Phase 3 | Generalises the 168-bucket adaptive control limits |
| **#53** Webhook/email alerting on sustained state changes | Phase 6 | Concrete build of the Phase 6 alert-routing bullet |
| **#48** Session/acceptance report (JSON/CSV/HTML) + hashes | Phase 6 | Operator-facing reporting/export surface |
| **#47** Freeze-evidence action + disk reserve/capture policy | Phase 6 (trigger) + Phase 8 (policy) | Dashboard action snapshots JSON telemetry; disk-reserve is config/hardening. Full PCAP stays out of scope. |

---

## What Is Deliberately Out of Scope

| Item | Reason |
|---|---|
| Anomaly detection in `collector/` | Collector is stateless data-plane only. All maths lives in `monitor/`. |
| Full Q-learning / deep RL for MDP | Requires failure corpus. Finite-state MDP approximation achieves ~80% of theoretical optimum without training data (Zabala 2023). |
| PCAP / full packet capture | eBPF provides RTT and flow metadata without payload recording. Avoids GDPR and storage burden. |
| Custom ML training pipeline | CUSUM+EWMA+PCA are parameter-light; validated on real ISP data (Münz 2010); no labelled training data needed. |
| eBPF on Windows nodes | Not supported by the Linux kernel eBPF subsystem. Windows nodes use active ICMP probing (graceful fallback). |

---

## References

1. Sundberg et al. "Efficient Continuous Latency Monitoring with eBPF." PAM 2023. https://doi.org/10.1007/978-3-031-28486-1_9
2. Rezvani et al. "Characterizing In-Kernel Observability of Latency-Sensitive Workloads using eBPF." ISPASS 2024. https://danielwong.org/files/eBPF-ISPASS2024.pdf
3. Bertrone et al. "COP2: Continuously Observing Protocol Performance." arXiv:1902.04280, 2019. https://arxiv.org/abs/1902.04280
4. Red Hat Engineering. "netstacklat: eBPF and network stack latency." 2026. https://developers.redhat.com/articles/2026/04/29/boosting-speed-use-ebpf-and-netstacklat-troubleshoot-latency
5. Münz, G. "Traffic Anomaly Detection and Cause Identification." TU Munich, 2010. https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2010-06-1.pdf
6. Christodoulou et al. "A Combination of CUSUM-EWMA for Anomaly Detection in Time Series." DSAA 2015. https://pure.ulster.ac.uk/en/publications/a-combination-of-cusum-ewma-for-anomaly-detection-in-time-series--3
7. Tikumporn et al. "Automated Root Cause Analysis of Network Failures." IEEE Access 2025. https://doi.org/10.1109/ACCESS.2025.11053841
8. Hinz et al. "TCP's Third Eye: eBPF for Telemetry-Powered Congestion Control." ACM SIGCOMM 2023. https://dl.acm.org/doi/10.1145/3609021.3609295
9. Zabala et al. "Optimality of a Network Monitoring Agent." Mathematics 11(3):610, 2023. https://doi.org/10.3390/math11030610
10. Amjad et al. "Optimal Probing with Statistical Guarantees." arXiv:2109.07743, 2021. https://doi.org/10.48550/arXiv.2109.07743
11. Zhao et al. "Wasm-bpf: Streamlining eBPF Deployment in Cloud Environments." arXiv:2408.04856, 2024. https://arxiv.org/abs/2408.04856
12. cilium/ebpf examples: tcp_close RTT kprobe. https://github.com/cilium/ebpf/blob/main/examples/tcprtt/

---

### P5 — excluded-by-default capability gate

A governance surface (Dashboard → **Dangerous Actions**), NOT an attack toolkit.
Each excluded behaviour is registered, shown with its risk, and gated behind an
explicit master switch plus per-item acknowledgement, with every attempt written
to the audit trail. The checkbox marks that the item is **surfaced and gated** —
the destructive technique itself is deliberately **not implemented** and
`/api/dangerous/<id>/run` refuses even when fully unlocked.

- [x] Automatic subnet expansion — gated, refused by design
- [x] Vulnerability / exploit scanning — gated, refused by design
- [x] Credential guessing, default-password checks — gated, refused by design
- [x] SNMP community sweeps — gated, refused by design
- [x] Wi-Fi deauthentication — gated, refused by design
- [x] Wi-Fi frame injection — gated, refused by design
- [x] Wi-Fi AP impersonation (rogue/evil-twin) — gated, refused by design
- [x] S7 / OPC UA writes — gated, refused by design
- [x] PLC mode changes / program operations — gated, refused by design
- [x] Arbitrary OPC UA node browsing — gated, refused by design
- [x] Inline blocking / automatic production changes — gated, refused by design
- [x] Internet dashboard exposure — gated, refused by design

These remain **excluded by default** as a matter of design. The gate exists to
make the exclusion explicit and auditable, not to enable the behaviours. The
destructive techniques are intentionally left unbuilt.
