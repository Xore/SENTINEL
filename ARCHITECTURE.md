# System architecture

## Operating model

The probe separates observation from interaction. This prevents a dashboard operator from accidentally turning a monitoring laptop into an uncontrolled OT scanner.

```text
TAP / SPAN / Wi-Fi monitor
          |
          v
  Capture plane ---------> bounded PCAPNG -------> Wireshark / reports
   dumpcap/libpcap             |                   optional Zeek logs
          |                    +-----------------> ntopng live flows
          +--------------------------------------> optional Suricata IDS

Approved inventory ---> guarded job scheduler ---> diagnostic adapters
                               |                    TCP / route / DNS / NTP
                               |                    OPC UA / S7 / SNMP opt-in
                               v
                         results + history
                               |
                         local dashboard
```

The capture plane uses a dedicated no-IP interface. The management plane uses a different interface and is the only path to the dashboard.

## Scan levels

| Level | Behavior | Schedule | Production OT default |
|---|---|---|---|
| 0 Passive | Decode traffic already present; send nothing | continuous | yes |
| 1 Basic | One ICMP or TCP connect to an approved address/port | 1–5 min, jittered | owner approval |
| 2 Authenticated health | Read-only SNMP, HTTPS/API, OPC UA, vendor diagnostics | 5–15 min | profile approval |
| 3 Discovery | Restricted ARP/ping/port discovery in an approved CIDR | maintenance/ad hoc | off |
| 4 Assessment | Version detection, scripts, vulnerability/wireless active tests | change window | off |

The dashboard implements Level 0 capture/analysis and explicit Level 1 TCP/route jobs. Higher levels are extension profiles, not implicit permissions.

## What should test what

| Asset/service | Passive evidence | Safe active check | Optional deeper check |
|---|---|---|---|
| S7 PLC | S7comm/S7comm Plus, PROFINET, peers, operation mix | TCP/102 | approved identity/SZL read; never write/control |
| OPC UA server | sessions, security policies, service/result mix | configured TCP port | `GetEndpoints`, certificate and designated health NodeId |
| Switch | LLDP/CDP/STP, MACs, VLAN tags, broadcasts | management HTTPS/SSH port | SNMPv3 interface errors/discards, STP, CPU/temp |
| AP/controller | LLDP/CDP, management traffic, Wi-Fi beacons | controller HTTPS port | authenticated client/radio/channel/retry metrics |
| Server | DNS/TLS/app flows, resets/retransmissions | service port and route | HTTPS status, TLS expiry, DNS, application transaction |
| Gateway | ARP/ND, routing protocols, flow pairs | ICMP/TCP and route | SNMP/API interfaces and routing adjacency |
| DHCP/DNS/NTP | responses, errors and timing | explicit query | correctness, latency, redundancy and drift |
| Wi-Fi RF | beacon/probe/deauth frames on one selected channel | local link stats | passive monitor survey; never deauth injection |

## Health dimensions

Health is more than ping:

1. Reachability: success rate, TCP connect time, route changes, path MTU.
2. Service: handshake, expected endpoint/certificate, designated read-only transaction.
3. Quality: latency, jitter, loss, retransmissions, resets, DNS response time.
4. Capacity: throughput, packets/s, top talkers, link utilization and queue drops.
5. Layer 2: errors/discards, speed/duplex, ARP/ND, STP changes and MAC churn.
6. Broadcast/multicast: frames/s and bit/s by source/protocol, baseline deviation and impact.
7. Wi-Fi: RSSI/SNR, retries, PHY rate, channel utilization/width, overlap and roaming.
8. Time: NTP offset/stratum and probe clock accuracy.
9. Security: new devices/services, unusual peers, IDS matches, TLS issues and OT program/write events.

Use rolling baselines by site, segment and production phase. Combine absolute safety limits with deviation from normal percentiles. There is no universal broadcast-storm packets-per-second threshold.

## Tool catalog

Core tools:

- `dumpcap`: efficient bounded PCAPNG and capture-drop statistics
- `tshark` / Wireshark: protocol decoding, statistics and investigation
- `ip`, `ethtool`, `ss`: local links, drivers, counters and sockets
- `iw`: Wi-Fi capability, association, signal, channel and bitrate
- `nmap -sT`: explicit allow-listed TCP connect only
- `tracepath`: route and path-MTU clues (Actions path-health job)
- `mtr`: per-hop latency/jitter/loss for the continuous route probe and path map
- `dig` and `chronyc`: DNS and time profiles

Optional continuous tools:

- ntopng Community: live hosts, flows, topology and basic alerts
- Zeek: compact long-term metadata and policy scripting
- Suricata: signature IDS and EVE JSON
- Prometheus/node_exporter/blackbox_exporter: optional trend storage and alerts

Optional authenticated adapters:

- SNMPv3 for switch/AP counters (prefer it over SNMPv2 community strings)
- OPC UA client for `GetEndpoints` and a configured read-only health NodeId
- Siemens/vendor tooling for read-only diagnostics after model/firmware validation
- Wireless controller API for radios, utilization, retries, clients and alarms

Credentials must not go in `targets.csv`. An adapter should reference a root-readable secret, use a fixed request shape, validate input, time out, rate limit, audit, and normalize its output.

## Scheduling and load control

- One queue per zone; default concurrency 1 for OT and 4 for IT.
- Add 10–20% jitter and a per-target cooldown.
- Back off on failures; never expand a failed target into a subnet scan.
- Suspend active jobs when loss, capture drops, CPU, disk or broadcast rate crosses a safety threshold.
- Use a disk-bounded capture ring and reserve free-space headroom.
- Audit operator, time, target, profile, parameters, result and duration.

## Dashboard roadmap

1. Implemented: interface/tool health, allow-listed TCP/route jobs, bounded PCAPNG, PCAP summary, Wi-Fi link state.
2. Next: SQLite result history, scheduler, loss/latency charts, baseline engine, DNS/NTP/HTTP/TLS profiles.
3. Then: passive live counters, broadcast-source drill-down, capture-drop alarms and annotations.
4. Site adapters: SNMPv3, controller API, OPC UA read-only and validated Siemens identity.
5. Optional alert routing and Prometheus export; never automatic containment.

The expanded use-case backlog and delivery phases are maintained in [ROADMAP.md](ROADMAP.md).

## Trust boundary

The dashboard binds to `127.0.0.1` by default. Reach it through SSH or an approved VPN. If exposed on a management VLAN, use authenticated HTTPS and firewalling. Run the web process unprivileged; provide capture through Linux capabilities/group permission or a narrow helper, never general `sudo` or a root web server.
