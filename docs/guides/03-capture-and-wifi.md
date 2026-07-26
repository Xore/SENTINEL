# Wi-Fi health checks — v2 Collector

The v2 collector monitors Wi-Fi link quality and AP state using the system’s `iw`
tool (Linux) or `netsh` (Windows). No packet capture, no monitor mode, and no
dedicated capture interface are required.

> **Check modules:** `checks/net_wifi_linux.py`, `checks/net_wifi_windows.py`
> **Design reference:** [`docs/collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md) §6.2

---

## What the Wi-Fi checks measure

| Metric | Source | Notes |
|---|---|---|
| `wifi_rssi_dbm` | `iw dev <iface> link` | Signal strength in dBm; lower (more negative) = weaker |
| `wifi_link_speed_mbps` | `iw dev <iface> link` | Negotiated link rate |
| `wifi_ap_changes_total` | AP BSSID change detection | Roaming events; alert if unexpected AP appears |

---

## Configuration

Enable and configure Wi-Fi checks in `collector.yaml`:

```yaml
wifi:
  enabled: true
  interface: wlan0          # the interface connected to the monitored SSID
  scan_interval_s: 60       # how often to sample link stats
  ap_change_alert: true     # alert when BSSID changes (roaming / rogue AP)
```

To disable Wi-Fi checks entirely:

```yaml
wifi:
  enabled: false
```

---

## Linux: verify `iw` is working

```bash
# Show current link state
iw dev wlan0 link

# Expected output (when associated):
# Connected to aa:bb:cc:dd:ee:ff (on wlan0)
#   SSID: MyNetwork
#   signal: -55 dBm
#   rx bitrate: 144.4 MBit/s
```

If the output is `Not connected`, the interface is not associated —
the collector will emit `wifi_rssi_dbm = NaN` and log a warning.

### AP scan (optional, requires `CAP_NET_ADMIN` or root)

The collector can run `iw dev wlan0 scan` to detect nearby APs and flag
unexpected BSSIDs. This requires `CAP_NET_ADMIN`:

```bash
# Grant to binary
sudo setcap cap_net_raw,cap_net_admin+ep ./analyselaptop-collector

# Or in systemd unit:
# AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN
```

If `CAP_NET_ADMIN` is not granted, the collector skips AP scanning and logs a
structured warning — link stats (`wifi_rssi_dbm`, `wifi_link_speed_mbps`) are
still collected via `iw dev link`.

---

## Windows: verify `netsh` is working

```powershell
# Show current Wi-Fi interface state
netsh wlan show interfaces

# Expected output:
# Name                   : Wi-Fi
# Description            : Intel(R) Wi-Fi 6 AX201
# SSID                   : MyNetwork
# Signal                 : 75%
# Receive rate (Mbps)    : 144
```

The collector parses `Signal` as a percentage and converts to approximate dBm.
No elevated privileges are required on Windows for `netsh wlan show interfaces`.

---

## Broadcast / multicast top-talker (Phase C11)

The collector also captures broadcast and multicast frame rates on a wired or
wireless interface using `scapy.AsyncSniffer`. This is a separate check from
Wi-Fi link stats and is configured independently:

```yaml
bcast_mcast:
  enabled: true
  interface: eth0           # or wlan0 for wireless segment
  window_s: 30              # capture window per sample
  top_n: 10                 # top-N talkers to report
  interval_s: 300           # how often to run a capture window
```

Requires `CAP_NET_RAW`. See
[`docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md`](../tasks/RESEARCH-BCAST-MCAST-GOPACKET.md)
for the research validation task before deploying on Raspberry Pi.

---

## MTR hop-tracing (Phase C6)

The collector can trace the route to any configured target using raw ICMP
TTL-exceeded probing — no external `mtr` binary is required.

```yaml
mtr:
  enabled: true
  targets:
    - 8.8.8.8
    - 192.168.50.1
  max_hops: 30
  probes_per_hop: 3
  interval_s: 300
```

Requires `CAP_NET_RAW`. Metrics produced:

```
mtr_hop_rtt_ms{target, hop, hop_ip}
mtr_hop_loss_pct{target, hop, hop_ip}
```

---

## OT safety rules for active checks

All Wi-Fi and network checks in the v2 collector are **read-only and passive**
with respect to the monitored network:

- `iw dev link` — reads local driver state, sends nothing to the network
- `iw dev scan` — sends probe frames on the collector’s own interface only
- `scapy.AsyncSniffer` — passive receive only, zero injected frames
- MTR tracing — sends ICMP Echo to configured targets only; never to OT devices
  unless explicitly listed in `mtr.targets`

See [`01-design-and-safety.md`](01-design-and-safety.md) for the full OT rules
of engagement.
