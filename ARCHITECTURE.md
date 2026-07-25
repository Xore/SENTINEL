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
                         results + history (SQLite)
                               |
                         local dashboard
                               ^
                               |
              Go collector (active checks, cross-platform)
              ping / DNS / HTTP / TCP / NTP / port
              standalone or API-push mode
```

The capture plane uses a dedicated no-IP interface. The management plane uses a different interface and is the only path to the dashboard. The Go collector runs independently on any host and pushes results to the dashboard API or writes to a local SQLite store.

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

## Monitor stack (Python, standalone)

The `monitor/` directory is the primary continuous-observation engine, running as a systemd service on the probe. All modules write to the shared SQLite store at `/var/lib/network-probe/monitor.db` (14-day retention).

| Module | Role |
|---|---|
| `outage_monitor.py` | Core daemon: per-path `ping -O` streams (1 s), Wi-Fi link telemetry (5 s), NIC error counters, outage event classification, broadcast-storm snapshot on event start, route tracking via `mtr` (5 min) |
| `service_check.py` | Service-health profiles (60 s): DNS query time per resolver, HTTP/HTTPS with connect/TLS/response phases, plain TCP connect, chrony NTP offset |
| `probes.py` | Port-probe engine: well-known port → expected-response table, OT connect-only safety boundary |
| `path_check.py` | Route and per-hop quality: `mtr -n -j` hop chain, per-hop loss %, RTT (last/avg/best/worst/StDev), route-change event detection |
| `scheduler.py` | Jittered job scheduler: per-zone concurrency limits, cooldown, backoff on failure, safety-threshold suspension (loss, CPU, disk, broadcast rate) |
| `discovery.py` | LAN host inventory: ICMP/ARP sweep + kernel neighbour cache, IP/MAC/OUI-vendor/reverse-DNS, subnet bounded to /22–/30 |
| `wifi_survey.py` | Wi-Fi AP/channel survey via NetworkManager scan cache: SSID, BSSID, channel, band, signal, security, per-channel occupancy |
| `snmp_probe.py` | Read-only single-host SNMP (v2c/v3): system group + interface list, no range sweep |
| `tcp_stat.py` | TCP connection-state counters and socket-level statistics |
| `traffic_gen.py` | Bounded, allow-listed TCP/UDP traffic generator: max 1000 messages, 100/s, 64 KB payload, 60 s; OT ports refused |
| `ids_reader.py` | Read-only Suricata `eve.json` tail for the Security dashboard tab |

## Collector (Go, cross-platform)

The `collector/` directory is a lightweight Go active-check agent designed to run on any host (Linux, Windows, macOS) and report to the dashboard API or a local SQLite store. It is the target for feature-parity with the Python monitor stack.

**Current checks** (`collector/checks.go`):

| Check | Implementation |
|---|---|
| ICMP ping | Raw socket; `ping_linux.go` / `ping_windows.go`; privilege re-exec via `reexec_unix.go` / `reexec_windows.go` |
| DNS resolution | Query time per resolver |
| HTTP/HTTPS | Connect, TLS handshake, response timing, status-code validation |
| TCP connect | Port reachability with configurable timeout |
| NTP | Chrony/NTP offset |
| Port (allow-listed) | Bounded port health with OT connect-only safety |

Scheduler: fixed 30 s tick (`collector/main.go`). Pre-built binaries for linux/amd64, linux/arm64, windows/amd64, windows/arm64 are produced by the CI release workflow and stored in `collector/dist/`.

**Roadmap parity items** (tracked in [ROADMAP.md](ROADMAP.md)):
- RTT distributions and loss %
- Wi-Fi link quality and NIC error counters
- Route/hop tracing (`mtr`-equivalent)
- Adaptive MDP scheduling
- SNMP GET
- Prometheus metrics export

## Tool catalog

Core tools:

- `dumpcap`: efficient bounded PCAPNG and capture-drop statistics
- `tshark` / Wireshark: protocol decoding, statistics and investigation
- `ip`, `ethtool`, `ss`: local links, drivers, counters and sockets
- `iw`: Wi-Fi capability, association, signal, channel and bitrate
- `nmap -sT`: explicit allow-listed TCP connect only
- `tracepath`: route and path-MTU clues (Actions path-health job)
- `mtr`: per-hop latency/jitter/loss for the continuous route probe and path map (`path_check.py`)
- `dig` and `chronyc`: DNS and time profiles (`service_check.py`)

Optional continuous tools:

- ntopng Community: live hosts, flows, topology and basic alerts
- Zeek: compact long-term metadata and policy scripting
- Suricata: signature IDS and EVE JSON (read by `ids_reader.py`)
- Prometheus/node_exporter/blackbox_exporter: optional trend storage and alerts

Optional authenticated adapters:

- SNMPv3 for switch/AP counters (`snmp_probe.py`; prefer v3 over v2c community strings)
- OPC UA client for `GetEndpoints` and a configured read-only health NodeId
- Siemens/vendor tooling for read-only diagnostics after model/firmware validation
- Wireless controller API for radios, utilization, retries, clients and alarms

Credentials must not go in `targets.csv`. An adapter should reference a root-readable secret, use a fixed request shape, validate input, time out, rate limit, audit, and normalize its output.

## Scheduling and load control

- One queue per zone; default concurrency 1 for OT and 4 for IT (`scheduler.py`).
- Add 10–20% jitter and a per-target cooldown.
- Back off on failures; never expand a failed target into a subnet scan.
- Suspend active jobs when loss, capture drops, CPU, disk or broadcast rate crosses a safety threshold.
- Use a disk-bounded capture ring and reserve free-space headroom.
- Audit operator, time, target, profile, parameters, result and duration.

## Implementation state

| Area | Status |
|---|---|
| Interface/tool health dashboard | ✅ Implemented |
| Allow-listed TCP/route jobs | ✅ Implemented |
| Bounded PCAPNG capture | ✅ Implemented |
| PCAP summary | ✅ Implemented |
| Wi-Fi link state | ✅ Implemented |
| SQLite result history | ✅ Implemented |
| Jittered scheduler with safety suspension | ✅ Implemented (`scheduler.py`) |
| Loss/latency/Wi-Fi/service-latency charts | ✅ Implemented |
| Route tracking and path map (SVG) | ✅ Implemented (`path_check.py`) |
| Service-health profiles (DNS/HTTP/TLS/NTP) | ✅ Implemented (`service_check.py`) |
| Port-health engine with OT safety | ✅ Implemented (`probes.py`) |
| TCP connection statistics | ✅ Implemented (`tcp_stat.py`) |
| LAN discovery (IP/MAC/vendor) | ✅ Implemented (`discovery.py`) |
| Wi-Fi AP/channel survey | ✅ Implemented (`wifi_survey.py`) |
| Suricata IDS integration | ✅ Implemented (`ids_reader.py`) |
| SNMP read-only probe | ✅ Implemented (`snmp_probe.py`) |
| LLDP/CDP neighbour discovery | ✅ Implemented (lldpd receive-only) |
| Bounded traffic generator | ✅ Implemented (`traffic_gen.py`) |
| Go collector (ping/DNS/HTTP/TCP/NTP/port) | ✅ Implemented (`collector/`) |
| Collector feature-parity with Python stack | 🔲 Roadmap |
| Baseline engine (rolling percentiles) | 🔲 Roadmap |
| Broadcast-source drill-down | 🔲 Roadmap |
| SNMPv3 switch/AP adapter | 🔲 Roadmap |
| OPC UA read-only adapter | 🔲 Roadmap |
| Prometheus export | 🔲 Roadmap |
| Adaptive MDP scheduling | 🔲 Roadmap |

The expanded use-case backlog and delivery phases are maintained in [ROADMAP.md](ROADMAP.md).

## Trust boundary

The dashboard binds to `127.0.0.1` by default. Reach it through SSH or an approved VPN. If exposed on a management VLAN, use authenticated HTTPS and firewalling. Run the web process unprivileged; provide capture through Linux capabilities/group permission or a narrow helper, never general `sudo` or a root web server.
