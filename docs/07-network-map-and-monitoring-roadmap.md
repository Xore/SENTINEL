# Network map & monitoring roadmap (Auvik-inspired)

Companion to [06-auvik-feature-reference.md](06-auvik-feature-reference.md). Where
that file records *what Auvik does*, this file is *what we build and in what order*
— an Auvik-style live topology map and the monitoring around it, built entirely
from our probe's **existing, passive/safe-active data** (no credential sweeps, no
config push). Fits the delivery discipline already in [../ROADMAP.md](../ROADMAP.md)
and the phased multi-node plan (tasks #34→#35→#36).

The user chose (AskUserQuestion, 2026-07-24): **real data, live map** and
**map first, FE/BE split (#35) after**.

## Guiding constraints

- **Passive-first / read-only.** Everything on the map comes from data we already
  gather or can gather safely (LLDP, ARP/discovery, traceroute, Wi-Fi scan, SNMP
  read, ping). No writes to any device. See [01-design-and-safety.md](01-design-and-safety.md).
- **Wi-Fi-only box, no wired fallback** — no change touches the box's own network
  binding. Map work is pure app/API.
- **Degrade gracefully.** Missing signals → an *inferred* or *unknown* node/edge,
  never a crash or an empty map.

## Data model (the contract the frontend renders)

New backend endpoint **`GET /api/map`** returns one graph document:

```jsonc
{
  "updated": 1690000000,
  "nodes": [
    {
      "id": "192.168.50.32",          // stable key: IP, or mac:.. / subnet:.. / "internet"
      "label": "probe-01",
      "kind": "self|internet|wan-gateway|firewall|router|switch|ap|server|"
              + "workstation|printer|phone|iot|subnet|host|unknown",
      "status": "up|down|unreachable|unknown|warning",
      "ips": ["192.168.50.32"],
      "macs": ["aa:bb:.."],
      "vendor": "Ubiquiti",           // from OUI / SNMP sysDescr
      "subnet": "192.168.50.0/24",
      "confidence": "observed|inferred",
      "detail": { "services": [...], "snmp": {...}, "loss": 0.0, "rtt_ms": 3.1 }
    }
  ],
  "edges": [
    {
      "from": "192.168.50.1", "to": "192.168.50.32",
      "layer": "l1|l2|l3|vpn",
      "media": "wired|wireless",
      "confidence": "observed|inferred",
      "detail": { "via": "wifi0ap0", "local_port": "...", "speed": "1G" }
    }
  ],
  "subnets": [ { "cidr": "192.168.50.0/24", "role": "main|mgmt|wifi|guest", "count": 7 } ],
  "wan_gateways": ["192.168.50.1"]
}
```

The renderer keeps **node identity stable** across refreshes (status recolors in
place; nodes don't jump). Colors follow the *entity*, not rank.

## Phases

### Phase A — Backend graph assembler `/api/map` (task #37)

Merge existing sources into the node/edge model above. Reuse the trim/label logic
already in `/api/monitor/topology` (`_trim_to_wan`, `label_for`, `_is_internal_ip`,
`_INTERNAL_NETS`).

- **Nodes** from: own interfaces (`self`), traceroute hops + `wan_gateway`,
  `/api/lldp` neighbours, `/api/hosts` (ARP/discovery), `/api/wifi/ap-monitor`
  (APs), monitor targets. Dedup by IP↔MAC union-find so one device with several
  IPs/MACs is one node.
- **Subnets** derived from interface CIDRs + discovered-host networks; role guessed
  from name/VLAN/SSID association where known.
- **Edges**: L3 from traceroute adjacency (Internet→gateway→subnet→host); L1/L2
  wired from LLDP `local_port`/`Connected To`; L1 wireless from AP↔client Wi-Fi
  associations; everything else `confidence:"inferred"`.
- **Status** from the outage monitor's latest `ping_samples` / route_state
  (up/down/loss → color).
- Endpoint is **read-only and cached** (assemble from stored history, don't launch
  scans on request).

### Phase B — Frontend "Network Map" view (task #38)

New SPA section `#map` + sidebar nav entry (respect the AdminLTE shell + the
`nav button[data-view]` / `.view.active` / `#pageTitle` contract — see
[[adminlte-shell]]).

- **Hierarchical top-down layout** (Internet → firewall/WAN → subnet clouds →
  devices), computed in-browser (tidy-tree / layered layout — no external D3;
  small vendored or hand-rolled layout to keep the offline/no-CDN rule).
- SVG renderer: typed node icons + **status colors** (green/red/gray/amber),
  curved bézier edges, **connection legend** (L1 wired solid, L1 wireless dotted,
  VPN, inferred gray). Zoom / pan / fit / fullscreen.
- **Hover** → tooltip (IP/MAC/vendor/status/RTT/loss); **click** → reuse the
  existing **IP dossier** (task #5) as the node detail drawer.
- Auto-refresh on the dashboard's existing cadence; diff-in-place, no full redraw.

### Phase C — Device classification (task #39)

Infer `kind` for each node so icons/roles are meaningful:

- OUI vendor (MAC prefix table, vendored) → make/vendor.
- Open services (from scans/services catalog): 53→DNS/server, 80/443→server,
  9100→printer, 5060→phone, 161→SNMP-managed infra.
- SNMP `sysDescr`/`sysServices` where available → router/switch/AP/server.
- Role heuristics: default-gateway IP → firewall/router; LLDP capability bits;
  Wi-Fi AP list → AP; the box itself → self.
- Ship a manual override (a small tag store, mirroring Auvik's Manage Tags) so a
  user can correct a classification; persists in the shared JSON config.

### Phase D — Map view modes + search/filter (task #40)

- **View modes**: Hybrid (default) / Layer 1 / Layer 2 / Layer 3 — filter edges by
  `layer`, collapse/expand subnet groups.
- **Map search** over node fields (name, type, status, vendor, network, IP, MAC,
  connection type) with match highlight, matching Auvik's search modifiers.
- Filter by status / kind / subnet; download map as SVG/PNG.

### Phase E — Monitoring & inventory around the map (later)

Lower priority, mostly UI over data we already store:

- **Alerts on the map**: node badges from IDS + outage monitor; a small alerts
  panel (severity/entity/detected-on) modeled on Auvik's alert list. Reuse our
  existing alert stores rather than a new engine.
- **Inventory tables**: Devices / Interfaces / Services list views (sortable,
  "Connected To" column) generated from `/api/map` + existing endpoints.
- **Hardware/lifecycle-lite**: surface vendor + firmware/SNMP version where we can
  read it (no vendor contract data — that's Auvik-cloud-only).
- **TrafficInsights-lite**: only if flow export is ever added — explicitly *not*
  planned now.

## Explicitly excluded (Auvik does, we won't by default)

Credential sweeps / WMI / VMware / vendor-API logins; config **backup or push**;
endpoint agents with a command-runner; automatic subnet expansion/scanning without
approval; cloud-only lifecycle/warranty data; PSA/ticketing integrations. These
conflict with the passive/read-only safety posture and stay out unless explicitly
requested and gated.

## Relationship to the multi-node plan

The map is **per-collector aware from the start**: `/api/map` tags every node with
the collector that observed it (`local` on the standalone box), so when task #36
(multi-collector) lands, the same view narrows to one collector or unions all —
no rework. This mirrors Auvik's site/collector structure (see
[06-auvik-feature-reference.md](06-auvik-feature-reference.md) → Auvik Collectors).

## Task index

| Task | Phase | Summary |
|---|---|---|
| #37 | A | `/api/map` backend graph assembler (nodes/edges/subnets from existing data) |
| #38 | B | Network Map SPA view — hierarchical SVG renderer + legend + node detail |
| #39 | C | Device classification (OUI + services + SNMP + role heuristics) + manual tags |
| #40 | D | View modes (L1/L2/L3/Hybrid) + map search/filter/export |
| (E)  | E | Alerts-on-map, inventory tables, lifecycle-lite — later, low priority |
