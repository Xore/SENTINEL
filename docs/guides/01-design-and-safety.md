# Design and safety

## Scope worksheet

Record these before connecting the probe:

- Owner, site, change ticket, start/end time, and emergency contact
- Authorized VLANs/CIDRs and specifically excluded systems
- Switch and exact SPAN source/destination ports
- Expected aggregate and peak throughput
- Required retention and whether payload/credentials may legally be stored
- Approved active checks, target IPs, ports, rate, and maintenance window
- Data classification, export rules, deletion date, and incident escalation path

## Network placement

Prefer a physical TAP. When using SPAN, mirror both ingress and egress for the required VLANs, avoid oversubscribing the destination port, disable port security features that interfere with mirrored frames, and verify VLAN tag preservation. The capture interface must have no layer-3 address. Keep management on a separate controlled VLAN.

Do not capture an entire enterprise by default. Start at an OT cell/area boundary or an aggregation link whose traffic and ownership are understood. Mirror traffic on the inside of NAT when host identity matters.

## Hardening baseline

- Full-disk encryption and a strong recovery-key process
- Automatic security updates during an approved window
- Host firewall: deny inbound by default; permit SSH/HTTPS only from the management subnet or VPN
- SSH keys only; disable password login and root login
- ntopng authentication enabled and its web port restricted to the management network
- Put remote web access behind a site-approved HTTPS reverse proxy or VPN
- Accurate NTP from the site-approved source
- No secrets in this Git repository
- Lock the screen, secure the laptop physically, and use a UPS for long captures
- Export evidence with hashes; define retention and secure deletion procedures

## OT rules of engagement

Passive parsing is normally low risk because the probe sends nothing to the monitored network through its capture NIC. Active interaction is different: legacy PLCs, gateways, and embedded stacks may be sensitive to unexpected connections. Begin with TCP connect-only checks against named targets. Application-layer S7 identification or OPC UA `GetEndpoints` should be added only after asset-owner and vendor approval, then validated on a test system first.

For the full academic basis for these rules, see [`../theory/ot/ot-protocol-safety-theory.md`](../theory/ot/ot-protocol-safety-theory.md) (NIST SP 800-82 Rev.3, IEC 62443-3-2/-3-3).

Use an incident runbook rather than automatically blocking traffic. This laptop is a sensor, not an IPS or safety control.
