# Portable IT/OT Network Analysis Probe

This repository is a deployment and operating guide for a **lightweight Ubuntu 24.04 LTS network probe**. The core is Wireshark/TShark/Dumpcap for packet evidence and scripted summaries. Add ntopng for a live web overview, Zeek for durable connection/protocol logs, and Suricata only if signature-based IDS alerts are required. There is no Elasticsearch/OpenSearch stack and no mandatory container platform.

The probe is **passive-first**. It observes mirrored traffic from a managed-switch SPAN port or a network TAP. Active checks are deliberately separate, target allow-listed, low-rate, and must be approved by the OT system owner. Never connect this device inline with a control path.

Start with [ARCHITECTURE.md](ARCHITECTURE.md) for scan levels, component boundaries, device profiles, health signals, scheduling, and the implementation roadmap.

Future use cases and prioritized features are tracked in [ROADMAP.md](ROADMAP.md).

## Recommended architecture

```text
                          management VLAN / VPN
 Analyst browser  <-------------------------------->  NIC 1 (IP, firewall)
                                                        Laptop
 Switch TAP/SPAN  --------------------------------->  NIC 2 (no IP)
                                              Wireshark + optional services
 Optional Wi-Fi adapter  -------------------------->  monitor capture
```

- **Management NIC:** built-in Ethernet or a dedicated USB NIC (this build uses the built-in Ethernet on DHCP, currently `10.0.255.7`). Remote UI and SSH live here.
- **Capture NIC:** a separate Intel-based wired adapter, with no IP address. Feed it from a TAP or correctly configured SPAN port.
- **Wi-Fi capture:** use a separate Linux-compatible USB adapter that supports monitor mode. One radio/channel cannot provide a complete view of all bands/channels. Capturing protected Wi-Fi payloads requires authorized access and appropriate keys; metadata is still useful without them.
- **Do not use a hub-like laptop connection as an inline bridge.** A laptop failure must not interrupt production.

## Laptop specification

Practical target for a small network or field investigation (far smaller than an all-in-one SIEM/NDR appliance):

| Component | Recommended | Minimum for evaluation |
|---|---:|---:|
| CPU | x86-64, 6–8 modern cores | 4 cores |
| RAM | 16–32 GB | 8 GB |
| Storage | 1–2 TB NVMe TLC | 512 GB SSD |
| Networking | 2 independent Ethernet NICs; Intel preferred | 2 NICs |
| Other | TPM 2.0, full-disk encryption, wired power, cooling | — |

Packet retention, not the tools, usually determines storage: average traffic in Mbit/s multiplied by `10.8` is approximately GB/day of raw packet data. At 50 Mbit/s, raw PCAP is about 540 GB/day. Use a bounded ring buffer and keep long-term Zeek summaries instead of all payloads.

## Install sequence

1. Read [docs/01-design-and-safety.md](docs/01-design-and-safety.md) and obtain written authorization and network scope.
2. Install **Ubuntu Desktop 24.04 LTS** (GUI needed to join Wi-Fi via NetworkManager) with full-disk encryption. Do not use the Malcolm appliance ISO unless every internal disk may be erased; its installer can partition all non-removable storage without confirmation.
3. Patch Ubuntu, create a non-root administrator, and enable Secure Boot if supported. The management NIC takes its address from DHCP (this build: `10.0.255.7`); a static reservation on the switch/router is fine. Do not configure an address, route, DNS, or gateway on the capture NIC.
4. Copy this repository to the probe, run `sudo ./scripts/preflight.sh`, then `sudo ./scripts/install-lightweight.sh`. The first is read-only; the second shows the package plan and asks before installing.
5. Follow [docs/02-install-lightweight.md](docs/02-install-lightweight.md) to select optional ntopng, Zeek, and Suricata layers.
6. To install the local dashboard as a restricted service, copy the repository to a system path first (Ubuntu home directories are mode 750, so the service user cannot read `/home/<user>`): `sudo cp -r ~/analyseLaptop /opt/analyseLaptop && sudo chmod -R a+rX /opt/analyseLaptop`. Then review and run `sudo /opt/analyseLaptop/scripts/install-dashboard-service.sh --apply`, validate with `./scripts/verify-probe.sh`, and add the outage monitor with `sudo /opt/analyseLaptop/scripts/install-outage-monitor.sh --apply`.
7. (Optional) Add passive attack detection: review and run `sudo /opt/analyseLaptop/scripts/install-ids.sh --apply [capture-interface]` to install Suricata (ET Open rules, AF_PACKET IDS mode). Alerts appear in the dashboard's Security tab. See "Attack detection (signature IDS)" below.
8. Configure the SPAN/TAP and validate packet visibility using [docs/03-capture-and-wifi.md](docs/03-capture-and-wifi.md).
9. Enter known assets in `config/assets.csv`; it becomes the human-owned reference for results.
10. Only after authorization, copy `config/targets.example.csv` to `config/targets.csv` and use `sudo ./scripts/ot-reachability.sh config/targets.csv` for narrowly scoped TCP checks.
11. Use [docs/04-operations.md](docs/04-operations.md) for acceptance tests and routine operation.

## Continuous outage monitor

The probe's primary live instrument is the **outage monitor**
(`monitor/outage_monitor.py`), built for intermittent failures such as
"Wi-Fi stays associated but traffic drops for seconds" or "internal network
dead for 1–2 minutes while 1.1.1.1 still answers":

- One `ping -O` stream per (target, interface) pair, one sample per second.
  Probing the same destinations via the Wi-Fi *and* wired NICs separates
  radio problems from network problems.
- Wi-Fi link telemetry every 5 s (signal, bitrate, tx retries/failures,
  beacon loss) plus per-NIC drop/error counters.
- Everything lands in SQLite (`/var/lib/network-probe/monitor.db`, 14-day
  retention). Outage events open after 3 consecutive misses, close after
  5 consecutive replies, and are classified on close (`wifi-only`,
  `internal-only (internet still reachable)`, `total-outage`, …).
- On event start, a 15 s broadcast/multicast capture on the wired interface
  records the top-talking MAC addresses — a broadcast storm from one client
  keeps flowing while unicast is dead, so the snapshot frequently names the
  culprit.
- Service-health profiles every 60 s from `monitor-services.csv`: DNS query
  time (per resolver), HTTP/HTTPS with separate connect/TLS/response timings,
  plain TCP connect, and chrony NTP sync offset.
- Route-change detection: the tracepath hop sequence to internal/external
  references is recorded every 5 min; a changed path becomes a route event.
- Per-interface packets/s, multicast/s and drop rates derived from NIC
  counters.
- Plots (loss, RTT, Wi-Fi signal, service latency, traffic rate, outage
  bands), route tables and the event timeline live at `/monitor`.

### Dashboard exposure and access token

By default the dashboard binds to `127.0.0.1` (SSH tunnel to view). To expose
it on the management-LAN address instead, install with:

```bash
sudo PROBE_EXPOSE=lan /opt/analyseLaptop/scripts/install-dashboard-service.sh --apply
```

This binds to the current IPv4 address of the default-route interface and
generates an access token in `/etc/network-probe/dashboard-token` (shown once
by the installer; readable with sudo). Sign in with **any username** and the
token as password. The transport is plain HTTP: acceptable on a trusted
management network, never through a port-forward to the internet. If the LAN
address changes (DHCP), re-run the installer.

Install after the dashboard service:

```bash
sudo ./scripts/install-outage-monitor.sh --apply
```

This seeds three config files under `/etc/network-probe/` (edit them, then
`sudo systemctl restart network-probe-monitor`):

- `monitor-targets.csv` — ping targets (gateway, internal servers, external
  references), one per interface, that drive outage detection.
- `monitor-services.csv` — DNS/HTTP/HTTPS/TCP/NTP service checks with per-phase
  timing.
- `monitor-ports.csv` — per-port health checks. Well-known ports (80, 443, 22,
  53, 25, 6379, …) probe and expect a valid response automatically; custom
  ports take an optional `send`/`expect`. OT/control ports (S7 102, Modbus 502,
  OPC UA 4840, PROFINET, EtherNet/IP, DNP3, BACnet, SNMP) are **connect-only** —
  the probe never sends an application payload to them.

### Traffic generator

The `/monitor` page includes a bounded traffic generator for path/port testing
(TCP/UDP, custom text/hex/sized payloads, optional expected-response regex). It
only sends to destinations in `/etc/network-probe/traffic-gen-allow.csv`
(`host,port,proto`, seeded empty) and is hard-capped at 1000 messages, 100/s,
64 KB payload, 60 s total. Control-system ports are refused outright — it is a
test tool, not a fuzzer or load flooder.

### Broad view: LAN discovery and Wi-Fi survey

Beyond the outage instrument, the main dashboard gives the wide network picture
the probe was built for:

- **Discovery** tab — a device inventory of a directly-connected subnet: IP,
  MAC, best-effort vendor (OUI table skewed toward IT/OT/network gear) and
  reverse-DNS name, from a light ICMP/ARP host sweep plus the kernel neighbour
  cache (`monitor/discovery.py`). Host discovery only — no port scan, and never
  a payload to OT devices. The subnet is bounded to the probe's own connected
  networks (prefix /22–/30) so a typo cannot sweep the internet.
- **Wi-Fi** tab — an AP/channel survey (`monitor/wifi_survey.py`): every SSID
  on air with BSSID, channel, band, signal and security label, plus a
  per-channel occupancy summary — the "which AP is the Wi-Fi coming from and
  how busy is the RF neighbourhood" view. It reads NetworkManager's scan cache
  (no root) and needs the radio enabled.
- For deeper 802.11 work, `sudo scripts/wifi-monitor-capture.sh <iface>
  <channels> [seconds]` puts a radio into monitor mode, channel-hops, captures
  management/control frames and summarises the beaconing APs and client
  stations. It needs `CAP_NET_ADMIN`, so it is an operator sudo tool and is
  deliberately not a dashboard button (the web process stays unprivileged).

> **Wi-Fi note:** this build's Intel 8260 radio driver (`iwlwifi`) and firmware
> are present and monitor-mode is supported, but the radio can be **rfkill
> hard-blocked** by the Dell wireless switch/BIOS. If the survey reports the
> radio is off, enable the wireless switch or the WLAN radio in BIOS/UEFI, then
> join the network through the desktop GUI.

### Attack detection (signature IDS)

For the "detect attacks, not just issues" half of the brief, the probe runs a
passive signature IDS:

- **Security** tab — recent Suricata alerts (time, severity, signature,
  category, source/destination) plus a per-severity and top-signature summary
  and engine health. It is read-only: the dashboard tails Suricata's `eve.json`
  through `monitor/ids_reader.py` and never starts, stops, or reconfigures the
  engine.
- Install it once on the probe with `sudo ./scripts/install-ids.sh --apply
  [interface]`. This installs Suricata (Ubuntu repo, single binary — the
  lightweight choice over Zeek), pulls the Emerging Threats **Open** ruleset,
  and enables it as a systemd service in **AF_PACKET IDS mode — passive only,
  never inline/IPS**, so it can flag but never block or alter traffic.
- Point it at a no-IP **capture NIC on a SPAN/TAP** when you have one; with only
  the management interface it still sees traffic to/from the probe plus
  broadcast/multicast (enough to catch scans against the probe, ARP anomalies
  and broadcast-storm signatures). Re-run the installer with the capture
  interface name to switch.
- Alerts are exposed to the unprivileged web account by dropping Suricata's
  post-capture group to `probe-dashboard` (group-readable `eve.json`); the web
  process is never granted sudo.

## What this detects

- Suricata signature alerts (installed via `scripts/install-ids.sh`, surfaced in the Security tab)
- New or unexpected devices, services, DHCP/DNS behavior, TLS certificates, software, and communication pairs
- Traffic volume, top talkers, failed connections, retransmission clues, broadcast/multicast behavior, and time-protocol activity
- Passive S7comm, S7comm Plus, PROFINET, and OPC UA operations visible at the monitored point
- Unexpected engineering-station/PLC relationships, discovery, programming/upload/download behavior, and unusual OPC UA connections

It cannot see traffic that does not cross the monitored link, encrypted application content without keys, radio traffic on channels the Wi-Fi adapter is not listening to, or attacks that leave no observable network trace. A SPAN port can also drop packets under load; a TAP is preferable for evidence-quality capture.

## Repository map

- `docs/` — design, lightweight installation, capture, operations, and research notes
- `scripts/preflight.sh` — read-only hardware/OS/interface readiness report
- `scripts/ot-reachability.sh` — explicit allow-list TCP reachability checks only
- `scripts/probe-health.sh` — local status and capture-drop checks
- `scripts/network-snapshot.sh` — hashed local support/configuration snapshot
- `scripts/l2-health.sh` — short passive link/broadcast/protocol health sample
- `scripts/install-dashboard-service.sh` — explicit Ubuntu dashboard bootstrap
- `scripts/verify-probe.sh` — post-install verification
- `scripts/capture-pcapng.sh` — bounded, rotating Wireshark-compatible capture
- `scripts/pcap-summary.sh` — passive endpoint/protocol/broadcast summary
- `config/` — example scope and asset inventory files (never store passwords here)
- `dashboard/` — local web UI/API for guarded jobs and results; see [dashboard/README.md](dashboard/README.md)
- `monitor/outage_monitor.py` — continuous per-path ping/Wi-Fi recorder with outage events, service checks, port checks, route tracking
- `monitor/probes.py` — port-probe engine with well-known port→expected-response table and OT connect-only safety
- `monitor/traffic_gen.py` — bounded, allow-listed TCP/UDP traffic generator
- `monitor/discovery.py` — broad-view LAN host inventory (IP/MAC/vendor/name), discovery-only
- `monitor/wifi_survey.py` — Wi-Fi AP/channel survey (nmcli/iw), with per-channel occupancy
- `monitor/ids_reader.py` — read-only Suricata `eve.json` alert summariser for the Security tab
- `scripts/install-ids.sh` — installs Suricata as a passive signature IDS (ET Open rules, AF_PACKET, systemd)
- `scripts/wifi-monitor-capture.sh` — operator sudo tool: monitor-mode 802.11 mgmt-frame capture and summary
- `scripts/install-outage-monitor.sh` — systemd service for the outage monitor
- `config/monitor-{targets,services,ports}.example.csv`, `config/traffic-gen-allow.example.csv` — seed configs for the monitor and generator

For a standalone evidence capture, run:

```bash
sudo ./scripts/capture-pcapng.sh <capture-interface> /var/capture 300 24 2048
./scripts/pcap-summary.sh /var/capture/<file>.pcapng
```

This produces a ring of 24 five-minute PCAPNG files with a 2 GiB per-file safety cap. The files open directly in Wireshark and can also be uploaded to Malcolm.

## Important safety boundary

Passive capture is the default. Do not run generic vulnerability scanners, unauthenticated SNMP sweeps, Nmap version detection, NSE scripts, S7 reads/writes, OPC UA browsing, fuzzing, or high-rate discovery against production OT without a change window and vendor/site approval. A successful TCP connection proves only that a listener accepted a connection; it does not prove application health or safety.

## Sources

Research was refreshed 2026-07-22. Primary references are collected in [docs/05-research-and-decisions.md](docs/05-research-and-decisions.md).
