# Product roadmap and future use cases

The probe should work as a field laptop, a remote sensor left at a site, and an offline investigation workstation. Features are prioritized by safety, diagnostic value and operating cost.

## Use cases

### Commissioning and acceptance

- Verify expected VLANs, DHCP, DNS, NTP and gateways before a machine or cell is accepted.
- Confirm approved servers and OT services are reachable from the correct zone.
- Record routes, latency, loss, TLS identity and service response as a baseline.
- Detect wrong speed/duplex, errors, unexpected broadcasts and duplicate addressing.
- Export an acceptance report with PCAP hashes and a configuration snapshot.

### Permanent remote health probe

- Schedule low-rate allow-listed checks with separate OT and IT concurrency limits.
- Retain time-series results and alert on sustained state changes, not single failures.
- Maintain a bounded capture ring with evidence from before an alarm.
- Monitor its own disk, capture drops, clock, temperature and services.

### OT behavior baseline

- Inventory observed S7, S7 Plus, PROFINET and OPC UA communication pairs.
- Learn normal production-cycle timing and operation mix.
- Flag new engineering stations, unexpected PLC programming/upload/download, OPC UA writes and cross-zone peers.
- Compare maintenance-window behavior to production behavior without initiating PLC traffic.

### Wi-Fi survey and troubleshooting

- Map SSID/BSSID/channel/security from passive management frames.
- Track link RSSI, rate and retries while walking a site.
- Correlate roaming with DHCP/DNS/gateway/service interruption.
- Compare channel utilization and co-channel overlap between locations.
- Treat rogue/duplicate SSIDs as evidence for investigation, not an automatic verdict.

### Path and application diagnosis

- Measure DNS, TCP connect, TLS handshake and HTTP transaction separately.
- Track route/path-MTU changes and distinguish link, gateway, WAN and server failures.
- Test redundant endpoints independently and report failover behavior.
- Use a designated read-only OPC UA health NodeId where the owner provides one.
- Correlate active measurements with passive loss and retransmission evidence.

### Incident response and offline analysis

- Freeze the rolling capture without overwriting it.
- Annotate an incident and preserve matching PCAPNG plus system snapshot.
- Hash evidence, work on copies and export filtered packets.
- Import third-party captures for the same reports without live access.
- Generate portable HTML/JSON reports for escalation.

### Asset and change management

- Build an observed inventory from MAC/IP/DHCP/DNS/LLDP/CDP/protocol data.
- Reconcile observations against the owner-maintained inventory.
- Detect new, missing or changed addresses, services, certificates and peers.
- Export CSV/JSON and optionally integrate NetBox later.

## Delivery plan

### P0 — ready for first laptop access

- [x] Ubuntu preflight and lightweight package installer
- [x] PCAPNG ring capture and offline summary
- [x] Allow-listed TCP and route checks
- [x] Interface, tool, disk and Wi-Fi link dashboard
- [x] System snapshot and short passive Layer-2 health scripts
- [x] Local dashboard service bootstrap design
- [x] Validate NIC names, permissions, offloads and capture loss on target hardware
      (MGPNetworkAnalyses01: enp0s31f6 captures drop-free as the service user;
      rx-checksumming/GRO on, TSO off)
- [x] Validate the Wi-Fi adapter, driver and monitor mode
      (wlp2s0 supports managed, monitor, AP and P2P modes)

### P1 — useful daily probe

- [x] SQLite history for measurements and events (`monitor/outage_monitor.py`,
      14-day retention, `/var/lib/network-probe/monitor.db`)
- [x] Continuous per-path ping monitor with outage events, classification and
      broadcast culprit snapshots
- [x] DNS, NTP, TCP, TLS and HTTP profiles with duration metrics
      (`monitor-services.csv`, 60 s interval, TLS handshake timed separately)
- [x] Historical charts and route-change detection (`/monitor` page; tracepath
      hop-sequence tracking every 5 min with change events)
- [x] Guarded scheduler with jitter, cooldown, backoff and OT/IT queues
      (`monitor/scheduler.py`: per-check exponential backoff, jittered intervals,
      cooldown floor, separate low-rate OT queue; drives the service/port loops)
- [ ] Disk reserve/capture policy and a freeze-evidence action
- [ ] JSON/CSV/HTML session report with hashes
- [ ] Configuration validation and an audit trail

### P2 — network and Wi-Fi health

- [x] Live packets/s and multicast/s per interface with drop/error rates
      (derived from NIC counters, charted on `/monitor`)
- [x] Top broadcast source/protocol drill-down (automatic on outage events;
      on demand via the Layer-2 health job)
- [ ] TCP retransmission/reset and DNS failure trends
- [ ] LLDP/CDP/STP observations as a continuous inventory
- [x] Wi-Fi beacon inventory, channel/security matrix and retry/roam timeline
      (passive survey + nearby-AP map + colorized roam/handover timeline;
      `monitor/wifi_survey.py`, Wi-Fi + Access Points tabs)
- [ ] Baselines by segment, hour and production state

### P3 — authenticated infrastructure profiles

- SNMPv3 interface counters, errors, discards, utilization, STP and device health
- Wireless-controller read-only APIs
- OPC UA `GetEndpoints`, certificate/policy validation and configured health-node read
- Siemens read-only identity/diagnostics validated by device family and firmware
- Secrets referenced from protected files or a credential store, never Git/output

### P4 — distributed and integration features

- Multiple sensors forwarding normalized measurements rather than all PCAP
- [x] Prometheus/OpenMetrics scrape endpoint (`/metrics`, off by default, optional
      bearer token; `dashboard/metrics.py`) — webhook/email alerting still pending
- NetBox inventory reconciliation
- Role-based UI behind a site identity provider
- Signed update/configuration bundles for offline sites

## Excluded by default

- Automatic subnet expansion, vulnerability or exploit scanning
- Credential guessing, default-password checks or SNMP sweeps
- Wi-Fi deauthentication, injection or impersonation
- S7/OPC UA writes, mode changes, program operations or arbitrary node browsing
- Inline blocking, automatic production changes or internet dashboard exposure
