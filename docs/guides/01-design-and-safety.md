# Design and safety

## Guiding principles

The v2 collector is a **sensor and reporter, not a controller**. It reads and probes;
it never writes to, reconfigures, or blocks traffic on any monitored device.
All active checks require explicit configuration — nothing probes by default except
what is listed in `collector.yaml`.

---

## Scope worksheet

Record these before deploying a collector node:

- Owner, site, change ticket, start/end time, and emergency contact
- Authorised VLANs/CIDRs and specifically excluded systems
- Approved active check types, target IPs, ports, rate, and maintenance window
- Expected aggregate and peak probe traffic
- Data classification, export rules, deletion date, and incident escalation path
- Required retention period and whether metric labels may include hostnames/IPs
  under the applicable data governance policy

---

## Network placement

- The collector needs a **management-plane IP** on the segment(s) it monitors.
- Keep the collector's management interface on a dedicated controlled VLAN where possible.
- For OT segments: deploy the collector inside the zone boundary (Purdue Level 2/3
  demilitarised zone) — never place it on the Level 1 control network directly.
- The collector sends **no traffic** to a network interface unless a check targeting
  that network is explicitly configured in `collector.yaml`.

---

## Hardening baseline

- Full-disk encryption and a strong recovery-key process on the collector node
- Automatic security updates during an approved maintenance window
- Host firewall: deny inbound by default; permit outbound OTLP/gRPC to the hub only
- SSH keys only; disable password login and root login
- No secrets in the Git repository — credentials live in `/etc/analyselaptop/` with
  `0600` permissions, owned by the `analyselaptop` service account
- mTLS between collector and hub: mutual certificate verification; PKI auto-enrol/renew
- Lock the screen and secure the device physically; use a UPS for continuous nodes

---

## Capability model

The collector runs as an unprivileged service account. Required Linux capabilities are
granted explicitly via `setcap` or `AmbientCapabilities` — never via `setuid` root:

| Capability | Used by | When to grant |
|---|---|---|
| `CAP_NET_RAW` | ICMP probes, MTR hop-tracing, bcast/mcast capture | Always (all deployments) |
| `CAP_NET_ADMIN` | Wi-Fi `iw scan` (some kernels) | Only when Wi-Fi scan is enabled |
| `CAP_BPF` | eBPF flow tracking (Phase C13) | Only when eBPF enabled; kernel ≥5.8 |
| `CAP_PERFMON` | eBPF flow tracking (Phase C13) | Only when eBPF enabled; kernel ≥5.8 |

No other capabilities are needed. If a check requires a capability that is not
granted, it logs a structured warning and skips — it never crashes the collector.

---

## OT rules of engagement

Passive metric reads from `/proc/` and ARP cache inspection are low risk
because they generate no network traffic. Active checks are different:
legacy PLCs, gateways, and embedded stacks may be sensitive to unexpected connections.

**Default posture for OT targets:**

1. Start with **TCP connect-only** checks against named targets.
   `net_tcp.py` opens and immediately closes a TCP connection — it does not
   authenticate, read data, browse nodes, or write anything.
2. SNMP GET/WALK (`net_snmp.py`) should be added only after asset-owner approval;
   use read-only community strings and SNMPv3 auth where possible.
3. Modbus TCP passive monitoring (`net_modbus.py`) reads coil/register values;
   it never writes (FC05/FC06/FC16 write function codes are refused unconditionally).
4. Application-layer OPC UA `GetEndpoints` or S7comm identification should be
   added only after asset-owner and vendor approval, then validated on a test system.
5. Configure OT targets in a dedicated `queue: ot` group in `collector.yaml` to
   apply lower probe rates and concurrency limits automatically.

**Academic basis:** NIST SP 800-82 Rev.3 §6.2.1 (active scanning caution in live ICS),
IEC 62443-3-2 §4.2 (passive asset discovery as default), IEC 62443-3-3 FR7
(availability as a security property). Full analysis in
[`../theory/ot/ot-protocol-safety-theory.md`](../theory/ot/ot-protocol-safety-theory.md).

**BACnet note:** `Who-Is`/`I-Am` discovery is an active broadcast mechanism;
gate it with the same approval required for OPC-UA `GetEndpoints`.

**Zone/conduit note (IEC 62443-3-2 §4.3):** the collector itself is a conduit
endpoint whenever it queries any OT-zone device, even read-only. Document the
collector’s OT polling configuration as part of the conduit inventory.

---

## Incident handling

Use an incident runbook rather than automatically blocking traffic.
The collector is a sensor — not an IPS or safety control. If anomalous activity
is detected via metrics:

1. Preserve relevant metric windows and hub alert history.
2. Record UTC time and alert identifiers.
3. Escalate through the site’s incident and safety process.
4. Do not reconfigure production equipment from the collector node.
