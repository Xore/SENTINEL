# Auvik feature reference (inspiration)

Captured 2026-07-24 from a live Auvik Network Management trial
(`xore.eu2.my.auvik.com`, site "Xore Headquarters") plus Auvik's public
documentation. This is a **reference of what Auvik does**, used to shape our own
probe's network-map and monitoring roadmap (see
[07-network-map-and-monitoring-roadmap.md](07-network-map-and-monitoring-roadmap.md)).
It is descriptive, not a spec to copy 1:1 — our probe stays passive-first,
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
    (Ethernet/WiFi/VLAN), parent device, negotiated speed, Connected To
    (e.g. "Port1 on firewall"), config details (IP / Access VLAN).
  - All Services (`/services`) — 29 rows: named service (AD, DNS, HTTP, HTTPS,
    FTP, BGP, Citrix, ILO…), check type (Port Status Check / Cloud Ping Check),
    # devices, Monitor / Don't Monitor toggle.
  - All Cloud Controllers / All Components / All Servers / All Endpoints / All
    Applications (`/cloudController`,`/components`,`/servers`,`/endpoints`,`/applications`).
- **All Alerts** (`/alerts`) — severity, status, alert name, detected-on, entity,
  description, related alert, dismissed, external ticket ID, dispatched, source.
  Buttons: Dismiss, Create Notifications, Pause Alerts, Export, View Paused.
  Time-range filtered.
- **Hardware Lifecycle** — Vendor Suggested Software (recommended firmware),
  Vendor Device Lifecycle Information (EOL/EOS), Device Contract Information
  (warranty/support contracts).
- **Documentation** — Notes (per-entity notes), Reports, **Configurations**
  (automatic device **config backups**, deployment-date versioned, diffable),
  Remote Tunnels.
- **Debug** — All Routes (`/routes`, 35 rows: device → destination → next hop →
  metric → gateway interface — a per-device routing table dump), All SNMP
  Pollers, Hardware Sensors.
- **Audit Log** — Remote Management (device, user, action, direction, status,
  cause), User Activity.
- **TrafficInsights** — NetFlow/IPFIX/sFlow traffic analysis (top apps, flows,
  geo, who/what/where, encrypted-traffic classification). Needs flow export set up.
- **Syslog** — Syslog Devices and message viewer.

Admin nav (`#admin/...`):

- **Discovery** (`/discovery/dashboard`) — Discovery Dashboard, Manage Devices,
  Manage Networks (approve subnets for scanning), Manage Credentials, Discovery
  Settings. Per-device probe matrix: **SNMP / Login / WMI / VMware / API**.
  Left rail auto-buckets devices by **role**: Unknown, Firewall, Router, Access
  Point, Server, Other. Prompts "Auvik needs device credentials to begin
  monitoring and mapping."
- **Integrations** (`/integrations/overview`) — PSA/ticketing/etc. connectors + API/webhooks.
- **Manage Alerts** (`/alerts/alerts`) — **45 preconfigured alerts** (V2 + legacy
  tables) with Alert Suppression, Notification Channels, Maintenance Windows.
  Each alert = name, severity, enabled, description, **entities applied to** (a
  Tag like "Network Device"/"Firewall" or "Collectors"), permission level.
  Create New Alert (dynamic, roll-up, delay to cut noise).
- **Manage Tags** (`/tags/tags`) — device tags: Firewall, Infrastructure Device,
  Network Device, Printer, UPS Device, Windows Server. Tags scope alerts & permissions.
- **Manage Users** (`/users/users`) — Users + Roles, per-user API key, Reset 2FA, invites.
- **Endpoint** (`/endpoint/agents`) — per-machine agent: network monitoring,
  inventory, remote support, command runner; Site Registration Key, Cloud Site
  Latency, Remote Support Settings.
- **Auvik Collectors** (`/virtualAppliances/overview`) — the collectors: unique
  ID, description, type (e.g. "Debian GNU/Linux 13"), IP(s), Connection
  (Connected), Approval (Approved), Post-NAT backup IP. Add/Approve/Reject.
- **Settings** (`/settings/company`) — org info, desired URL, timezone, daily
  alert-summary email, Support Access level (Read Only), **Theme Styles** (logo,
  favicon, light/dark colors for links, nav highlight, titles, sidebar,
  **map background**).

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
  router/switch=network icon; AP=Wi-Fi glyph; subnet=small cloud with CIDR; plus
  server / workstation / printer / phone / generic. **Status color**: green=up,
  red=down, gray=unreachable/unknown, amber=warning. Node label sits below.
- **Edge (connection) legend** — Layer 1 Wired (solid blue), Layer 1 Wireless
  (dotted blue), VPN (solid dark), Inferred Wired (solid gray), Inferred Wireless
  (dotted gray). Edges are curved béziers fanning out.
- **Map View modes**: Hybrid (default) / Layer 1 (physical) / Layer 2
  (VLAN/switching) / Layer 3 (routing).
- **Interactions**: hover a node → detail tooltip; click → the device's own
  dashboard; toolbar for layout / visibility / filter / export / settings; zoom /
  fit / fullscreen; **search the map** by `device name / device type / device
  status / device discovery status / vendor / network / interface name / IP /
  MAC / connection type / alert severity`. Alerts surface on the map.

### How Auvik builds it (discovery algorithm)

A combination of **SNMP, CDP, LLDP, FDP, ARP tables, MAC forwarding tables, VLAN
data, and routing tables**, plus CLI `show` commands:

- **Layer 1 (physical)** — LLDP / CDP / FDP (via SNMP MIBs + CLI) + switch
  forwarding tables → who is plugged into whom.
- **Layer 2 (switching)** — ARP tables, MAC/IP bindings, VLAN associations.
- **Layer 3 (routing)** — device routing tables + IP assignments → the routed
  hierarchy (Internet → firewall → subnets).
- **Inference** — where definitive adjacency is unknown, proprietary algorithms
  infer the edge (shown as the dotted/solid **Inferred** styles).

Sources:
[How Auvik discovers topology](https://support.auvik.com/hc/en-us/articles/202956414-How-does-Auvik-discover-network-topology-and-device-information),
[Network topology mapper](https://www.auvik.com/network-management-software/use-case/network-topology-mapper/),
[Network mapping software](https://www.auvik.com/network-management-software/network-mapping-software/).

## What maps cleanly onto our probe

We already collect most of the raw signals Auvik uses — the gap is **assembly +
device classification + a good renderer**, not new data collection:

| Auvik input | Our existing source |
|---|---|
| LLDP/CDP neighbours | `lldpd` + `/api/lldp`, `history.get_lldp_state()` |
| Routing tables / hops | traceroute → `/api/monitor/topology`, `/api/monitor/routes` |
| ARP / discovered hosts | nmap/ARP discovery → `/api/hosts`, `history.get_hosts()` |
| Wi-Fi APs | AP monitor → `/api/wifi/ap-monitor` |
| Interfaces / IPs / speeds | `/api/status` interfaces |
| Services per host | services catalog + scans |
| SNMP identity | `/api/snmp` |
| Per-device status (up/down/loss) | outage monitor `ping_samples` |
| Collector/node model | our multi-collector plan (task #36) mirrors Auvik collectors |

Deliberately **out of scope for us** (Auvik does them, we won't by default):
credential sweeps, WMI/vendor-API logins, config *push*, agentized command-runner
on endpoints, automatic subnet expansion. Our config/inventory stays passive and
read-only.
