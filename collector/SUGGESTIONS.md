# Collector – Assessment & Improvement Suggestions

> **Last updated:** 2026-07-25  
> **Scope:** Full review of the current Go collector, academic and industry research grounding, and a concrete roadmap for production-grade network + OT probe collection.

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

---

## 2. Academic & Industry Research Context

### 2.1 Active vs. Passive Monitoring (Foundational Principle)

Peer-reviewed work on scalable monitoring platforms (Wren project, ACM SIGMETRICS) demonstrates that neither purely active nor purely passive monitoring is sufficient alone:

- **Passive monitoring** (ARP table reads, interface sniffing, SPAN ports) is zero-impact on the network but blind to path-level failures and WAN state.
- **Active monitoring** (ICMP, TCP probes, SNMP polls) adds measurable but small traffic load and gives ground-truth reachability and latency data.
- The academic recommendation is **hybrid**: use passive data (topology, utilisation) to *steer* which active probes to run, avoiding blanket active scanning. This is called "topology-based steering" and significantly reduces probe overhead without sacrificing measurement accuracy.

> **Implication for this collector:** The current agent is already push-based (active). It should add passive interface-counter collection (`/proc/net/dev`) in parallel, so the aggregator can correlate active probe results against real link utilisation.

The Cambridge multi-layer Nprobe architecture (UCAM-CL-TR-571) further establishes that probes should capture only the minimal data needed per protocol layer, with full offline analysis at the aggregator. This justifies the current design of sending JSON rows rather than raw packet captures.

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
| NTP clock skew is critical for OT log correlation | NTP check already implemented; should add per-device offset threshold alerting |

The IEC 62443 standard (sections 3-1 to 3-3) governs component-level security in OT networks. **Monitoring must not disturb the control plane** — this rules out any SYN-scan-style active discovery. Only targeted, rate-limited Modbus reads (one request per cycle) and SNMP GETs are acceptable.

The RITICS/NCSC ICS-COI guidance (2024) provides the authoritative indicator list for OT network anomalies (see Appendix A below). The collector's check plan should alert on these:

- Unknown device appears in ARP table
- Modbus TCP traffic outside expected register range
- Controller uptime drop (reboot detected)
- PLC key switch position change (via SNMP OID or Modbus discrete input)
- Unexpected outbound connection from engineering workstation subnet

### 2.4 Agent Architecture Patterns

The MDP-based network monitoring agent model (Zabala et al., 2023, *Mathematics* 11(3):610, cited 3 times) shows that a **Markov Decision Process** approach to scheduling checks — prioritising checks with highest uncertainty — outperforms fixed-interval polling on commodity hardware. This is directly applicable: the aggregator could eventually return a `priority_hints` field in the check plan, telling the collector to re-probe recently-failed targets more aggressively.

The push-vs-pull debate in distributed monitoring (HertzBeat community discussion, 2024) confirms the current push-active design is the right choice for NAT-traversal scenarios: the agent initiates all connections, requiring no inbound firewall rules.

### 2.5 Programming Language Considerations

After reviewing Go, Python, Rust, and C for this use case:

| Language | Binary size | Cross-compile | OT lib ecosystem | Verdict |
|---|---|---|---|---|
| **Go** | ~8 MB static | First-class | Good (gosnmp, go-modbus) | ✅ **Keep** |
| Python | Runtime required | Hard to single-binary | Best (pymodbus, pysnmp) | ❌ Deployment cost too high |
| Rust | ~2 MB static | First-class | Immature OT libs | ⚠️ Future consideration |
| C | ~200 KB | Manual | libmodbus, net-snmp | ❌ Memory safety risk |

**Verdict: Keep Go.** The only scenario where switching would add value is if the collector needs to run on extremely resource-constrained embedded hardware (< 16 MB RAM), in which case Rust would be the alternative.

---

## 3. Gap Analysis

### 3.1 Network Health Checks

| Missing Check | Academic / Industry Basis | Priority |
|---|---|---|
| **Default gateway reachability + RTT** | Baseline for all routing problems | P0 |
| **ICMP packet loss %** (multi-packet) | Wren / CoNEXT – loss % more informative than binary up/down | P0 |
| **Interface RX/TX counters, errors, drops** | `/proc/net/dev`; link degradation before failure | P0 |
| **Route table dump** | Detect route injection / missing static routes | P1 |
| **WAN public IP + ISP** | Failover / unexpected path detection | P1 |
| **WAN latency anchors** (1.1.1.1, 8.8.8.8) | Absolute baseline, detect ISP degradation | P1 |
| **WireGuard peer last-handshake age** | VPN silently dead; common in split-tunnel setups | P1 |
| **DNS upstream check** (custom resolver vs. 8.8.8.8 delta) | DNS hijack / Pi-hole bypass detection | P1 |
| **MTU / PMTUD probe** | Silent black-holes on GRE/WireGuard tunnels | P2 |
| **Traceroute hop latency** (3 probes per hop) | Congestion localisation | P2 |
| **BGP route table** (via quagga/bird socket) | Route leaks on multi-homed sites | P3 |

### 3.2 Endpoint / OS Health

| Missing Check | Industry Basis | Priority |
|---|---|---|
| **CPU / memory / disk usage** | RITICS guidance: "High CPU usage" is an IoC indicator | P0 |
| **Uptime / last reboot timestamp** | PLC and server unexpected reboots = IoC | P0 |
| **Logged-in users** (who / wtmp) | Unexpected sessions = lateral movement | P1 |
| **Listening port snapshot** (ss -tlnp) | New listener = potential compromise or misconfiguration | P1 |
| **Systemd unit failures** | Service crash silent without monitoring | P1 |
| **Docker container status** | Containerised services invisible otherwise | P1 |
| **TLS certificate expiry** | Avoids surprise outages | P1 |
| **Pending OS security updates** | Patch posture hygiene | P2 |
| **SMART disk health** | Silent disk failures on long-running nodes | P2 |
| **auditd / Windows Event log tail** | Process creation, privilege escalation (RITICS Appendix A) | P2 |

### 3.3 OT / Industrial Device Checks

> **Safety rule (IEC 62443 / RITICS):** All OT checks must be **read-only**, **rate-limited to 1 request per collection cycle**, and must **not write** to any PLC register or coil.

| Missing Check | Protocol | Industry Basis | Priority |
|---|---|---|---|
| **SNMP v2c/v3 GET** (sysDescr, ifOperStatus, CPU OID) | SNMP UDP/161 | Standard for all managed network devices | P0 |
| **Modbus TCP FC03 read** (holding registers) | Modbus TCP/502 | PLC/HMI alive + data point; Ollila 2024 | P1 |
| **Modbus TCP FC01 read** (coil status — read-only) | Modbus TCP/502 | PLC discrete input health | P1 |
| **Siemens S7 / ISO-TSAP connect** | TCP/102 | S7-300/400/1200/1500 reachability | P1 |
| **BACnet WhoIs** broadcast | BACnet UDP/47808 | Building automation device discovery | P2 |
| **OPC-UA browse / read** | OPC-UA TCP/4840 | SCADA historian / data plane health | P2 |
| **IPMI / Redfish GET** | HTTP/443 or IPMI UDP/623 | Server OOB health without OS agent | P2 |
| **EtherNet/IP** (CIP identity object) | UDP/44818 | Allen-Bradley PLC reachability | P3 |
| **DNP3 data link status** | TCP/20000 | SCADA RTU health (power/water utilities) | P3 |

### 3.4 WAN Checks

| Missing Check | Why It Matters | Priority |
|---|---|---|
| **Public IP** (`api.ipify.org` or self-hosted) | Confirms internet egress; detects NAT failover | P0 |
| **Latency to Cloudflare (1.1.1.1) + Google (8.8.8.8)** | Absolute WAN baseline | P0 |
| **HTTP(S) to configured external URL** | DNS + routing + TLS full stack test | P1 |
| **Download throughput probe** (timed GET of fixed payload) | Bandwidth regression | P2 |
| **RIPE Atlas / BGP looking glass** (via REST API) | ISP route changes from collector's AS | P3 |

---

## 4. Language Assessment: Keep Go

**Verdict: Keep Go. Extend it.**

Go is correct for this agent because:

- **Single static binary** — zero runtime dependency, trivially deployable via `scp` or a service manager
- **Cross-compilation** is first-class (`GOOS=windows GOARCH=amd64 go build`)
- **Stdlib** covers 80%: `net`, `os/exec`, `crypto`, `encoding/json`, `syscall`
- **Goroutines** let every check run concurrently without thread pool overhead
- **Low footprint** — suitable for Raspberry Pi, VMs, and Windows Server Core

External libraries needed (minimal, all pure-Go):

| Need | Library | License |
|---|---|---|
| SNMP v2c/v3 | `github.com/gosnmp/gosnmp` | BSD-2 |
| Modbus TCP | `github.com/things-go/go-modbus` | MIT |
| WireGuard wg-ctrl | `golang.zx2c4.com/wireguard/wgctrl` | MIT |
| ICMP raw socket | `golang.org/x/net/icmp` | BSD |
| Prometheus metrics export | `github.com/prometheus/client_golang` | Apache-2 |

---

## 5. Recommended File Structure

```
collector/
├── main.go              # lifecycle, config, ticker loop  (existing)
├── checks.go            # DNS/HTTP/TCP/NTP/port           (existing)
├── ping_linux.go        # OS ping wrapper                 (existing)
├── ping_windows.go      # OS ping wrapper                 (existing)
├── reexec_unix.go       # self-update re-exec             (existing)
├── reexec_windows.go    # self-update re-exec             (existing)
│
├── net_interfaces.go    # interface counters, errors, MTU (NEW)
├── net_routes.go        # route table, GW reachability    (NEW)
├── net_wan.go           # public IP, WAN latency probes   (NEW)
├── net_wireguard.go     # wgctrl last-handshake, peers    (NEW)
├── net_icmp.go          # ICMP loss %, x/net/icmp         (NEW)
│
├── os_health.go         # CPU/mem/disk, uptime            (NEW — build-tagged)
├── os_health_linux.go   # /proc/stat, /proc/meminfo       (NEW)
├── os_health_windows.go # Get-CimInstance Win32_OS        (NEW)
├── os_processes.go      # systemd units, Docker containers(NEW)
├── os_ports.go          # ss/netstat listening snapshot   (NEW)
│
├── ot_snmp.go           # SNMP GET, walk (gosnmp)         (NEW)
├── ot_modbus.go         # Modbus TCP FC01/FC03 read-only  (NEW)
├── ot_s7.go             # Siemens ISO-TSAP connect check  (NEW)
├── ot_bacnet.go         # BACnet WhoIs / ReadProperty     (NEW)
│
├── tls_check.go         # cert expiry check               (NEW)
├── SUGGESTIONS.md       # this file
└── go.mod
```

---

## 6. Concrete Implementation Guide

### 6.1 Interface Counters (P0)

```go
// net_interfaces.go — Linux reads /proc/net/dev; Windows uses PowerShell
func collectInterfaceCounters() []map[string]any {
    // Linux: parse /proc/net/dev
    // Columns: iface | rx_bytes rx_packets rx_errs rx_drop ... | tx_bytes ...
    // Windows: exec PowerShell "Get-NetAdapterStatistics | ConvertTo-Json"
    // Return per-interface: rx_bytes, tx_bytes, rx_errors, tx_errors, rx_dropped, tx_dropped
}
```

Linux `/proc/net/dev` is available without any privilege escalation. Windows `Get-NetAdapterStatistics` requires no elevation either.

### 6.2 ICMP Loss % (P0)

```go
// net_icmp.go — uses golang.org/x/net/icmp
// Requires CAP_NET_RAW on Linux (same privilege path as reexec_unix.go already handles)
// Requires Administrator on Windows (document this in service install guide)
func pingWithLoss(host string, count int, timeoutMs int) (up bool, avgRttMs float64, lossPercent float64) {
    // Send `count` ICMP echo requests with sequence numbers
    // Collect replies within timeout window
    // lossPercent = (sent - received) / sent * 100
    // avgRttMs = mean of reply RTTs
}
```

Academic basis: binary up/down is insufficient — the Wren project showed that loss % and jitter are the leading indicators of path degradation before a link goes fully down.

### 6.3 Default Gateway + Route Table (P1)

```go
// net_routes.go
func collectRoutes() []map[string]any {
    // Linux:   exec("ip", "route") → parse "default via X.X.X.X dev ethN"
    // Windows: exec("route", "print", "-4") → parse 0.0.0.0 line
    // Always extract: destination, gateway, interface, metric
    // Then ping the default gateway address (using pingWithLoss above)
    // Return: gateway_ip, gateway_rtt_ms, gateway_loss_pct, route_count, routes[]
}
```

### 6.4 WAN Public IP + Latency (P1)

```go
// net_wan.go
func collectWAN(cfg wanConfig) map[string]any {
    // Step 1: GET cfg.PublicIPURL (default: https://api.ipify.org?format=json)
    // Parse {"ip":"1.2.3.4"} — confirms internet egress
    // Step 2: ping each cfg.LatencyTargets (["1.1.1.1","8.8.8.8"]) with loss %
    // Step 3: optional HTTP GET to cfg.ExternalURL — confirms DNS + TLS stack
    // Return: public_ip, latency_cf_ms, latency_google_ms, external_ok, tls_cert_days_left
}
```

### 6.5 WireGuard Peer Health (P1)

```go
// net_wireguard.go — uses golang.zx2c4.com/wireguard/wgctrl
func collectWireGuard() []map[string]any {
    // Open wgctrl.New() client
    // For each device: for each peer:
    //   - PublicKey (truncated for display)
    //   - AllowedIPs
    //   - LastHandshakeTime → age in seconds
    //   - RxBytes, TxBytes (delta from previous cycle)
    //   - up: LastHandshakeTime < 3 minutes (WireGuard keepalive default)
    // If wgctrl fails (no WireGuard interfaces) → return empty, no error
}
```

### 6.6 SNMP GET for OT/Network Gear (P0)

```go
// ot_snmp.go — uses github.com/gosnmp/gosnmp
// Recommended base OIDs:
//   sysDescr        1.3.6.1.2.1.1.1.0  — device identity
//   sysUpTime       1.3.6.1.2.1.1.3.0  — uptime (detect reboots)
//   sysName         1.3.6.1.2.1.1.5.0  — hostname
//   ifOperStatus    1.3.6.1.2.1.2.2.1.8.N — interface state
//   ifInErrors      1.3.6.1.2.1.2.2.1.14.N
//   ifOutErrors     1.3.6.1.2.1.2.2.1.20.N

func collectSNMP(targets []snmpTarget) []map[string]any {
    // For each target: gosnmp.Get(oids)
    // Support v2c (community string) and v3 (user/auth/priv)
    // Rate-limit: one SNMP GET per target per collection cycle
    // Return: name, host, sysDescr, sysUpTime, interface_states[]
}
```

Per RITICS/NCSC ICS-COI guidance: a `sysUpTime` drop back to near-zero is a **high-priority indicator** of an unexpected PLC/switch reboot.

### 6.7 Modbus TCP Read-Only Poll (P1)

```go
// ot_modbus.go — uses github.com/things-go/go-modbus
// SAFETY: FC03 (read holding registers) and FC01 (read coils) ONLY
// NEVER use FC05 (write single coil), FC06 (write register), FC16 (write multiple)
func collectModbus(targets []modbusTarget) []map[string]any {
    // For each target:
    //   client := modbus.NewClient(modbus.NewTCPClientProvider(host:port))
    //   data, err := client.ReadHoldingRegisters(unitID, address, count)
    //   Interpret as uint16 values; store raw + optional scaling factor from config
    // Return: name, host, unit_id, registers[], timestamp, ok, error
}

type modbusTarget struct {
    Name      string           `json:"name"`
    Host      string           `json:"host"`
    Port      int              `json:"port"`      // default 502
    UnitID    uint8            `json:"unit_id"`
    Registers []modbusRegister `json:"registers"`
    TimeoutMs int              `json:"timeout_ms"` // default 2000
}
type modbusRegister struct {
    Address uint16  `json:"address"`
    Count   uint16  `json:"count"`
    Scale   float64 `json:"scale"` // optional: raw * scale = engineering unit
    Label   string  `json:"label"`
}
```

### 6.8 OS Health (P0)

```go
// os_health_linux.go (build tag: //go:build linux)
func collectOSHealth() map[string]any {
    // CPU: parse /proc/stat (user+nice+system / total ticks) → usage %
    // Memory: parse /proc/meminfo (MemTotal, MemAvailable, SwapTotal, SwapFree)
    // Disk: for each configured path → syscall.Statfs → used_bytes, free_bytes, used_pct
    // Uptime: read /proc/uptime → uptime_seconds
    // Load average: read /proc/loadavg → load1, load5, load15
    // Users: exec("who") → count and list
}

// os_health_windows.go (build tag: //go:build windows)
func collectOSHealth() map[string]any {
    // exec PowerShell: "Get-CimInstance Win32_OperatingSystem | ConvertTo-Json"
    // Parse: FreePhysicalMemory, TotalVisibleMemorySize, LastBootUpTime
    // exec: "Get-PSDrive -PSProvider FileSystem | ConvertTo-Json"
    // Parse: Used, Free per drive letter
}
```

### 6.9 TLS Certificate Expiry (P1)

```go
// tls_check.go
func checkCertExpiry(host string, port int, daysWarnThreshold int) map[string]any {
    // net.DialTimeout("tcp", host:port, 5s)
    // tls.Client(conn, &tls.Config{ServerName: host, InsecureSkipVerify: false})
    // conn.Handshake()
    // cert := conn.ConnectionState().PeerCertificates[0]
    // daysLeft := time.Until(cert.NotAfter).Hours() / 24
    // Return: host, subject, issuer, not_after, days_left, ok: daysLeft > daysWarnThreshold
}
```

### 6.10 Listening Port Snapshot (P1)

```go
// os_ports.go
func collectListeningPorts() []map[string]any {
    // Linux:   exec("ss", "-tlnp") → parse LISTEN lines
    //          fields: proto, local_addr, local_port, pid, process_name
    // Windows: exec("netstat", "-ano") | filter LISTENING
    //          then cross-reference PID with Get-Process
    // Return: proto, port, address, pid, process — for change detection at aggregator
}
```

---

## 7. Extended Check Plan Schema

```json
{
  "targets":  [...],
  "services": [...],
  "ports":    [...],

  "snmp_targets": [
    {
      "name": "core-switch",
      "host": "10.0.0.1",
      "version": "2c",
      "community": "public",
      "oids": ["1.3.6.1.2.1.1.1.0", "1.3.6.1.2.1.1.3.0"]
    },
    {
      "name": "ups-01",
      "host": "10.0.0.5",
      "version": "3",
      "username": "monitor",
      "auth_protocol": "SHA",
      "auth_passphrase": "...",
      "priv_protocol": "AES",
      "priv_passphrase": "..."
    }
  ],

  "modbus_targets": [
    {
      "name": "plc-main",
      "host": "10.100.0.5",
      "port": 502,
      "unit_id": 1,
      "timeout_ms": 2000,
      "registers": [
        { "address": 100, "count": 4, "label": "production_counter" },
        { "address": 200, "count": 2, "label": "temperature_raw", "scale": 0.1 }
      ]
    }
  ],

  "wan_checks": {
    "enabled": true,
    "public_ip_url": "https://api.ipify.org?format=json",
    "latency_targets": ["1.1.1.1", "8.8.8.8", "9.9.9.9"],
    "external_url": "https://example.com/healthz"
  },

  "wireguard": {
    "enabled": true,
    "max_handshake_age_seconds": 180
  },

  "os_health": {
    "enabled": true,
    "disk_paths": ["/", "/data", "/var"],
    "disk_warn_pct": 85,
    "users_warn_count": 3
  },

  "tls_checks": [
    { "name": "traefik", "host": "proxy.internal", "port": 443, "warn_days": 30 },
    { "name": "aggregator", "host": "192.168.50.32", "port": 8088, "warn_days": 14 }
  ]
}
```

---

## 8. Linux vs. Windows Agent Matrix

| Concern | Linux | Windows |
|---|---|---|
| ICMP raw socket | `CAP_NET_RAW` (setcap or reexec as root) | Admin; `NETWORK SERVICE` with firewall rule |
| Interface counters | `/proc/net/dev` — no privilege | `Get-NetAdapterStatistics` — no privilege |
| Route table | `ip route` (iproute2) | `route print` or `Get-NetRoute` (PS) |
| CPU/memory | `/proc/stat`, `/proc/meminfo` | `Get-CimInstance Win32_OperatingSystem` |
| Disk | `syscall.Statfs` | `Get-PSDrive` or `WMI Win32_LogicalDisk` |
| Uptime | `/proc/uptime` | `(Get-Date) - (gcim Win32_OS).LastBootUpTime` |
| WireGuard | `wgctrl` kernel socket (root) | `wgctrl` (Admin) |
| SNMP | same Go binary | same Go binary |
| Service status | `systemctl is-active` | `Get-Service` or SCM API |
| Docker | `/var/run/docker.sock` | `npipe:////./pipe/docker_engine` |
| Listening ports | `ss -tlnp` | `netstat -ano` |
| Install as service | systemd unit file | `sc.exe create` or NSSM |
| Log forwarding (OT) | rsyslog / auditd | WEF + WEC chain |

The existing Go build-tag pattern (`ping_linux.go` / `ping_windows.go`) must be extended to `os_health_linux.go` / `os_health_windows.go` and `net_routes_linux.go` / `net_routes_windows.go`.

---

## 9. OT Safety Rules (Non-Negotiable)

Based on IEC 62443, RITICS/NCSC ICS-COI 2024 guidance, and Ollila 2024 thesis:

1. **Never write to OT devices** — only FC01 (read coils), FC02 (read discrete inputs), FC03 (read holding registers), FC04 (read input registers) are permitted.
2. **Rate-limit all OT probes** — maximum 1 request per device per collection cycle (default 30 s). OT devices have limited TCP connection tables.
3. **Respect zone/conduit topology** (IEC 62443-3-3) — the collector must not bridge traffic between Purdue levels. Deploy one collector per zone.
4. **No broadcast scanning** — do not send ARP broadcasts on OT VLANs; rely only on the existing ARP/neighbour table passively populated by the OS.
5. **NTP alignment** — OT log correlation requires all collectors to be NTP-synchronised to the same stratum-1/2 source. The existing NTP check should validate this offset is < 1 second.
6. **Alert on unexpected reboots** — `sysUpTime` via SNMP dropping near zero or `uptime` from Modbus reset counter is a **high-priority IoC** per RITICS Appendix A.

---

## 10. RITICS/NCSC Indicator Checklist (Appendix A Mapping)

The following RITICS indicators should map directly to collector checks:

| RITICS Indicator | Collector Check | Stream |
|---|---|---|
| Unknown device on network | ARP table new entry (aggregator diff) | `neighbours` |
| Unknown IP address | ARP + DNS reverse lookup | `neighbours` |
| Unexpected ARP broadcasting | ARP count spike (aggregator rate) | `neighbours` |
| Detection of port scanning | Listening port change | `port_snapshot` |
| Communications outside specification | Modbus register out of expected range | `modbus_checks` |
| Controller uptime drop | SNMP sysUpTime near-zero | `snmp_checks` |
| PLC key switch position change | Modbus discrete input (configurable) | `modbus_checks` |
| High CPU usage | OS health CPU % threshold | `os_health` |
| Unexpected process started | Listening port new entry | `port_snapshot` |
| WAN path change | Public IP change between cycles | `wan_checks` |
| VPN tunnel dead | WireGuard handshake age > 3 min | `wireguard` |
| Certificate expiry imminent | TLS days_left < warn_days | `tls_checks` |

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
