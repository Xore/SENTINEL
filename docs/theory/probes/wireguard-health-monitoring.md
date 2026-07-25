# WireGuard Tunnel Health Monitoring
## Academic & Operational Research for `collector/checks/wireguard.go`

> **Status:** Research document — feeds into `collector/checks/wireguard.go`  
> **Priority:** High — WireGuard is a first-class check in this system. The challenge is detecting tunnel degradation *before* it becomes a full drop, since WireGuard's roaming and handshake behaviour creates monitoring edge cases that naive ping-based checks miss.

---

## 1. WireGuard Protocol Internals Relevant to Monitoring

WireGuard uses **Noise_IKpsk2** protocol for key exchange. The following timing constants (from the WireGuard whitepaper, Donenfeld 2017) are critical for correct monitoring:

| Constant | Value | Meaning |
|---|---|---|
| `REKEY_AFTER_TIME` | 180 seconds | Initiate new handshake after this time |
| `REJECT_AFTER_TIME` | 180 seconds | Reject sessions older than this |
| `REKEY_TIMEOUT` | 5 seconds | Time between handshake retries |
| `KEEPALIVE_TIMEOUT` | 10 seconds | Send keepalive if no data for this long |
| `REKEY_AFTER_MESSAGES` | 2^60 | Initiate rekey after this many messages |
| `REJECT_AFTER_MESSAGES` | 2^64 - 2^13 - 1 | Hard reject after this many messages |

**Key monitoring implication:** A healthy WireGuard tunnel's `latest handshake` should be **< 180 seconds** old if there is active traffic, or < `REKEY_AFTER_TIME + REKEY_TIMEOUT × retries` = ~3–5 minutes if idle. A handshake older than 3 minutes on an active tunnel is a degradation signal.

```go
// collector/checks/wireguard.go — handshake age thresholds
const (
    WGHandshakeFreshOK      = 180 * time.Second  // healthy: < REKEY_AFTER_TIME
    WGHandshakeSuspect      = 3 * time.Minute    // suspect: rekey in progress?
    WGHandshakeDegraded     = 5 * time.Minute    // degraded: multiple rekey failures
    WGHandshakeDown         = 15 * time.Minute   // down: no handshake for 15min
)
```

---

## 2. Reading WireGuard State from Go

The `golang.zx2c4.com/wireguard/wgctrl` library provides userspace access to the WireGuard kernel interface:

```go
// collector/checks/wireguard.go
package checks

import (
    "golang.zx2c4.com/wireguard/wgctrl"
    "golang.zx2c4.com/wireguard/wgctrl/wgtypes"
    "time"
)

type WGPeerMetrics struct {
    PublicKey          string
    Endpoint           string
    LastHandshakeAge   time.Duration  // time since last successful handshake
    HandshakeState     string         // OK / SUSPECT / DEGRADED / DOWN
    RxBytes            int64
    TxBytes            int64
    RxRate             float64        // bytes/s since last poll
    TxRate             float64        // bytes/s since last poll
    AllowedIPs         []string
}

func CollectWGMetrics(iface string) ([]WGPeerMetrics, error) {
    c, err := wgctrl.New()
    if err != nil {
        return nil, fmt.Errorf("wgctrl open: %w", err)
    }
    defer c.Close()

    dev, err := c.Device(iface)
    if err != nil {
        return nil, fmt.Errorf("wgctrl device %s: %w", iface, err)
    }

    metrics := make([]WGPeerMetrics, 0, len(dev.Peers))
    for _, peer := range dev.Peers {
        age := time.Since(peer.LastHandshakeTime)
        state := handshakeState(age, peer.LastHandshakeTime.IsZero())
        metrics = append(metrics, WGPeerMetrics{
            PublicKey:        peer.PublicKey.String()[:8] + "...", // truncate for logs
            Endpoint:         peer.Endpoint.String(),
            LastHandshakeAge: age,
            HandshakeState:   state,
            RxBytes:          peer.ReceiveBytes,
            TxBytes:          peer.TransmitBytes,
            AllowedIPs:       allowedIPStrings(peer.AllowedIPs),
        })
    }
    return metrics, nil
}

func handshakeState(age time.Duration, neverHandshaked bool) string {
    if neverHandshaked {
        return "NEVER_HANDSHAKED"  // peer configured but never connected
    }
    switch {
    case age < WGHandshakeFreshOK:   return "OK"
    case age < WGHandshakeSuspect:   return "SUSPECT"
    case age < WGHandshakeDegraded:  return "DEGRADED"
    default:                         return "DOWN"
    }
}
```

---

## 3. The Five WireGuard Failure Modes

WireGuard degrades in five distinct ways, each requiring a different detection strategy:

### Mode 1: Handshake Stall (Most Common)

**Symptom:** `latest handshake` age exceeds `REKEY_AFTER_TIME` but tunnel still passes traffic briefly.  
**Cause:** UDP hole punch failed after NAT mapping changed; firewall rule change; peer IP changed (roaming).  
**Detection:** Handshake age > `WGHandshakeSuspect` (3 min) **and** `last_handshake_age` is *increasing* monotonically (not refreshing).  
**Remediation:** `wg show` to confirm, then `wg set <iface> peer <pubkey> endpoint <new_ip>:<port>` or restart WG.

```go
// Stall detection: handshake age is increasing faster than 1s/s
// (i.e., no successful rekey is occurring)
func isHandshakeStalled(prev, curr WGPeerMetrics, elapsed time.Duration) bool {
    ageDelta := curr.LastHandshakeAge - prev.LastHandshakeAge
    // If handshake refreshed, ageDelta should be negative (age reset to ~0)
    // If stalled, ageDelta ≈ elapsed (age growing at wall-clock rate)
    return ageDelta > elapsed*9/10 && curr.LastHandshakeAge > WGHandshakeSuspect
}
```

### Mode 2: Clock Skew / NTP Failure

**Symptom:** Handshake initiates but peer rejects with silence; tunnel drops completely after 180s.  
**Cause:** System clock differs from peer by >1 minute. WireGuard timestamps are monotonic but the Noise handshake includes a TAI64N timestamp checked for replay prevention; large clock skew causes rejection.  
**Detection:** Tunnel goes from OK to NEVER_HANDSHAKED (handshake never succeeds) after a clock event (reboot, NTP failure).  
**Remediation:** Fix NTP. `timedatectl status` should show `NTP service: active` and `System clock synchronized: yes`.

```go
// Cross-check: if WG handshake fails AND NTP sync lost, clock skew is likely cause
// This should be added to the RCA DAG as NTP_FAILURE → SYM_WG_STALE
// (already documented in docs/rca-causal-inference.md)
```

### Mode 3: Silent Data Plane Failure

**Symptom:** Handshake is fresh (age < 180s) but data traffic is not flowing. Tunnel appears healthy but pings fail.  
**Cause:** Asymmetric routing change (return path broken); firewall blocks data but not handshake (different UDP ports); MTU mismatch causing silent data loss.  
**Detection:** Handshake OK **and** RxBytes/TxBytes flat for >2 collection cycles **and** ICMP through tunnel fails.  

```go
// Flatline detection: byte counters not moving despite active probe traffic
func isByteFlatline(prev, curr WGPeerMetrics, elapsed time.Duration) bool {
    if curr.HandshakeState != "OK" {
        return false // already alarming on handshake
    }
    rxDelta := curr.RxBytes - prev.RxBytes
    txDelta := curr.TxBytes - prev.TxBytes
    // If we sent probes (TxDelta > 0) but received nothing (RxDelta == 0)
    // for >2 cycles, silent data plane failure
    return txDelta > 0 && rxDelta == 0
}
```

### Mode 4: MTU Mismatch (Subtle, Common in WG over WAN)

**Symptom:** Small pings work, large transfers fail or are fragmented. p95 RTT normal, but TCP connections hang on large payloads.  
**Cause:** WireGuard adds 60 bytes of overhead (IPv4) or 80 bytes (IPv6) to each packet. If the path MTU is exactly 1500, WG-encapsulated 1420-byte payloads become 1480-byte packets that fit, but the inner traffic's MTU negotiation may not account for this.  
**Detection:** ICMP works, small TCP works, but p99 RTT of large TCP flows via eBPF is >> p95. Alternatively: `ping -M do -s 1400 <wg_peer>` succeeds but `ping -M do -s 1420 <wg_peer>` fails.  
**Recommended MTU:**

```
WireGuard MTU = Path MTU - 60 (IPv4) or - 80 (IPv6)
For 1500-byte path: WG interface MTU = 1420
For PPPoE path (1492 byte):  WG interface MTU = 1432 (IPv4) or 1412 (IPv6)
```

```go
// Automated MTU probe (add to collector/checks/wireguard.go)
// Send ICMP with DF bit set at increasing sizes to find PMTU
func ProbeMTU(target string) (int, error) {
    for size := 1400; size <= 1500; size += 10 {
        _, err := sendICMPDFBit(target, size)
        if err != nil {
            return size - 10, nil  // last size that worked
        }
    }
    return 1500, nil
}
```

### Mode 5: Roaming / Endpoint Change

**Symptom:** Mobile peer (phone, laptop) changes IP (roaming from WiFi to LTE). WireGuard automatically updates the peer endpoint on the server side, but the client-side `wg show` still shows the old endpoint briefly.  
**Detection:** `peer.Endpoint` changes between collection cycles. Not necessarily an error, but log it.  

```go
if prev.Endpoint != curr.Endpoint {
    log.Infof("WG peer %s endpoint roamed: %s → %s",
        curr.PublicKey, prev.Endpoint, curr.Endpoint)
    // Reset handshake age expectation — rekey will occur
}
```

---

## 4. Prometheus Metrics Schema for WireGuard

```
# HELP wg_peer_handshake_age_seconds Seconds since last successful WireGuard handshake
# TYPE wg_peer_handshake_age_seconds gauge
wg_peer_handshake_age_seconds{iface="wg0", peer="AbCdEf12..."} 45.2

# HELP wg_peer_rx_bytes_total Bytes received from WireGuard peer (counter)
# TYPE wg_peer_rx_bytes_total counter
wg_peer_rx_bytes_total{iface="wg0", peer="AbCdEf12..."} 1234567

# HELP wg_peer_tx_bytes_total Bytes transmitted to WireGuard peer (counter)
# TYPE wg_peer_tx_bytes_total counter
wg_peer_tx_bytes_total{iface="wg0", peer="AbCdEf12..."} 987654

# HELP wg_peer_state WireGuard peer health state (0=OK, 1=SUSPECT, 2=DEGRADED, 3=DOWN, 4=NEVER_HANDSHAKED)
# TYPE wg_peer_state gauge
wg_peer_state{iface="wg0", peer="AbCdEf12...", endpoint="1.2.3.4:51820"} 0

# HELP wg_peer_handshake_stalled WireGuard handshake not refreshing despite active traffic
# TYPE wg_peer_handshake_stalled gauge
wg_peer_handshake_stalled{iface="wg0", peer="AbCdEf12..."} 0

# HELP wg_peer_data_flatline WireGuard data plane silent despite fresh handshake
# TYPE wg_peer_data_flatline gauge
wg_peer_data_flatline{iface="wg0", peer="AbCdEf12..."} 0
```

---

## 5. Alerting Thresholds (Prometheus Alertmanager Rules)

```yaml
# Grafana / Alertmanager alert rules for WireGuard
groups:
  - name: wireguard
    rules:
      - alert: WireGuardHandshakeStale
        expr: wg_peer_handshake_age_seconds > 300
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "WireGuard handshake stale for {{ $labels.peer }}"
          description: "Last handshake {{ $value | humanizeDuration }} ago. Tunnel may be degraded."

      - alert: WireGuardTunnelDown
        expr: wg_peer_state == 3
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "WireGuard tunnel DOWN for {{ $labels.peer }}"
          description: "No handshake in 15+ minutes on {{ $labels.iface }}."

      - alert: WireGuardDataFlatline
        expr: wg_peer_data_flatline == 1
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "WireGuard data plane silent despite fresh handshake"
          description: "Possible MTU mismatch, asymmetric routing, or firewall blocking data UDP."

      - alert: WireGuardNeverHandshaked
        expr: wg_peer_state == 4
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "WireGuard peer never completed handshake"
          description: "Check NTP sync, firewall UDP {{ $labels.endpoint }} port, and peer config."
```

---

## 6. RCA DAG Integration

Add these edges to `monitor/rca/graph.py` (supplements `docs/rca-causal-inference.md`):

```python
# WireGuard-specific cause nodes
G.add_node("WG_NAT_CHANGE", node_type="cause",
           label="NAT mapping expired — WireGuard hole punch failed",
           prior=0.08,
           remediation="wg set <iface> peer <key> endpoint <new_ip>:<port>")
G.add_node("WG_MTU_MISMATCH", node_type="cause",
           label="WireGuard MTU mismatch — large packets silently dropped",
           prior=0.05,
           remediation="Set WG interface MTU to path_mtu - 60. Check: ip link show wg0.")
G.add_node("WG_ASYMMETRIC_ROUTE", node_type="cause",
           label="Asymmetric routing — WG return path broken",
           prior=0.03,
           remediation="Check routing table on both peers: ip route show. Verify WG AllowedIPs.")

# Symptom edges
G.add_edge("WG_NAT_CHANGE",        "SYM_WG_STALE",       {"p": 0.85})
G.add_edge("WG_NAT_CHANGE",        "SYM_WG_DATA_FLAT",   {"p": 0.70})
G.add_edge("WG_MTU_MISMATCH",      "SYM_WG_DATA_FLAT",   {"p": 0.90})
G.add_edge("WG_MTU_MISMATCH",      "SYM_RTT_HIGH",       {"p": 0.30})  # fragmentation adds latency
G.add_edge("WG_ASYMMETRIC_ROUTE",  "SYM_WG_DATA_FLAT",   {"p": 0.95})
G.add_edge("WG_ASYMMETRIC_ROUTE",  "SYM_LOSS_HIGH",      {"p": 0.80})
```

---

## 7. Implementation Checklist

| Item | File | Status |
|---|---|---|
| `wgctrl` peer state collection | `collector/checks/wireguard.go` | **Implement** |
| Handshake age thresholds (OK/SUSPECT/DEGRADED/DOWN) | `collector/checks/wireguard.go` | **Implement** |
| Handshake stall detection (age increasing monotonically) | `collector/checks/wireguard.go` | **Implement** |
| Silent data plane detection (byte flatline) | `collector/checks/wireguard.go` | **Implement** |
| MTU probe function | `collector/checks/wireguard.go` | **Add — optional but useful** |
| Endpoint roaming logging | `collector/checks/wireguard.go` | **Implement** |
| Prometheus metrics (5 metric schema above) | `collector/metrics.go` | **Add** |
| Alertmanager rules | `dashboard/alerts/wireguard.yaml` | **New file** |
| RCA DAG: 3 new WG cause nodes | `monitor/rca/graph.py` | **Add** |
| NTP_FAILURE → SYM_WG_STALE edge | `monitor/rca/graph.py` | See rca-causal-inference.md |

---

## References

1. Donenfeld, J.A. "WireGuard: Next Generation Kernel Network Tunnel." NDSS 2017. https://www.wireguard.com/papers/wireguard.pdf
2. Prometheus WireGuard Monitoring. how2.sh, 2026. https://how2.sh/posts/how-to-automate-vpn-reliability-baselines-in-platform-operations/
3. OneUptime. "Monitor WireGuard Tunnel Status on Talos Linux." 2026. https://oneuptime.com/blog/post/2026-03-03-monitor-wireguard-tunnel-status-on-talos-linux/view
4. LinuxGD. "Expert Guide to WireGuard Tuning in Linux." 2025. https://linuxgd.medium.com/expert-guide-to-wireguard-tuning-in-linux-21da74cb33f4
5. wgctrl-go — WireGuard control interface for Go. https://pkg.go.dev/golang.zx2c4.com/wireguard/wgctrl
