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
│  ┌──────────────┐   mTLS+OTLP  ┌─────────────────────────────┐    │
│  │  collector/  │ ───────────▶│         monitor/            │    │
│  │  (Go agent)  │               │  (aggregator + analyser)    │    │
│  │              │◄───check plan─│                             │    │
│  │  Gorilla     │               │  ┌─────────────────────┐   │    │
│  │  compressed  │               │  │  Anomaly Detection  │   │    │
│  │  local store │               │  │  CUSUM / EWMA / PCA │   │    │
│  └──────────────┘               │  └─────────────────────┘   │    │
│   runs on each                  │  ┌─────────────────────┐   │    │
│   monitored node                │  │   Root Cause Engine │   │    │
│                                 │  │   (causal graph)    │   │    │
│   ┌──────────────┐             │  └─────────────────────┘   │    │
│   │ backend PKI │             │  hot/cold Gorilla store      │    │
│   │ CA + cert   │             └──────────────────────────────┘    │
│   │ issuance    │                              │                   │
│   └──────────────┘                              │                   │
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
| Pelkonen et al. **"Gorilla: A Fast, Scalable, In-Memory Time Series Database"** VLDB 2015. https://www.vldb.org/pvldb/vol8/p1816-teller.pdf | Delta-of-delta timestamps + XOR float64; 12× compression; 96% of timestamps = 1 bit |
| Tagliaro et al. **"A Longitudinal View of IoT TLS Deployments"** ACM CCS 2024. | 99.84% of IoT backends use insecure transport; mTLS design requirement |

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
| [`docs/theory/probes/probe-to-backend-transport-theory.md`](docs/theory/probes/probe-to-backend-transport-theory.md) | Secure probe-to-backend transport theory (mTLS, OTLP/gRPC, backend-generated PKI, Gorilla wire format) |
| [`docs/theory/probes/gorilla-compression-go-theory.md`](docs/theory/probes/gorilla-compression-go-theory.md) | Delta-of-delta / XOR compression theory; Go library comparison; `collector/` reference implementation; hot/cold SQLite schema |
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

On kernels < 5.8: `CAP_SYS_ADMIN` was required for all BPF operations (blunt instrument). On ≥ 5.8: the split `CAP_BPF` + `CAP_PERFMON` allows least-privilege deplo