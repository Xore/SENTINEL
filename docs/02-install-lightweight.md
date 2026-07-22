# Install the lightweight probe

## Layers

| Layer | Purpose | Default |
|---|---|---|
| Dumpcap/TShark/Wireshark | bounded PCAPNG, protocol decoding, reports | required |
| Nmap connect mode | allow-listed reachability only | required |
| ntopng Community | live hosts, flows, traffic and alerts in a browser | recommended |
| Zeek | compact durable connection/protocol logs and scripting | recommended for continuous use |
| Suricata | IDS signatures and EVE JSON | optional |

Start with the core and ntopng. Add Zeek when you need history without retaining every packet. Add Suricata only when you will maintain rules and tune alerts.

## Core install

```bash
sudo ./scripts/install-lightweight.sh
sudo reboot
```

The script installs distribution packages only: Wireshark CLI/GUI, Nmap, ethtool, `iw`, `jq`, and supporting utilities. It does not enable monitoring services, modify interfaces, or add third-party repositories.

## ntopng live overview

Install the stable package using ntop's current official Ubuntu instructions: <https://packages.ntop.org/>. ntopng uses Redis and normally serves its authenticated UI on port 3000. Configure the capture interface explicitly, define local networks, change the initial administrator password immediately, and allow the UI only from the management subnet/VPN. Do not expose port 3000 directly to the internet.

Official references: [installation](https://www.ntop.org/guides/ntopng/installation.html), [starting/configuration](https://www.ntop.org/guides/ntopng/how_to_start/index.html).

## Zeek metadata

Use the Zeek project's current LTS binary packages or official `zeek/zeek:lts` container, not an unversioned community script: <https://docs.zeek.org/en/lts/install.html>. Point Zeek at the no-IP capture interface and store logs on the data volume. Begin with the standard policy; install third-party packages only after reviewing their source and compatibility.

Zeek produces useful `conn.log`, `dns.log`, `dhcp.log`, `ssl.log`, `notice.log`, and `weird.log` data. OT protocol depth varies by installed analyzer/package, so Wireshark/TShark remains the ground truth decoder in this design.

## Optional Suricata

Install from Ubuntu or the OISF-maintained repository following the current official guide: <https://docs.suricata.io/en/latest/install.html>. Configure AF_PACKET on the capture interface, HOME_NET precisely, EVE JSON output, and the Emerging Threats Open ruleset. Measure capture drops and CPU before leaving it enabled. Rules require updates and local tuning; an untuned alert feed is not a reliable verdict.

## Remote access

Use WireGuard/Tailscale only if approved by the site, or an existing management VPN. Otherwise restrict SSH (keys only) and the ntopng UI with host and upstream firewall rules to a dedicated management subnet. Never place an IP address on the packet-capture interface.
