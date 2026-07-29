# Network map & monitoring roadmap (Auvik-inspired)

Companion to [06-auvik-feature-reference.md](06-auvik-feature-reference.md). Where
that file records *what Auvik does*, this file is *what we build and in what order*
— an Auvik-style live topology map and the monitoring around it, built entirely
from the v2 collector's **passive/safe-active OTLP metrics** (no credential sweeps,
no config push). Fits the delivery discipline already in
[`../collector/ROADMAP.md`](../collector/ROADMAP.md).

## Guiding constraints

- **Passive-first / read-only.** Everything on the map comes from metrics the v2
  collector already emits or can emit safely (ARP watch, ICMP reachability, MTR
  hops, Wi-Fi scan, SNMP read). No writes to any device.
  See [01-design-and-safety.md](01-design-and-safety.md).
- **Degrade gracefully.** Missing signals → an *inferred* or *unknown* node/edge,
  never a crash or an empty map.
- **Hub-side assembly.** The v2 collector emits flat OTLP metrics. The hub ingest
  service (`hub/ingest/`) assembles the topology graph from those metrics and
  serves it via the hub REST API.

## Data model (the contract the hub frontend renders)

Hub endpoint **`GET /api/v2/map`** returns one graph document:

```jsonc
{
  "updated": 1690000000,
  "nodes": [
    {
      "id": "192.168.50.32",
      "label": "collector-01",
      "kind": "self|internet|wan-gateway|firewall|router|switch|ap|server|workstation|printer|phone|iot|subnet|host|unknown",
      "status": "up|down|unreachable|unknown|warning",
      "ips": ["192.168.50.32"],
      "macs": ["aa:bb:.."],
      "vendor": "Ubiquiti",
      "subnet": "192.168.50.0/24",
      "collector_id": "site-a-collector-01",
      "confidence": "observed|inferred",
      "detail": { "services": [], "snmp": {}, "loss_pct": 0.0, "rtt_ms": 3.1 }
    }
  ],
  "edges": [
    {
      "from": "192.168.50.1", "to": "192.168.50.32",
      "layer": "l1|l2|l3|vpn",
      "media": "wired|wireless",
      "confidence": "observed|inferred",
      "detail": { "via": "wifi0ap0", "hop": 1, "speed": "1G" }
    }
  ],
  "subnets": [ { "cidr": "192.168.50.0/24", "role": "main|mgmt|wifi|guest", "count": 7 } ],
  "wan_gateways": ["192.168.50.1"]
}
```

### OTLP metric sources per graph element

| Graph element | v2 collector metric |
|---|---|
| Host reachability / status | `icmp_rtt_ms`, `icmp_loss_pct` (Phase C2) |
| ARP table / host discovery | `arp_table_size`, `arp_new_entry_total` (Phase C4) |
| Routing hops / L3 edges | `mtr_hop_rtt_ms{hop,hop_ip}`, `mtr_hop_loss_pct` (Phase C5) |
| TCP service detection | `tcp_connect_ok{port}`, `tcp_connect_ms` (Phase C6) |
| HTTP service health | `http_response_ms`, `http_status_code` (Phase C7) |
| SNMP identity / vendor | `snmp_sysuptime_seconds`, `snmp_if_oper_status` (Phase C8) |
| Wi-Fi AP / RSSI | `wifi_rssi_dbm`, `wifi_ap_changes_total` (Phase C9) |
| Broadcast/multicast talkers | `bcast_top_talker_pkts_total` (Phase C11) |
| Collector node identity | `collector_id`, `site_id` labels on all metrics |

## Build phases

### Phase A — Hub graph assembler `GET /api/v2/map`

Hub ingest service consumes OTLP metric streams from enrolled collectors and
assembles the node/edge model above. ARP watch metrics seed the host list;
ICMP metrics drive `status`; MTR hop metrics build L3 edges; SNMP metrics
provide vendor/interface detail.

### Phase B — SvelteKit "Network Map" view

New route `/map` in the hub SvelteKit frontend. **Hierarchical top-down layout**
(Internet → WAN gateway → subnet clouds → devices), computed in-browser from
`GET /api/v2/map`. SVG renderer: typed node icons + **status colors**
(green/red/gray/amber), curved bézier edges, **connection legend**.
Auto-refresh on a configurable interval; diff-in-place, no full redraw.

### Phase C — Device classification

Infer `kind` for each node at hub ingest time:

- OUI vendor (MAC prefix table, vendored in hub) → `vendor` field.
- Open TCP services: 53 → DNS, 80/443 → server, 9100 → printer, etc.
- SNMP `sysDescr`/`sysServices` where available.
- Role heuristics: default-gateway IP → firewall/router; Wi-Fi RSSI source → AP.
- Manual tag override stored in hub DB (mirrors Auvik's Manage Tags).

### Phase D — Map view modes + search/filter

- **View modes**: Hybrid / Layer 1 / Layer 2 / Layer 3 — filter edges by `layer`.
- **Map search** over node fields (name, kind, status, vendor, subnet, IP, MAC).
- Filter by status / kind / subnet; export map as SVG/PNG.

### Phase E — Monitoring & inventory around the map (later)

Lower priority: alert badges on map nodes, inventory tables, hardware/lifecycle
status. These require hub-side alerting rules on top of the OTLP metric store.

## Collector-aware from the start

Every OTLP metric carries `collector_id` and `site_id` labels. The hub assembler
tags every map node with the collector that observed it. Multi-collector sites
simply result in multiple collector-tagged observation sets merged into one map
document — mirroring Auvik's site/collector structure (see
[06-auvik-feature-reference.md](06-auvik-feature-reference.md) → Auvik Collectors).
