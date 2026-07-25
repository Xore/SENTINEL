# Collector – Assessment & Improvement Suggestions

> **⚠️ SUPERSEDED — Last updated:** 2026-07-25  
> **This document is the academic background reference only.**  
> **The actionable v2 design has moved to: [`COLLECTOR-V2-REFACTOR.md`](COLLECTOR-V2-REFACTOR.md)**  
> That document contains the full gap table, file structure, go.mod, OTLP metric naming, OT safety rules, migration plan, and phased implementation roadmap (C1–C11), including **Wi-Fi health (C4), mtr hop-tracing (C6), and broadcast/multicast top-talker (C11)**.

---

## 1. What the Current Collector Does

The collector is a **Go-based lightweight push agent** (`v0.2.0`) that:

- Reads its own **network interfaces** (name, state, MAC, addresses) via `net.Interfaces()`
- Reads the **ARP/neighbour table** (`ip neigh` on Linux, `arp -a` on Windows)
- Runs **operator-configured active checks** pulled from the aggregator:
  - `ping` (host reachability via OS ping, platform-branched)
  - `dns` – resolves a hostname
  - `http` – GET with status code check
  - `tcp` – TCP connect check
  - `ntp` – SNTP client offset check
  - `port` – TCP/UDP open check with optional send/expect banner matching
- Sends a **fast heartbeat ping** (~5–10 s) and a **slower sample push** (default 30 s)
- Supports **HMAC-authenticated self-update** over HTTP from the aggregator

**v2 design:** The v2 collector bundles all features listed in Sections 3–6 below natively — including OS health (CPU/mem/disk/uptime), SNMP, Modbus, WireGuard, ICMP loss%, interface counters, WAN checks, TLS cert expiry, listening port snapshot, systemd unit state, **Wi-Fi health (signal/bitrate/retries/AP scan/new-AP detection), mtr-style hop-level route tracing, and broadcast/multicast top-talker snapshots**. `node_exporter` is no longer required on collector nodes. See [`COLLECTOR-V2-REFACTOR.md`](COLLECTOR-V2-REFACTOR.md).

---

## 2. Academic & Industry Research Context

### 2.1 Active vs. Passive Monitoring (Foundational Principle)

Peer-reviewed work on scalable monitoring platforms (Wren project, ACM SIGMETRICS) demonstrates that neither purely active nor purely passive monitoring is sufficient alone:

- **Passive monitoring** (ARP table reads, interface sniffing, SPAN ports) is zero-impact on the network but blind to path-level failures and WAN state.
- **Active monitoring** (ICMP, TCP probes, SNMP polls) adds measurable but small traffic load and gives ground-truth reachability and latency data.
- The academic recommendation is **hybrid**: use passive data (topology, utilisation) to *steer* which active probes to run, avoiding blanket active scanning. This is called "topology-based steering" and significantly reduces probe overhead without sacrificing measurement accuracy.

> **Implication for this collector:** The v2 collector implements both: active probes (all check types) and passive interface-counter collection (`/proc/net/dev`) in the same binary. The MDP adaptive scheduler (C6) implements topology-based steering driven by `priority_hints` from the backend. The broadcast/multicast top-talker module (C11) adds a third tier: **passive segment observation** via AF_PACKET/gopacket.

The Cambridge multi-layer Nprobe architecture (UCAM-CL-TR-571) further establishes that probes should capture only the minimal data needed per protocol layer, with full offline analysis at the aggregator. This justifies the current design of sending JSON rows/OTLP metrics rather than raw packet captures.

### 2.2 Probe Placement Optimality

A 2005 ACM CoNEXT paper on optimal positioning of active/passive devices proved that minimising probe hardware while maintaining full network observability is an NP-hard combinatorial problem, approximated efficiently with Mixed Integer Programming (MIP). The practical takeaway: **a single collector per network segment is sufficient** if it can observe the default gateway, DNS resolver, and key OT devices — you do not need a probe on every host.

### 2.3 OT/ICS Network Monitoring – Research & Standards

A 2024 Master's thesis from JAMK University (Ollila, 2024) evaluated 18 commercial OT monitoring tools (Claroty, Nozomi Networks, Microsoft Defender for IoT, Dragos, SCADAfence, etc.) and identified that **the most common gap is vendor-specific industrial protocol support** — generic IT monitoring tools cannot passively decode Modbus, S7, BACnet or OPC-UA traffic without dedicated parsers.

Key findings relevant to this collector:

| Finding | Impact on collector design |
|---|---|
| OT devices have 10–20 year lifespans; availability >> confidentiality | Probes must be **read-only / non-intrusive** — never write to Modbus registers |
| Most OT nets are flat (no VLAN segmentation) | ARP table enumeration covers the whole segment; passive discovery is reliable |
| Vendor remote access (VPN backdoors) is a major blind spot | Collector should log unexpected outbound connections via netstat/ss |
| Asset inventory is the first ROI value — unknown devices on the network | ARP + SNMP sysDescr already gives good inventory data |
| NTP clock skew is critical for OT log correlation | NTP check already implemented; v2 adds stratum check + offset < 1s enforcement |

The IEC 62443 standard (sections 3-1 to 3-3) governs component-level security in OT networks. **Monitoring must not disturb the control plane** — this rules out any SYN-scan-style active discovery. Only targeted, rate-limited Modbus reads (one request per cycle) and SNMP GETs are acceptable.

The RITICS/NCSC ICS-COI guidance (2024) provides the authoritative indicator list for OT network anomalies (see Appendix A below). The collector's check plan should alert on these:

- Unknown device appears in ARP table
- Modbus TCP traffic outside expected register range
- Controller uptime drop (reboot detected)
- PLC key switch position change (via SNMP OID or Modbus discrete input)
- Unexpected outbound connection from engineering workstation subnet
- **New Wi-Fi AP appearing on a monitored SSID or channel** (rogue AP indicator)
- **Broadcast/multicast storm exceeding threshold** (ARP flood, DHCP storm indicator)

### 2.4 Agent Architecture Patterns

The MDP-based network monitoring agent model (Zabala et al., 2023, *Mathematics* 11(3):610, cited 3 times) shows that a **Markov Decision Process** approach to scheduling checks — prioritising checks with highest uncertainty — outperforms fixed-interval polling on commodity hardware. This is directly applicable: the aggregator returns a `priority_hints` field in the check plan, telling the collector to re-probe recently-failed targets more aggressively. **Implemented in v2 as `scheduler/scheduler.go` (Phase C6).**

The push-vs-pull debate in distributed monitoring (HertzBeat community discussion, 2024) confirms the current push-active design is the right choice for NAT-traversal scenarios: the agent initiates all connections, requiring no inbound firewall rules.

### 2.5 Programming Language Considerations

After reviewing Go, Python, Rust, and C for this use case:

| Language | Binary size | Cross-compile | OT lib ecosystem | Verdict |
|---|---|---|---|---|
| **Go** | ~22–26 MB static (v2) | First-class | Good (gosnmp, go-modbus) | ✅ **Keep** |
| Python | Runtime required | Hard to single-binary | Best (pymodbus, pysnmp) | ❌ Deployment cost too high — but acceptable for standalone monitor |
| Rust | ~2 MB static | First-class | Immature OT libs | ⚠️ Future consideration |
| C | ~200 KB | Manual | libmodbus, net-snmp | ❌ Memory safety risk |

**Verdict: Keep Go.** The v2 binary grows to ~22–26 MB due to OTel SDK, gRPC, gosnmp, go-modbus, wgctrl, cilium/ebpf, gopacket, and modernc.org/sqlite — still a single static binary, zero runtime dependencies.

> **Note on Python:** The user confirmed Python is acceptable if Go cannot support a feature. In practice all three new features (Wi-Fi, mtr, broadcast/multicast) are implementable in Go: Wi-Fi via `iw`/`iwconfig` shell-out, mtr via `x/net/icmp` raw socket, broadcast/multicast via `github.com/google/gopacket` AF_PACKET. Python is not required.

---

## 3. Gap Analysis

> **These gaps are addressed in v2.** See [`COLLECTOR-V2-REFACTOR.md`](COLLECTOR-V2-REFACTOR.md) for implementation details, file assignments, and priority phasing.

### 3.1 Network Health Checks

| Missing Check | Academic / Industry Basis | Priority | v2 File |
|---|---|---|---|
| **Default gateway reachability + RTT** | Baseline for all routing problems | P0 | `net_routes.go` |
| **ICMP packet loss %** (multi-packet) | Wren / CoNEXT – loss % more informative than binary up/down | P0 | `net_icmp.go` |
| **Interface RX/TX counters, errors, drops** | `/proc/net/dev`; link degradation before failure | P0 | `net_interfaces.go` |
| **Route table dump** | Detect route injection / missing static routes | P1 | `net_routes.go` |
| **WAN public IP + ISP** | Failover / unexpected path detection | P1 | `net_wan.go` |
| **WAN latency anchors** (1.1.1.1, 8.8.8.8) | Absolute baseline, detect ISP degradation | P1 | `net_wan.go` |
| **WireGuard peer last-handshake age** | VPN silently dead; common in split-tunnel setups | P1 | `net_wireguard.go` |
| **DNS upstream check** (custom resolver vs. 8.8.8.8 delta) | DNS hijack / Pi-hole bypass detection | P1 | `checks.go` (extend) |
| **Wi-Fi link quality** (signal dBm, bitrate, retries, beacon loss) | Wireless degradation before packet loss; rogue AP detection | P1 | `net_wifi_linux.go` / `net_wifi_windows.go` |
| **Wi-Fi AP scan** (SSID/BSSID/channel/signal for all visible APs) | New AP detection (rogue AP IoC per RITICS/NCSC) | P1 | `net_wifi_linux.go` |
| **mtr-style hop-level tracing** (raw ICMP TTL-exceeded) | Congestion localisation on DEGRADED transition | P1 | `net_mtr.go` |
| **Broadcast/multicast top-talker snapshot** | ARP storm / DHCP storm / segment congestion (TU Munich 2024) | P2 | `net_bcast.go` (gopacket AF_PACKET, Linux) |
| **MTU / PMTUD probe** | Silent black-holes on GRE/WireGuard tunnels | P2 | Future |
| **BGP route table** (via quagga/bird socket) | Route leaks on multi-homed sites | P3 | Future |

### 3.2 Endpoint / OS Health

> **All P0 and P1 items implemented in v2 Phase C3** via `os_health_linux.go` / `os_health_windows.go` — **eliminating the node_exporter requirement**.

| Missing Check | Industry Basis | Priority | v2 File |
|---|---|---|---|
| **CPU / memory / disk usage** | RITICS guidance: "High CPU usage" is an IoC indicator | P0 | `os_health_*.go` |
| **Uptime / last reboot timestamp** | PLC and server unexpected reboots = IoC | P0 | `os_health_*.go` |
| **Logged-in users** (who / wtmp) | Unexpected sessions = lateral movement | P1 | `os_health_linux.go` |
| **Listening port snapshot** (ss -tlnp) | New listener = potential compromise or misconfiguration | P1 | `os_ports.go` |
| **Systemd unit failures** | Service crash silent without monitoring | P1 | `os_processes.go` |
| **Docker container status** | Containerised services invisible otherwise | P1 | `os_processes.go` |
| **TLS certificate expiry** | Avoids surprise outages | P1 | `tls_check.go` |
| **Pending OS security updates** | Patch posture hygiene | P2 | Future |
| **SMART disk health** | Silent disk failures on long-running nodes | P2 | Future |
| **auditd / Windows Event log tail** | Process creation, privilege escalation (RITICS Appendix A) | P2 | Future |

### 3.3 OT / Industrial Device Checks

> **Safety rule (IEC 62443 / RITICS):** All OT checks must be **read-only**, **rate-limited to 1 request per collection cycle**, and must **not write** to any PLC register or coil.

| Missing Check | Protocol | Industry Basis | Priority | v2 File |
|---|---|---|---|---|
| **SNMP v2c/v3 GET** (sysDescr, ifOperStatus, CPU OID) | SNMP UDP/161 | Standard for all managed network devices | P0 | `ot_snmp.go` |
| **Modbus TCP FC03 read** (holding registers) | Modbus TCP/502 | PLC/HMI alive + data point; Ollila 2024 | P1 | `ot_modbus.go` |
| **Modbus TCP FC01 read** (coil status — read-only) | Modbus TCP/502 | PLC discrete input health | P1 | `ot_modbus.go` |
| **Siemens S7 / ISO-TSAP connect** | TCP/102 | S7-300/400/1200/1500 reachability | P1 | `ot_s7.go` |
| **BACnet WhoIs** broadcast | BACnet UDP/47808 | Building automation device discovery | P2 | Future |
| **OPC-UA browse / read** | OPC-UA TCP/4840 | SCADA historian / data plane health | P2 | Future |
| **IPMI / Redfish GET** | HTTP/443 or IPMI UDP/623 | Server OOB health without OS agent | P2 | Future |
| **EtherNet/IP** (CIP identity object) | UDP/44818 | Allen-Bradley PLC reachability | P3 | Future |
| **DNP3 data link status** | TCP/20000 | SCADA RTU health (power/water utilities) | P3 | Future |

### 3.4 WAN Checks

| Missing Check | Why It Matters | Priority | v2 File |
|---|---|---|---|
| **Public IP** (`api.ipify.org` or self-hosted) | Confirms internet egress; detects NAT failover | P0 | `net_wan.go` |
| **Latency to Cloudflare (1.1.1.1) + Google (8.8.8.8)** | Absolute WAN baseline | P0 | `net_wan.go` |
| **HTTP(S) to configured external URL** | DNS + routing + TLS full stack test | P1 | `net_wan.go` |
| **Download throughput probe** (timed GET of fixed payload) | Bandwidth regression | P2 | Future |
| **RIPE Atlas / BGP looking glass** (via REST API) | ISP route changes from collector's AS | P3 | Future |

---

## 4. Language Assessment: Keep Go

**Verdict: Keep Go. Extend it.**

Go is correct for this agent because:

- **Single static binary** — zero runtime dependency, trivially deployable via `scp` or a service manager
- **Cross-compilation** is first-class (`GOOS=windows GOARCH=amd64 go build`)
- **Stdlib** covers 80%: `net`, `os/exec`, `crypto`, `encoding/json`, `syscall`
- **Goroutines** let every check run concurrently without thread pool overhead
- **Low footprint** — suitable for Raspberry Pi, VMs, and Windows Server Core

External libraries needed for v2 (see `COLLECTOR-V2-REFACTOR.md` Section 8 for full go.mod):

| Need | Library | License |
|---|---|---|
| OTLP/gRPC export | `go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc` | Apache-2 |
| ICMP raw socket | `golang.org/x/net/icmp` | BSD |
| SNMP v2c/v3 | `github.com/gosnmp/gosnmp` | BSD-2 |
| Modbus TCP | `github.com/things-labs/go-modbus` | MIT |
| WireGuard wg-ctrl | `golang.zx2c4.com/wireguard/wgctrl` | MIT |
| eBPF (Linux) | `github.com/cilium/ebpf` | MIT |
| Broadcast/multicast capture | `github.com/google/gopacket` | BSD-2 |
| SQLite (cold buffer) | `modernc.org/sqlite` | MIT |

---

## 5. Recommended File Structure

> **See [`COLLECTOR-V2-REFACTOR.md`](COLLECTOR-V2-REFACTOR.md) Section 7** for the full v2 file structure (38 files including Wi-Fi, mtr, broadcast/multicast). Below is the v1 starting point for reference.

```
collector/
├── main.go              # lifecycle, config, ticker loop  (existing → refactor)
├── checks.go            # DNS/HTTP/TCP/NTP/port           (existing → extend)
├── ping_linux.go        # OS ping wrapper                 (existing → keep)
├── ping_windows.go      # OS ping wrapper                 (existing → keep)
├── reexec_unix.go       # self-update re-exec             (existing → keep)
├── reexec_windows.go    # self-update re-exec             (existing → keep)
└── go.mod               # stdlib only today → 9 deps in v2 (adds gopacket)
```

---

## 6. Implementation Guide

> **The full implementation guide has moved to [`COLLECTOR-V2-REFACTOR.md`](COLLECTOR-V2-REFACTOR.md) Section 6.** That document contains complete Go function signatures, build tags, and cross-platform notes for all 18 new source files, including `net_wifi_linux.go`, `net_mtr.go`, and `net_bcast.go`.

---

## 7–10. Extended Check Plan Schema, Linux/Windows Matrix, OT Safety Rules, RITICS Mapping

> **These sections remain valid and are reproduced / extended in [`COLLECTOR-V2-REFACTOR.md`](COLLECTOR-V2-REFACTOR.md) Sections 9–11.** Refer to that document for the authoritative version.

---

## 11. References

- Wren project: "Combining active and passive network measurements to build scalable monitoring systems on the grid." ACM SIGMETRICS Performance Evaluation Review. https://dl.acm.org/doi/10.1145/773056.773061
- "Optimal positioning of active and passive monitoring devices." ACM CoNEXT 2005. https://dl.acm.org/doi/10.1145/1095921.1095932
- Cambridge Nprobe: "Multi-layer network monitoring and analysis." UCAM-CL-TR-571. https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-571.html
- Zabala, L. et al. "Optimality of a Network Monitoring Agent and Validation in a Real Environment." *Mathematics* 11(3):610, 2023. https://www.mdpi.com/2227-7390/11/3/610
- Ollila, T. "Overview for capabilities of OT network monitoring tools." Master's thesis, JAMK University, April 2024. https://www.theseus.fi/handle/10024/851535
- RITICS / NCSC ICS-COI. "How to log and monitor in ICS/OT Environments." 2024. https://ritics.org/wp-content/uploads/2024/08/How-to-log-and-monitor-in-ICS-OT-Environments.pdf
- IEC 62443 Industrial Cybersecurity Standard, sections 3-1 to 3-3.
- HertzBeat community: "How can we support agent/agentless monitoring and active/passive modes?" GitHub Discussions #2178, 2024. https://github.com/apache/hertzbeat/discussions/2178
- Pelkonen, T. et al. "Gorilla: A Fast, Scalable, In-Memory Time Series Database." VLDB 2015. http://www.vldb.org/pvldb/vol8/p1816-teller.pdf
- gopacket: "Google gopacket — Go packet processing library." https://github.com/google/gopacket
- IEEE 802.11k-2008 / 802.11v-2011: "Radio Resource Measurement" and "BSS Transition Management" — formal basis for Wi-Fi AP scan and roaming detection.
