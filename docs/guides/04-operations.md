# Operations runbook

## Start of session

1. Confirm authorization/change window and probe clock.
2. Confirm management and capture cables by MAC/interface name.
3. Run `sudo ./scripts/probe-health.sh <capture-interface>`.
4. Start the bounded PCAPNG capture and any selected services (`ntopng`, Zeek, optional Suricata).
5. Validate current hosts/flows in ntopng and protocol traffic using the supplied TShark report or Wireshark filters.
6. Record packet-drop counters and disk free space.

## Passive network-health review

- Capture loss: NIC drops, kernel capture drops, SPAN oversubscription
- Availability: repeated SYNs without replies, resets, connection-state changes
- Name/addressing: DNS failures, duplicate or unexpected DHCP behavior, new MAC/IP mappings
- Timing: NTP participants, clock inconsistencies, latency trends where timestamps allow
- Capacity: top talkers, sudden traffic-volume changes, broadcast/multicast growth
- Security: Suricata alerts, Zeek notices/weird events, new services/software, TLS/certificate anomalies
- OT: new engineering-to-controller pairs, S7 upload/download/programming activity, OPC UA security policies and unexpected browsing/write patterns, cross-zone traffic

Baseline normal behavior for at least one representative production cycle. Alerts without a site-specific asset inventory and baseline will be noisy.

## Approved reachability check

Create the local target list and review it with the asset owner:

```bash
cp config/targets.example.csv config/targets.csv
sudo ./scripts/ot-reachability.sh config/targets.csv
```

The script performs one low-timeout TCP connection per listed target and does not identify versions, authenticate, browse nodes, read PLC state, or write anything. Interpret `open` as TCP listener reachable—not as application healthy.

## Check scheduling and OT gentleness

The outage monitor paces its active service/port checks through a guarded
scheduler (`monitor/scheduler.py`), not a fixed sweep. Each check runs on a
jittered interval, backs off geometrically while it keeps failing (up to a
ceiling) and recovers to the base cadence on the next success, and is never
re-run sooner than a cooldown floor. Checks are split into two queues with
independent pacing and concurrency: **IT** (brisk) and **OT** (deliberately
low-rate, low-concurrency). A check lands in the OT queue when it carries an
explicit `queue: ot`, or when its group/name looks operational-technology
(`plc`, `profinet`, `s7`, `opcua`, `modbus`, `scada`, `hmi`, ...) — so PLC and
OPC UA endpoints are probed gently by default.

## Broadcast-storm assessment

Use the passive PCAP summary first. It reports total frame rate, broadcast/multicast rates, top Ethernet sources, and common discovery/control protocols. There is no universal storm threshold: compare against link capacity, switch telemetry, the site's baseline, and endpoint sensitivity. See [`../theory/ot/segment-health-arp-dhcp-theory.md`](../theory/ot/segment-health-arp-dhcp-theory.md) for the full academic detection model.

## Incident handling

Preserve relevant PCAP and exported events, record UTC time and filters, hash exported files (`sha256sum`), and work on copies. Do not retaliate or reconfigure production from the sensor. Escalate through the site's incident and safety process.

## Maintenance

- Daily/session: disk, drops, service health, clock, current alerts
- Weekly: review new assets/services and false positives
- Monthly: OS and probe/application updates in a change window; test restore and certificate expiry
- Quarterly: validate SPAN scope, access list, retention, alert routing, and incident drill
- Before upgrades: read release notes, back up configuration, export critical data, and record current image digests
