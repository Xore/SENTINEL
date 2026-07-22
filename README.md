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

- **Management NIC:** built-in Ethernet or a dedicated USB NIC, with one static IP. Remote UI and SSH live here.
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
2. Install **Ubuntu Server 24.04 LTS** with full-disk encryption. Do not use the Malcolm appliance ISO unless every internal disk may be erased; its installer can partition all non-removable storage without confirmation.
3. Patch Ubuntu, create a non-root administrator, enable Secure Boot if supported, and give the management NIC a static address. Do not configure an address, route, DNS, or gateway on the capture NIC.
4. Copy this repository to the probe, run `sudo ./scripts/preflight.sh`, then `sudo ./scripts/install-lightweight.sh`. The first is read-only; the second shows the package plan and asks before installing.
5. Follow [docs/02-install-lightweight.md](docs/02-install-lightweight.md) to select optional ntopng, Zeek, and Suricata layers.
6. To install the local dashboard as a restricted service, copy the repository to a system path first (Ubuntu home directories are mode 750, so the service user cannot read `/home/<user>`): `sudo cp -r ~/analyseLaptop /opt/analyseLaptop && sudo chmod -R a+rX /opt/analyseLaptop`. Then review and run `sudo /opt/analyseLaptop/scripts/install-dashboard-service.sh --apply`, validate with `./scripts/verify-probe.sh`, and add the outage monitor with `sudo /opt/analyseLaptop/scripts/install-outage-monitor.sh --apply`.
7. Configure the SPAN/TAP and validate packet visibility using [docs/03-capture-and-wifi.md](docs/03-capture-and-wifi.md).
8. Enter known assets in `config/assets.csv`; it becomes the human-owned reference for results.
9. Only after authorization, copy `config/targets.example.csv` to `config/targets.csv` and use `sudo ./scripts/ot-reachability.sh config/targets.csv` for narrowly scoped TCP checks.
10. Use [docs/04-operations.md](docs/04-operations.md) for acceptance tests and routine operation.

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
- Plots (loss, RTT, Wi-Fi signal, outage bands) and the event timeline live
  at `http://127.0.0.1:8088/monitor`.

Install after the dashboard service:

```bash
sudo ./scripts/install-outage-monitor.sh --apply
```

Then edit `/etc/network-probe/monitor-targets.csv` (gateway, internal
servers, external references, per interface) and
`sudo systemctl restart network-probe-monitor`.

## What this detects

- Optional Suricata signature alerts and Zeek notices/weird events
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
- `monitor/outage_monitor.py` — continuous per-path ping/Wi-Fi recorder with outage events
- `scripts/install-outage-monitor.sh` — systemd service for the outage monitor

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
