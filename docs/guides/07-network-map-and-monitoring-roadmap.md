# Network map & monitoring roadmap (Auvik-inspired)

Companion to [06-auvik-feature-reference.md](06-auvik-feature-reference.md). Where
that file records *what Auvik does*, this file is *what we build and in what order*
— an Auvik-style live topology map and the monitoring around it, built entirely
from our probe's **existing, passive/safe-active data** (no credential sweeps, no
config push). Fits the delivery discipline already in [`../../ROADMAP.md`](../../ROADMAP.md)
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
      "id": "192.168.50.32",
      "label": "probe-01",
      "kind": "self|internet|wan-gateway|firewall|router|switch|ap|server|workstation|printer|phone|iot|subnet|host|unknown",
      "status": "up|down|unreachable|unknown|warning",
      "ips": ["192.168.50.32"],
      "macs": ["aa:bb:.."],
      "vendor": "Ubiquiti",
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

## Phases

### Phase A — Backend graph assembler `/api/map` (task #37)

Merge existing sources into the node/edge model above. Reuse the trim/label logic
already in `/api/monitor/topology`.

### Phase B — Frontend "Network Map" view (task #38)

New SPA section `#map` + sidebar nav entry. **Hierarchical top-down layout**
(Internet → firewall/WAN → subnet clouds → devices), computed in-browser.
SVG renderer: typed node icons + **status colors** (green/red/gray/amber),
curved bézier edges, **connection legend**. Auto-refresh on the dashboard's
existing cadence; diff-in-place, no full redraw.

### Phase C — Device classification (task #39)

Infer `kind` for each node:

- OUI vendor (MAC prefix table, vendored) → make/vendor.
- Open services (from scans/services catalog): 53→DNS, 80/443→server, 9100→printer, etc.
- SNMP `sysDescr`/`sysServices` where available.
- Role heuristics: default-gateway IP → firewall/router; LLDP capability bits.
- Manual override (small tag store, mirroring Auvik's Manage Tags).

### Phase D — Map view modes + search/filter (task #40)

- **View modes**: Hybrid / Layer 1 / Layer 2 / Layer 3 — filter edges by `layer`.
- **Map search** over node fields (name, type, status, vendor, network, IP, MAC).
- Filter by status / kind / subnet; download map as SVG/PNG.

### Phase E — Monitoring & inventory around the map (later)

Lower priority: alerts on the map, inventory tables, hardware/lifecycle-lite.

## Relationship to the multi-node plan

The map is **per-collector aware from the start**: `/api/map` tags every node with
the collector that observed it (`local` on the standalone box). Task #36's scoped
view builds on that — each enabled collector's pushed `neighbours` stream is woven
into `/api/map` as collector-tagged device nodes.

This mirrors Auvik's site/collector structure (see
[06-auvik-feature-reference.md](06-auvik-feature-reference.md) → Auvik Collectors).

## Task index

| Task | Phase | Summary |
|---|---|---|
| #37 | A | `/api/map` backend graph assembler (nodes/edges/subnets from existing data) |
| #38 | B | Network Map SPA view — hierarchical SVG renderer + legend + node detail |
| #39 | C | Device classification (OUI + services + SNMP + role heuristics) + manual tags |
| #40 | D | View modes (L1/L2/L3/Hybrid) + map search/filter/export |
| (E)  | E | Alerts-on-map, inventory tables, lifecycle-lite — later, low priority |
