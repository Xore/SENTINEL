# Auvik feature reference (inspiration)

Captured 2026-07-24 from a live Auvik Network Management trial
(`xore.eu2.my.auvik.com`, site "Xore Headquarters") plus Auvik's public
documentation. This is a **reference of what Auvik does**, used to shape our own
collector's network-map and monitoring roadmap (see
[07-network-map-and-monitoring-roadmap.md](07-network-map-and-monitoring-roadmap.md)).
It is descriptive, not a spec to copy 1:1 — our collector stays passive-first,
read-only and safety-gated (see [01-design-and-safety.md](01-design-and-safety.md)).

## The product in one line

Install a **collector** on the LAN; it auto-discovers everything with an IP,
draws a live **physical + logical topology map**, and continuously monitors
device/interface health, config, and traffic — with a library of preconfigured
alerts. MSP-shaped: an org root aggregates many **sites**, each site has one or
more collectors.

## Navigation map (every page observed)

Per-site nav (`#entity/root/...`) — the network map is a **persistent panel
pinned above every page in the site**, not a separate page.

- **Site Dashboard** (`/dashboard`) — the map + cards: Top Device Usage, Open
  Alerts (Emergency/Critical/Warning/Informational/Paused), Component Statuses
  (OK/Degraded/Failed), Online Network Elements (`3 of 3`), Detected
  Misconfigurations, Top Device Utilization (CPU/mem/storage), All Internet
  Connections.
- **Inventory**
  - All Networks (`/networks`) — subnet, type (Routed Network), # devices, **scan
    status** (Awaiting Approval / Scan / Don't Scan). Each subnet drills into its
    own dashboard. Subnets carry role labels: `(Main)`, `(Mgmt)`, `(WiFi)`.
  - All Devices (`/devices`) — status (Up/Down/Unreachable), name, **type**, make
    & model (vendor), MAC(s), IP(s), network(s), **Connected To** (uplink device
    "through" an interface — the L1/L2 edge), serial number.
  - All Interfaces (`/interfaces`) — 272 rows: admin/oper status, name, MAC, type
    (Ethernet/WiFi/VLAN), parent device, negotiated speed, Connected To, config details.
  - All Services (`/services`) — named service (AD, DNS, HTTP, HTTPS, FTP, BGP,
    Citrix, ILO…), check type, # devices, Monitor / Don't Monitor toggle.
- **All Alerts** (`/alerts`) — severity, status, alert name, detected-on, entity,
  description, related alert, dismissed, external ticket ID, dispatched, source.
- **Hardware Lifecycle** — Vendor Suggested Software (recommended firmware),
  Vendor Device Lifecycle Information (EOL/EOS), Device Contract Information.
- **Documentation** — Notes, Reports, **Configurations** (automatic device
  **config backups**, deployment-date versioned, diffable), Remote Tunnels.
- **Debug** — All Routes (device → destination → next hop → metric → gateway
  interface), All SNMP Pollers, Hardware Sensors.
- **TrafficInsights** — NetFlow/IPFIX/sFlow traffic analysis.
- **Syslog** — Syslog Devices and message viewer.

Admin nav (`#admin/...`):

- **Discovery** — Discovery Dashboard, Manage Devices, Manage Networks (approve
  subnets for scanning), Manage Credentials, Discovery Settings. Per-device probe
  matrix: **SNMP / Login / WMI / VMware / API**.
- **Manage Alerts** — **45 preconfigured alerts** with Alert Suppression,
  Notification Channels, Maintenance Windows.
- **Manage Tags** — device tags: Firewall, Infrastructure Device, Network Device,
  Printer, UPS Device, Windows Server.
- **Auvik Collectors** — the collectors: unique ID, description, type, IP(s),
  Connection (Connected), Approval (Approved), Post-NAT backup IP.

## The network map (the headline feature)

Layout — a **top-down hierarchical tree**:

```
Internet (cloud)
   │  Layer-1 wired (solid blue)
firewall (red circle, flame/shield icon)
   ├── 10.0.255.0/24  (subnet cloud, CIDR label)
   ├── 172.31.0.0/24 (Mgmt)
   ├── 192.168.42.0/24
   └── 192.168.50.0/24 (WiFi)
          └── U6Enterprise (AP) ── devices (dashed = wireless) …
```

- **Node types → icon + status color.** Internet=cloud; firewall=red flame;
  router/switch=network icon; AP=Wi-Fi glyph; subnet=small cloud with CIDR.
  **Status color**: green=up, red=down, gray=unreachable/unknown, amber=warning.
- **Edge (connection) legend** — Layer 1 Wired (solid blue), Layer 1 Wireless
  (dotted blue), VPN (solid dark), Inferred Wired (solid gray), Inferred Wireless
  (dotted gray).
- **Map View modes**: Hybrid (default) / Layer 1 / Layer 2 / Layer 3.

### How Auvik builds it (discovery algorithm)

A combination of **SNMP, CDP, LLDP, FDP, ARP tables, MAC forwarding tables, VLAN
data, and routing tables**, plus CLI `show` commands.

## What maps onto our v2 collector

The v2 collector already produces or will produce most of the raw signals Auvik
uses. The gap is **assembly + device classification + a hub-side renderer**,
not new data collection:

| Auvik input | v2 collector source |
|---|---|
| SNMP identity / interface table | `checks/net_snmp.py` — `snmp_sysuptime_seconds`, `snmp_if_oper_status{ifindex}` |
| ARP / discovered hosts | `checks/net_arp_watch.py` — `arp_table_size`, `arp_new_entry_total` |
| Wi-Fi APs / RSSI | `checks/net_wifi_linux.py` — `wifi_rssi_dbm`, `wifi_ap_changes_total` |
| Per-device reachability (up/down/loss) | `checks/net_icmp.py` — `icmp_rtt_ms`, `icmp_loss_pct` |
| Routing hops / path quality | `checks/net_mtr.py` — `mtr_hop_rtt_ms{hop,hop_ip}`, `mtr_hop_loss_pct` |
| TCP service reachability | `checks/net_tcp.py` — `tcp_connect_ms`, `tcp_connect_ok` |
| HTTP service health | `checks/net_http.py` — `http_response_ms`, `http_status_code` |
| Top broadcast/multicast talkers | `checks/net_bcast.py` (Phase C11) — `bcast_top_talker_pkts_total` |
| Host CPU/mem/disk | `os_health/linux.py` — `host_cpu_usage_pct`, `host_mem_available_bytes` |
| Collector node model | `collector_id` + `site_id` labels on all metrics; hub enrolment API |

Deliberately **out of scope**: credential sweeps, WMI/vendor-API logins,
config push, agentized command-runner on endpoints, automatic subnet expansion.
