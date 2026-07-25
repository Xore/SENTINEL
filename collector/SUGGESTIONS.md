# Collector – Assessment & Improvement Suggestions

## What the Current Collector Does

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
- Sends a **fast heartbeat ping** (lightweight, configurable cadence ~5–10 s) and a **slower sample push** (default 30 s)
- Supports **HMAC-authenticated self-update** over HTTP from the aggregator

## What It Is Missing (Gap Analysis)

### Network Health Checks

| Missing Check | Why It Matters |
|---|---|
| **Default gateway reachability** | Detects local routing failures before WAN |
| **Traceroute / hop latency** | Identifies congestion or flapping hops |
| **BGP/static route table dump** | Route changes go undetected |
| **WAN IP + ISP detection** | Detects failover / unexpected path changes |
| **DNS leak / upstream resolver check** | Critical for split-DNS / Pi-hole setups |
| **ICMP unreachables / packet loss %** | Current ping only reports up/rtt, no loss % |
| **Interface RX/TX counters & error rates** | Link degradation invisible without counters |
| **MTU / PMTUD check** | Silent black-holes on GRE/WireGuard tunnels |
| **WireGuard peer last-handshake age** | VPN tunnel silently dead detection |
| **VLAN / ARP table completeness** | L2 topology drift |

### Endpoint / OS Health Checks

| Missing Check | Why It Matters |
|---|---|
| **CPU / memory / disk usage** | Node overload invisible to aggregator |
| **Process health** (systemd unit state, Docker container status) | Service crash not visible |
| **Open listening ports** (ss/netstat snapshot) | New listeners = potential compromise |
| **Logged-in users** | Unexpected sessions |
| **Uptime / last reboot** | Silent reboot detection |
| **Pending OS updates count** | Patch posture |
| **Certificate expiry** (TLS of configured endpoints) | Avoids surprise outages |
| **SMART disk health** | Silent disk failures |

### OT / Industrial Device Checks

| Missing Check | Why It Matters |
|---|---|
| **Modbus TCP read** (register poll) | PLC/HMI alive check with data point |
| **Siemens S7 / ISO-TSAP connect** | S7 device reachability |
| **BACnet WhoIs** | Building automation discovery |
| **SNMP v1/v2c/v3 GET** | Network gear health (CPU, interfaces, OID poll) |
| **IPMI / Redfish** endpoint check | Server OOB health |
| **OPC-UA browse / read** | SCADA/OT data plane health |

### WAN Checks

| Missing Check | Why It Matters |
|---|---|
| **Public IP check** (e.g. api.ipify.org) | Confirms internet egress works |
| **Latency to well-known anchors** (1.1.1.1, 8.8.8.8, regional IXPs) | Absolute WAN baseline |
| **Download throughput probe** | Bandwidth regression |
| **HTTP(S) to external hostnames** | DNS + routing + TLS stack end-to-end |
| **BGP looking glass / RIPE Atlas** (optional, via API) | ISP route changes |

---

## Language Assessment: Keep Go or Switch?

**Verdict: Keep Go. Extend it.**

Go is the correct language for this agent. Reasons:

- **Single static binary** – zero runtime dependency, trivially deployable via `scp` or a service manager on Linux and Windows
- **Cross-compilation** is first-class (`GOOS=windows GOARCH=amd64 go build`)
- **Stdlib is large** – `net`, `os/exec`, `crypto`, `encoding/json` covers 80% of what is needed
- **Concurrency is cheap** – goroutines let every check run in parallel without thread pool overhead
- **Low resource footprint** – suitable for Raspberry Pi and embedded collectors

The only gaps where you need an external library:

| Need | Library |
|---|---|
| SNMP v2c/v3 | `github.com/gosnmp/gosnmp` |
| Modbus TCP | `github.com/things-go/go-modbus` |
| WireGuard wg-ctrl | `golang.zx2c4.com/wireguard/wgctrl` |
| ICMP (raw socket ping with loss %) | `golang.org/x/net/icmp` |
| Prometheus metrics export | `github.com/prometheus/client_golang` |

---

## Recommended Architecture for a Full Collector

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
├── net_routes.go        # route table dump, GW reachability (NEW)
├── net_wan.go           # public IP, WAN latency, BW probe (NEW)
├── net_wireguard.go     # wgctrl last-handshake, peer state (NEW)
├── net_icmp.go          # ICMP loss %, x/net/icmp          (NEW)
│
├── os_health.go         # CPU/mem/disk, uptime, users      (NEW)
├── os_processes.go      # systemd units, Docker containers (NEW)
├── os_ports.go          # listening port snapshot          (NEW)
│
├── ot_snmp.go           # SNMP GET, walk                   (NEW)
├── ot_modbus.go         # Modbus TCP register poll         (NEW)
├── ot_bacnet.go         # BACnet WhoIs / ReadProperty      (NEW)
│
├── tls_check.go         # cert expiry check                (NEW)
└── go.mod
```

Each new file follows the existing pattern: it exports a `collect*()` or `check*()` function returning `[]map[string]any` and gets wired into `pushSamples()` in `main.go`.

---

## Concrete Next Steps (Priority Order)

### 1. Interface Counters (Linux: `/proc/net/dev`, Windows: `Get-NetAdapterStatistics`)

```go
// net_interfaces.go
func collectInterfaceCounters() []map[string]any {
    // read /proc/net/dev on Linux
    // exec PowerShell Get-NetAdapterStatistics on Windows
    // return: name, rx_bytes, tx_bytes, rx_errors, tx_errors, rx_dropped
}
```

### 2. Default Gateway + Route Table

```go
// net_routes.go
func collectRoutes() []map[string]any {
    // Linux:   exec("ip", "route")
    // Windows: exec("route", "print")
    // Always ping the default gateway and report RTT
}
```

### 3. WAN / Public IP Check

```go
// net_wan.go
func collectWAN() map[string]any {
    // GET https://api.ipify.org?format=json  (or self-hosted echo endpoint)
    // Latency to 1.1.1.1, 8.8.8.8
    // Return: public_ip, isp (optional), latency_cloudflare_ms, latency_google_ms
}
```

### 4. ICMP Loss % (requires raw socket / root on Linux, admin on Windows)

```go
// net_icmp.go  – uses golang.org/x/net/icmp
func pingWithLoss(host string, count int) (up bool, rttMs float64, lossPercent float64)
```

Handle privilege escalation the same way `reexec_unix.go` already does.

### 5. SNMP GET for OT/network gear

```go
// ot_snmp.go  – uses github.com/gosnmp/gosnmp
func collectSNMP(targets []snmpTarget) []map[string]any {
    // Poll OIDs: sysDescr, ifOperStatus, ifInErrors, ifOutErrors
    // configurable community string, v2c or v3
}
```

### 6. WireGuard Peer Health

```go
// net_wireguard.go  – uses golang.zx2c4.com/wireguard/wgctrl
func collectWireGuard() []map[string]any {
    // For each peer: PublicKey, AllowedIPs, LastHandshakeTime, RxBytes, TxBytes
    // Flag peers where LastHandshakeTime > 3 minutes as DOWN
}
```

### 7. OS Health (CPU / Memory / Disk)

```go
// os_health.go
// Linux:   read /proc/stat, /proc/meminfo, /proc/mounts + statvfs
// Windows: exec PowerShell Get-CimInstance Win32_OperatingSystem
func collectOSHealth() map[string]any
```

### 8. TLS Certificate Expiry

```go
// tls_check.go
func checkCertExpiry(host string, daysWarn int) (ok bool, daysLeft int, detail string) {
    // tls.Dial → ConnectionState().PeerCertificates[0].NotAfter
}
```

---

## Check Plan Extension (aggregator-side config)

The existing `checkPlan` struct should grow to cover the new check types:

```json
{
  "targets":  [...],
  "services": [...],
  "ports":    [...],
  "snmp_targets": [
    { "name": "core-switch", "host": "10.0.0.1", "community": "public", "oids": ["1.3.6.1.2.1.1.1.0"] }
  ],
  "wan_checks": {
    "enabled": true,
    "public_ip_url": "https://api.ipify.org?format=json",
    "latency_targets": ["1.1.1.1", "8.8.8.8"]
  },
  "wireguard": { "enabled": true },
  "os_health":  { "enabled": true, "disk_paths": ["/", "/data"] },
  "modbus_targets": [
    { "name": "plc-01", "host": "10.100.0.5", "port": 502, "unit_id": 1, "registers": [{"address": 100, "count": 4}] }
  ]
}
```

---

## Linux vs Windows Agent Notes

| Concern | Linux | Windows |
|---|---|---|
| ICMP raw socket | needs `CAP_NET_RAW` or setuid | needs Admin (or `NETWORK SERVICE` with firewall rule) |
| Route table | `ip route` (iproute2) | `route print` or `Get-NetRoute` |
| Interface counters | `/proc/net/dev` | `Get-NetAdapterStatistics` (PowerShell) |
| WireGuard | `wgctrl` (kernel socket) | `wgctrl` (same, works on Win) |
| SNMP | same binary | same binary |
| Service status | `systemctl is-active` | `Get-Service` or SCM API |
| Docker | Docker socket `/var/run/docker.sock` | Named pipe `npipe:////./pipe/docker_engine` |
| Install as service | systemd unit file | `sc.exe create` or NSSM |

The existing Go build-tag pattern (`ping_linux.go` / `ping_windows.go`) is the right approach — extend it for `net_routes.go`, `net_interfaces.go`, and `os_health.go`.

---

## Summary

The existing collector is a **solid foundation**. Go is the right language — do not switch. The main gaps are:

1. No network counters / loss metrics
2. No WAN/public-IP awareness
3. No route table visibility
4. No WireGuard tunnel health
5. No OT protocol checks (SNMP, Modbus)
6. No OS resource health (CPU/mem/disk)
7. No TLS certificate expiry monitoring

All of these can be added as standalone `.go` files following the existing pattern, wired into `pushSamples()` and the `checkPlan` config schema. The aggregator-side only needs the new JSON fields and corresponding DB streams.
