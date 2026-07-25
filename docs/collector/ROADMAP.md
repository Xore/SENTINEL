# Collector Implementation Roadmap
## Research-Grounded Network Probe & Health Monitoring

> **Date:** 2026-07-25  
> **Updated:** 2026-07-25 — WiFi health (Phase 1), mtr native (Phase 6), broadcast/multicast top-talker (Phase 3) added to v2 scope.  
> **Basis:** Peer-reviewed academic literature + industry standards  
> All phases are additive — each builds directly on the previous.

---

## Background: Academic Foundations

### Active vs. Passive vs. Hybrid Probing (RFC 7799)

RFC 7799 formally defines the three monitoring paradigms that every probe design must choose from:

| Paradigm | Mechanism | Overhead | Blind Spots |
|---|---|---|---|
| **Active** | Generate synthetic probe packets (ICMP, TCP SYN, TWAMP) | Small but measurable | Probes may traverse different paths than real traffic |
| **Passive** | Observe existing traffic without injection | Near-zero | Requires traffic to flow; no data on idle links |
| **Hybrid** | Combine both; use passive to steer active probes | Tunable | Complexity of both |

*Source: Sundberg (2024), "Towards Ubiquitous and Continuous Network Latency Monitoring", Karlstad University Licentiate Thesis.*

**Conclusion for this collector:** The current agent is purely active. The roadmap adds **passive interface counters and eBPF-based RTT observation** (Phase 2), then merges both into a **hybrid adaptive scheduler** (Phase 4). This mirrors what the Wren project (ACM SIGMETRICS) proved to be optimal: passive data steers which active probes to run and at what cadence.

---

### Latency as the Primary Health Metric

Sundberg (2024) demonstrates that bandwidth is a poor proxy for user-perceived network quality — **RTT and packet loss % are the leading indicators** of network degradation. Key empirical findings from ISP deployment:

- **Time-of-day pattern:** RTT increases sharply during peak hours, but only in the *external* network path, not the local segment — meaning a collector must separately measure LAN RTT and WAN RTT to localise degradation.
- **Bufferbloat signature:** An elevated RTT with stable bandwidth (measured via interface counters) is a near-perfect indicator of buffer bloat (AQM-related), not link failure.
- **Loss % precedes outage:** Packet loss % begins rising 2–15 minutes before a link fully fails. Binary up/down detection misses this window entirely.

**Implication:** The collector must track RTT *distributions* (p50, p95, p99), not just average RTT, and must measure loss %, not just reachability.

---

### Optimal Probe Budget Allocation (Amjad et al., 2021, arXiv:2109.07743)

This Microsoft Research / Inria paper proves that with a **fixed probing budget**, a statistical experimental design approach (A-optimal or E-optimal design approximated by Frank-Wolfe algorithm) allocates probes to paths in proportion to their **measurement uncertainty**, not uniformly. Results on real cloud networks:

- **50% reduction in probe traffic** with equivalent or better estimation accuracy
- Uniform fixed-interval polling wastes probe budget on stable paths
- Paths with recent anomalies or high variance should receive **more frequent probes**

**Implication:** The collector's fixed 30-second uniform interval is wasteful. The roadmap implements an **adaptive backoff/accelerate** scheme: stable targets probe every 60 s, recently-degraded targets probe every 5 s. This is the practical version of the Frank-Wolfe budget allocation without the full MIP complexity.

---

### MDP-Based Adaptive Scheduling (Zabala et al., 2023, Mathematics 11(3):610)

This paper models a network monitoring agent as a **Markov Decision Process (MDP)**:

- **State:** Current health status of each monitored target (REACHABLE, DEGRADED, UNREACHABLE)
- **Action:** Which target to probe next, at what interval
- **Reward:** Reduction in uncertainty about network state
- **Transition:** Empirical RTT/loss observations update the state belief

The paper proves that an MDP scheduler on commodity hardware **outperforms fixed-interval polling** in detection latency (time from failure onset to alert) by 40–60%, because it concentrates probe effort where uncertainty is highest.

**Practical approximation for this collector (Phase 4):**

```
State machine per target:
  STABLE    → probe every base_interval (default 30s)
  SUSPECT   → probe every base_interval / 6 (default 5s)
  DEGRADED  → probe every base_interval / 3 (default 10s), alert
  DOWN      → probe every base_interval (heartbeat only), alert

Transitions:
  STABLE  + (loss > 1% OR rtt_p95 > 2x baseline) → SUSPECT
  SUSPECT + (2 consecutive confirms)               → DEGRADED
  SUSPECT + (1 clean probe)                        → STABLE
  DEGRADED + (3 consecutive clean probes)          → STABLE
  DEGRADED + (loss = 100% for 2 cycles)            → DOWN
  DOWN    + (1 successful probe)                   → DEGRADED
```

This is a simplified finite-state MDP approximation. Full Q-learning or policy gradient would require a training corpus of failure events; the finite-state version is deployable immediately.

---

### Link Failure Classification (Brügge & Simon, TU Munich, NET-2024-04-1)

This TU Munich seminar paper classifies network failure modes relevant to a software probe:

| Failure Type | Detectable By | Detection Method |
|---|---|---|
| Cable/physical layer break | ICMP unreachable, ARP disappearance | Ping loss 100% + neighbour entry gone |
| Wireless interference / RSSI drop | Interface error counter spike + WiFi signal dBm | RX errors/drops in `/proc/net/dev` + `iw dev link` |
| Network overload / congestion | RTT elevation + high TX drops | RTT p95 > threshold AND TX_drop delta |
| Node crash / reboot | sysUpTime reset, ARP flap | SNMP sysUpTime, uptime check |
| Routing failure (no default GW) | Route table empty or GW unreachable | `ip route` parse + GW ping |
| DNS failure | DNS lookup timeout | DNS health check |
| VPN tunnel failure | WireGuard handshake age > 3 min | wgctrl |
| **Rogue AP / WiFi intrusion** | **New BSSID on `wifi_new_ap_detected`** | **`iw scan` diff against known AP whitelist** |
| **Broadcast/multicast storm** | **`bcast_total_pps` spike** | **AF_PACKET gopacket top-talker snapshot** |

**Implication:** Each failure type requires a different detection primitive. The collector must run all in parallel — they are not redundant.

---

### eBPF for Passive Latency Monitoring (Sundberg, PAM 2023)

Sundberg's `epping` tool (Evolved Passive Ping) implements **in-kernel passive RTT measurement** using eBPF's TC/XDP hooks. Proven results:

- Monitors RTT for **all TCP flows** at multi-gigabit rates on commodity hardware
- Overhead an **order of magnitude lower** than libpcap-based user-space solutions
- Zero impact on monitored traffic (fully passive)
- Works on any Linux device running kernel ≥ 5.6

For the collector, this means: instead of actively sending ICMP probes to measure RTT to a gateway, an eBPF program on the collector node can **passively observe the RTT of all real traffic** flowing through it — far more representative of actual user experience.

**Constraint:** eBPF requires root / `CAP_BPF` + `CAP_NET_ADMIN`. On nodes where this is acceptable, it is superior to active ICMP probing. On restricted nodes, stick with active ICMP.

---

## Phase 0 — Hardening the Existing Collector (Now)

**Goal:** Make the current checks production-quality before adding new ones.

| Task | What | Why |
|---|---|---|
| **P0.1** | Replace binary `up/down` ping with multi-packet ICMP (count=5, report loss %) | Loss % is the leading failure indicator (Sundberg 2024) |
| **P0.2** | Track RTT distribution: store `rtt_min`, `rtt_max`, `rtt_p50`, `rtt_p95` per target | Required for anomaly baseline (Amjad 2021) |
| **P0.3** | Add `tx_errors`, `rx_errors`, `rx_dropped` to interface collection | Wireless congestion detection (TU Munich 2024) |
| **P0.4** | Separate GW ping from host pings — always ping default GW regardless of check plan | GW reachability is the root of all routing failures |
| **P0.5** | Cap per-check timeout to 4 s with context; never block the goroutine pool | Prevents one slow OT target from delaying all checks |
| **P0.6** | Add `collector_test.go` coverage for MDP state machine (Phase 4 prep) | |

**Library additions for Phase 0:**
```
golang.org/x/net/icmp   v0.x  # multi-packet ICMP with sequence tracking
```

**Estimated effort:** 2–3 days

---

## Phase 1 — Complete the Check Inventory (Weeks 1–3)

**Goal:** Implement all checks documented in `SUGGESTIONS.md` Sections 6.1–6.10 **plus** WiFi health monitoring.

### 1a. Interface Counters (`net_interfaces.go`) — P0 priority

```go
// Linux: parse /proc/net/dev — zero privilege
// Windows: exec PowerShell Get-NetAdapterStatistics | ConvertTo-Json
type ifaceCounters struct {
    Name       string
    RxBytes    uint64
    TxBytes    uint64
    RxErrors   uint64
    TxErrors   uint64
    RxDropped  uint64
    TxDropped  uint64
    // Deltas computed against previous cycle values — rate, not cumulative
    RxBps      float64  // derived
    TxBps      float64  // derived
    ErrorRate  float64  // (rx_errors+tx_errors) / (rx_bytes+tx_bytes)
}
```

Track **deltas** between cycles, not raw counters, so the aggregator receives rates (bytes/s, errors/s).

### 1b. Route Table + Default GW (`net_routes_linux.go` / `net_routes_windows.go`)

```go
// Linux:   exec("ip", "-j", "route")   → JSON output since iproute2 v4.12
// Windows: exec("route", "print", "-4") → parse text
// Always extract: destination, gateway, interface, metric, proto
// Always ping: each unique gateway IP → rtt_ms, loss_pct
```

### 1c. WAN Checks (`net_wan.go`)

```go
// Sequential:
// 1. GET public_ip_url → confirms internet egress
// 2. pingWithLoss("1.1.1.1", 5, 3000) → Cloudflare latency baseline
// 3. pingWithLoss("8.8.8.8", 5, 3000) → Google latency baseline
// 4. Optional: GET external_url → full-stack DNS+TLS+HTTP test
// Return: public_ip, changed (bool), cf_rtt_p95, google_rtt_p95, external_ok
```

### 1d. OS Health (`os_health_linux.go` / `os_health_windows.go`)

```go
// Linux — no privilege required:
//   CPU:    /proc/stat (user+nice+system / total_ticks, delta per cycle)
//   Mem:    /proc/meminfo (MemAvailable / MemTotal)
//   Swap:   /proc/meminfo (SwapFree / SwapTotal)
//   Disk:   syscall.Statfs for each configured path
//   Uptime: /proc/uptime
//   Load:   /proc/loadavg (load1, load5, load15)
//   Temp:   /sys/class/thermal/thermal_zone*/temp (optional, Pi-friendly)
```

### 1e. SNMP GET (`ot_snmp.go`)

```go
// Uses github.com/gosnmp/gosnmp
// Minimum viable OID set:
var baseOIDs = []string{
    "1.3.6.1.2.1.1.1.0",  // sysDescr
    "1.3.6.1.2.1.1.3.0",  // sysUpTime  ← uptime drop = IoC
    "1.3.6.1.2.1.1.5.0",  // sysName
    "1.3.6.1.2.1.2.1.0",  // ifNumber
}
// Per-interface OIDs walked: ifDescr, ifOperStatus, ifInErrors, ifOutErrors
// sysUpTime regression detection: if new_uptime < previous_uptime → reboot event
```

### 1f. Modbus TCP Read-Only (`ot_modbus.go`)

```go
// Uses github.com/things-labs/go-modbus
// Only FC01 (read coils) and FC03 (read holding registers)
// Hard-coded safety guard: refuse any write function code
// Timeout: configurable, default 2000ms
// Rate: one request per target per collection cycle (IEC 62443 constraint)
```

### 1g. WireGuard Peer Health (`net_wireguard.go`)

```go
// Uses golang.zx2c4.com/wireguard/wgctrl
// Per peer: flag as DOWN if LastHandshakeTime.IsZero() OR time.Since(LastHandshake) > 3*time.Minute
// Track RxBytes/TxBytes deltas — a peer with zero throughput but recent handshake = degraded
```

### 1h. TLS Certificate Expiry (`tls_check.go`)

```go
// net.DialTimeout → tls.Client → Handshake → PeerCertificates[0].NotAfter
// No CAP_NET_RAW needed; works without privilege
// Classify: ok (days > warn), warning (warn >= days > 0), critical (expired)
```

### 1i. WiFi Health (`net_wifi_linux.go` / `net_wifi_windows.go`) — **NEW in v2 scope**

WiFi health is treated as a first-class check module, not an optional extra. Wireless is the primary transport for many collector nodes (Raspberry Pi deployments on site).

**What it measures:**

| Metric | Linux source | Windows source |
|---|---|---|
| Signal strength (dBm) | `iw dev wlan0 link` | `netsh wlan show interfaces` |
| Link quality (%) | `/proc/net/wireless` | `netsh wlan show interfaces` |
| Noise floor (dBm) | `iw dev wlan0 link` | `netsh wlan show interfaces` |
| TX/RX bitrate (Mbps) | `iw dev wlan0 link` | `netsh wlan show interfaces` |
| Channel + frequency | `iw dev wlan0 link` | `netsh wlan show interfaces` |
| Connected BSSID + SSID | `iw dev wlan0 link` | `netsh wlan show interfaces` |
| Visible AP inventory | `iw dev wlan0 scan` | `netsh wlan show networks mode=bssid` |
| New AP detection | Diff vs known-AP cache | Diff vs known-AP cache |
| AP disappearance | Diff vs known-AP cache | Diff vs known-AP cache |

**Signal drop detection:** Signal tracked as rolling window. Drop > 15 dBm within one interval → MDP state machine transitions WiFi-dependent targets to `StateSuspect`.

**New AP alert:** Any BSSID not in the configured `ap_whitelist` generates a `wifi_new_ap_detected=1` metric event. On OT zone nodes, this triggers an immediate IEC 62443 rogue-AP alert.

**OT safety:** On OT-zone nodes, `scan_mode` is forced to `passive` (`iw dev wlan0 scan passive`) — listens for beacons only, zero probe-request RF injection.

```go
// net_wifi_linux.go  //go:build linux
type WiFiChecker struct {
    ifaces   []string
    knownAPs map[string]APEntry  // BSSID → APEntry, persisted across cycles
    cfg      WiFiConfig
}

func (w *WiFiChecker) Collect() ([]WifiMetric, []APEntry, []APEntry, error) {
    // Returns: metrics, newAPs, goneAPs, error
    // 1. exec "iw dev <iface> link"   → parse signal/noise/bitrate/bssid
    // 2. parse /proc/net/wireless      → link quality int/max
    // 3. exec "iw dev <iface> scan"    → AP inventory, diff against w.knownAPs
    // 4. emit wifi_signal_dbm, wifi_link_quality_pct, wifi_ap_count etc.
    // 5. emit wifi_new_ap_detected=1 for each new BSSID
}
```

**Privilege:** `iw` is a standard tool on all Linux distros; no special capability needed for `iw link`. `iw scan` requires the interface to be up. No CAP required beyond normal user on most distros (interface is owned by collector user via udev rule).

**Estimated effort for 1i:** 3–4 days (Linux + Windows)

**Estimated effort Phase 1 total:** 1–2 weeks

---

## Phase 2 — Passive eBPF Latency Layer (Weeks 3–5, Linux only)

**Goal:** Add in-kernel passive RTT measurement alongside active probing, following Sundberg's `epping` design.

**Why:** Active ICMP probes may traverse a different network path than real traffic (load balancers, policy routing). Passive eBPF observes the *actual* latency that application traffic experiences.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  collector process (Go, user space)                          │
│                                                              │
│  ┌──────────────┐     BPF map read    ┌──────────────────┐  │
│  │ sample loop  │ ←──────────────── ── │ ebpf_reader.go   │  │
│  └──────────────┘                      └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
            ↑  BPF map (per-flow RTT histogram)
┌─────────────────────────────────────────────────────────────┐
│  Linux kernel                                                │
│  TC hook → epping.bpf.c                                     │
│    match TCP TSval/TSecr pairs → compute RTT per flow       │
│    bucket into histogram map keyed by (src_ip, dst_ip)      │
└─────────────────────────────────────────────────────────────┘
```

### Implementation Path

1. **Vendor `epping` eBPF C program** from Sundberg's open-source implementation (Apache-2 licensed)
2. **Compile to BPF bytecode** (`clang -target bpf`) and embed in Go binary via `go:embed`
3. **Load via `cilium/ebpf` Go library** — load program, attach to TC ingress hook on configured interface
4. **Read BPF map** every sample cycle — aggregate per-subnet RTT histograms
5. **Report as new stream:** `passive_rtt_observations` with fields: `src_subnet`, `dst_subnet`, `rtt_p50_ms`, `rtt_p95_ms`, `rtt_p99_ms`, `flow_count`, `ts`

**Library additions:**
```
github.com/cilium/ebpf   v0.x   # BPF program loading and map access
```

**Privilege:** Requires `CAP_BPF` + `CAP_NET_ADMIN`. Falls back gracefully if caps are absent.

**Estimated effort:** 1 week (if `epping` BPF C is vendored as-is)

---

## Phase 3 — Segment Health Analysis (Weeks 5–7)

**Goal:** Detect endpoints that are disproportionately degrading the network — chatty devices, misconfigured DHCP clients, broadcast storms, and rogue ARP.

### 3a. ARP Rate Monitoring (`net_arp_watch.go`)

```go
// Track ARP table between cycles:
// - New entry appearing = new device (alert if not in whitelist)
// - Entry disappearing = device left or rebooted
// - ARP rate: if a single IP generates > N ARP replies per minute → broadcast storm indicator
// Data source: read /proc/net/arp (Linux) or arp -a (Windows) each cycle
// Alert: new_devices[], disappeared_devices[], arp_rate_anomalies[]
```

Academic basis: TU Munich (2024) identifies ARP broadcast storms as a leading cause of wireless segment congestion. RITICS Appendix A lists "unexpected ARP broadcasting" as an OT IoC.

### 3b. Per-Subnet Traffic Load (`net_segment_health.go`)

If the collector is running on a router/gateway (Raspberry Pi, VPS):

```go
// Read /proc/net/dev for the segment-facing interface
// Correlate RX byte rate with ARP neighbour count
// Estimate per-device bandwidth: total_rx_bytes / active_neighbour_count
// Flag: if segment utilisation > 70% AND neighbour_count > N → congestion from device density
// Flag: if one device accounts for > 40% of traffic (requires eBPF flow data from Phase 2)
```

### 3c. DHCP Lease Exhaustion Check (`net_dhcp_check.go`)

```go
// Linux (dnsmasq): parse /var/lib/misc/dnsmasq.leases
// Alert: lease_count / max_leases > 80%
// Alert: same MAC requesting new lease repeatedly (DHCP storm)
```

### 3d. DNS Query Rate (Pi-hole Integration) (`check_pihole.go`)

```go
// GET http://pi.hole/api/summary → JSON
// Extract: dns_queries_today, ads_blocked_today, clients_ever_seen, unique_clients
// Alert: query_rate > baseline + 3σ → DNS amplification or misconfigured client
```

### 3e. Port Scan / Sweep Detection (`os_ports.go` extension)

```go
// exec("ss", "-tnp", "state", "syn-sent")  → outbound SYN flood from this host
// exec("ss", "-tnp", "state", "time-wait") → connection exhaustion indicator
// Alert: syn_sent > threshold → this host is scanning or misconfigured
```

### 3f. Broadcast/Multicast Top-Talker Snapshot (`net_bcast.go`) — **NEW in v2 scope**

> **Implementation depends on research task:** `docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md`

Captures a short AF_PACKET snapshot (default 10 s every 5 min) to identify the top-N source MACs by broadcast and multicast packet rate on each interface. Uses gopacket `pcapgo` (no libpcap binary) with a kernel BPF pre-filter for bcast/mcast only.

**Purpose:** Broadcast/multicast storms are a leading OT/wireless failure cause (TU Munich NET-2024-04-1 §3; RITICS Appendix A). Interface counters alone cannot identify *which device* is responsible. This module closes that gap.

**Metrics emitted:**
```
bcast_top_talker_pps{interface, src_mac, type="broadcast|ipv4_mcast|ipv6_mcast"}
bcast_top_talker_bps{interface, src_mac, type}
mcast_top_talker_pps{interface, src_mac, dst_ip}
bcast_total_pps{interface}
```

**OT safety:** AF_PACKET `SOCK_RAW` is fully passive — zero injected packets. Unicast traffic is kernel-filtered before reaching user space.

**Privilege:** Requires `CAP_NET_RAW`. Falls back gracefully (module disabled with log warning) if cap is absent.

**Platform:** Linux only (AF_PACKET). Windows variant is deferred (NDIS raw socket complexity).

**Estimated effort for 3f:** 1 week (after research task resolves prototype choice)

**Estimated effort Phase 3 total:** ~1.5 weeks

---

## Phase 4 — MDP Adaptive Probe Scheduler (Weeks 7–10)

**Goal:** Replace the fixed-interval ticker loop with a state-machine scheduler that concentrates probe effort where uncertainty is highest.

*Basis: Zabala et al. (2023), Mathematics 11(3):610 — MDP optimality proof for network monitoring agents.*

### State Machine Per Target

```go
type probeState uint8

const (
    StateStable   probeState = iota // probe at base_interval
    StateSuspect                    // probe at base_interval / 6 (accelerated)
    StateDegraded                   // probe at base_interval / 3, alert sent
    StateDown                       // probe at base_interval (heartbeat), alert sent
)
```

### Transition Logic

```go
func (h *targetHealth) transition(rtt_p95, loss_pct float64, reachable bool) {
    switch h.State {
    case StateStable:
        if loss_pct > 1.0 || rtt_p95 > 2.0*h.RTTBaseline {
            h.State = StateSuspect
        }
    case StateSuspect:
        if !reachable || loss_pct > 5.0 {
            h.FailCount++
            if h.FailCount >= 2 { h.State = StateDegraded }
        } else {
            h.State = StateStable
        }
    // ... (see COLLECTOR-V2-REFACTOR.md Section 5)
    }
}
```

**WiFi integration:** Signal drop > 15 dBm within one interval (from `net_wifi_linux.go`) also triggers `StateSuspect` for any ICMP/TCP/HTTP targets routed over that wireless interface.

**Estimated effort:** 1–1.5 weeks

---

## Phase 5 — Probe Budget Optimisation (Weeks 10–12)

**Goal:** Implement a simplified version of the Frank-Wolfe probe budget allocation from Amjad et al. (2021).

```go
// For each target, maintain a rolling variance of RTT over last 20 observations
// Probe weight = variance / sum(all_variances)
// Total probes per minute = budget (configurable, default 120/min = 2/s)
// Allocation: target_probes_per_min = weight * budget
```

**Estimated effort:** 3–4 days

---

## Phase 6 — mtr Hop-Level Diagnosis (Weeks 12–14)

**Goal:** When a target transitions to `DEGRADED`, automatically run an mtr-style hop-level trace to localise *which hop* introduced the latency or loss.

**v2 upgrade from original design:** Rather than shelling out to `traceroute`/`tracert`, the v2 collector implements mtr natively using `golang.org/x/net/icmp` raw sockets. This provides:
- Per-hop **loss %** and RTT distribution (p50/p95), not just single-probe RTT
- No dependency on `mtr`, `traceroute`, or `tracert` binaries on the collector node
- Consistent output format across Linux/arm64, Linux/amd64, and Windows/amd64

```go
// net_mtr.go
func RunMTR(target string, maxHops, probesPerHop int, timeoutMs int) ([]HopResult, error) {
    // Uses golang.org/x/net/icmp — requires CAP_NET_RAW or root
    // For each TTL from 1 to maxHops:
    //   Send probesPerHop ICMP Echo requests with TTL=n
    //   Collect ICMP Time Exceeded replies → record hop IP + RTT
    //   If ICMP Echo Reply received → target reached, stop
}
```

**Trigger policy:**
1. MDP `StateDegraded` → run mtr once, emit all hop metrics as a single `trace_id`-tagged batch
2. Config `mtr.only_on_degraded: false` → run on every cycle (not recommended for OT/battery nodes)
3. Backend check-plan with `"mtr_force": true` → immediate manual trigger

**Metrics emitted:**
```
mtr_hop_rtt_ms{target, hop, hop_ip, trace_id}
mtr_hop_loss_pct{target, hop, hop_ip, trace_id}
mtr_hop_count{target, trace_id}
```

**Privilege fallback:** If `CAP_NET_RAW` is absent, falls back to `exec("traceroute", ...)` / `exec("tracert", ...)`.

Academic basis: Augustin et al. "Avoiding traceroute anomalies with Paris traceroute" IMC 2006; TU Munich NET-2024-04-1 §5 (hop-level failure localisation as critical diagnostic step).

**Estimated effort:** 3–4 days (native raw ICMP is ~2× the effort of exec-based, but no binary dependency)

---

## Phase 7 — Metrics Export & Integration (Weeks 14–16)

**Goal:** Allow the collector to optionally expose a Prometheus `/metrics` endpoint in addition to pushing to the aggregator.

```go
// metrics.go — github.com/prometheus/client_golang/prometheus
// Expose: probe_rtt_seconds, probe_loss_ratio, interface_rx_bytes_total,
//         wireguard_peer_handshake_age_seconds, wifi_signal_dbm,
//         wifi_link_quality_pct, bcast_total_pps, mtr_hop_rtt_ms, ...
```

**Estimated effort:** 2 days

---

## Implementation Timeline Summary

| Phase | Description | Duration | Priority |
|---|---|---|---|
| **0** | Harden existing checks (loss %, RTT distribution, GW ping) | 2–3 days | **Now** |
| **1** | Complete check inventory + WiFi health (`net_wifi_*.go`) | 1–2 weeks | **Week 1** |
| **2** | Passive eBPF RTT layer (epping, Linux only) | 1 week | **Week 3** |
| **3** | Segment health / excessive client detection + **broadcast/multicast top-talker** | 1.5 weeks | **Week 5** |
| **4** | MDP adaptive probe scheduler (WiFi signal as trigger input) | 1–1.5 weeks | **Week 7** |
| **5** | Frank-Wolfe probe budget allocation (simplified) | 3–4 days | **Week 10** |
| **6** | **mtr native raw ICMP** hop-level tracing for DEGRADED targets | 3–4 days | **Week 12** |
| **7** | Prometheus metrics export (includes WiFi + mtr + bcast metrics) | 2 days | **Week 14** |

---

## Go Modules Required

```
# go.mod additions
require (
    golang.org/x/net                       v0.x.x   // ICMP raw socket (loss %, mtr hop-tracing)
    github.com/gosnmp/gosnmp               v1.x.x   // SNMP v2c/v3
    github.com/things-labs/go-modbus       v0.x.x   // Modbus TCP
    golang.zx2c4.com/wireguard/wgctrl      v0.x.x   // WireGuard
    github.com/cilium/ebpf                 v0.x.x   // eBPF loading (Phase 2)
    github.com/prometheus/client_golang    v1.x.x   // Metrics export (Phase 7)
    github.com/google/gopacket             v1.1.19  // Bcast/mcast capture (Phase 3, Linux)
)
```

---

## Academic References

| Paper | Key Contribution | Applied In |
|---|---|---|
| Sundberg, S. "Towards Ubiquitous and Continuous Network Latency Monitoring." Karlstad University Licentiate Thesis, 2024. https://doi.org/10.59217/xpyc8728 | RTT distribution > binary up/down; eBPF passive monitoring; bufferbloat signature | Phase 0, Phase 2 |
| Amjad, M.J. et al. "Optimal Probing with Statistical Guarantees for Network Monitoring at Scale." arXiv:2109.07743, 2021. https://doi.org/10.48550/arXiv.2109.07743 | A-optimal probe budget allocation; 50% probe reduction; Frank-Wolfe approximation | Phase 4, Phase 5 |
| Zabala, L. et al. "Optimality of a Network Monitoring Agent and Validation in a Real Environment." Mathematics 11(3):610, 2023. https://doi.org/10.3390/math11030610 | MDP model for monitoring agents; adaptive scheduling outperforms fixed interval by 40–60% | Phase 4 |
| Brügge, M. & Simon, M. "Link Failure Detection in Computer Networks." NET-2024-04-1, TU Munich, 2024. https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2024-04-1/NET-2024-04-1_09.pdf | Failure type taxonomy; wireless interference via RSSI; broadcast storm → congestion | Phase 0, Phase 3 |
| Augustin, B. et al. "Avoiding traceroute anomalies with Paris traceroute." ACM IMC 2006. https://dl.acm.org/doi/10.1145/1177080.1177100 | ECMP-aware traceroute design; per-hop loss measurement | Phase 6 |
| Wren project. "Combining active and passive network measurements to build scalable monitoring systems." ACM SIGMETRICS 2004. https://dl.acm.org/doi/10.1145/773056.773061 | Hybrid monitoring; passive data steers active probe selection | Phase 2, Phase 3 |
| ACM CoNEXT 2005. "Optimal positioning of active and passive monitoring devices." https://dl.acm.org/doi/10.1145/1095921.1095932 | One collector per segment is sufficient | Architecture |
| RITICS/NCSC ICS-COI. "How to log and monitor in ICS/OT Environments." 2024. https://ritics.org/wp-content/uploads/2024/08/How-to-log-and-monitor-in-ICS-OT-Environments.pdf | OT IoC list; ARP anomalies; sysUpTime regression; unexpected broadcast | Phase 1, Phase 3 |
| Ollila, T. "Overview for capabilities of OT network monitoring tools." JAMK Thesis, 2024. https://www.theseus.fi/handle/10024/851535 | OT tool evaluation; Modbus/SNMP gaps; IEC 62443 constraints | Phase 1 |
| RFC 7799. "Active and Passive Metrics and Methods." IETF, 2016. https://datatracker.ietf.org/doc/html/rfc7799 | Formal definition of active/passive/hybrid monitoring | Architecture |
| IEEE 802.11k-2008. "Neighbor Report." IEEE, 2008. | WiFi AP neighbor inventory; RSSI measurement standards | Phase 1 (WiFi) |
