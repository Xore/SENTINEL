# Wired and Wi-Fi capture

## Wired capture acceptance

Replace `CAPTURE_IFACE` with the dedicated interface:

```bash
ip -brief address show CAPTURE_IFACE
sudo ethtool -k CAPTURE_IFACE
sudo tcpdump -ni CAPTURE_IFACE -c 50
```

The interface should be UP but have no IPv4/IPv6 address. The packet sample should show both directions and the expected VLANs/hosts. NIC offloads (GRO/LRO/TSO) can merge or reorder frames and distort capture; disable them on the capture NIC (`ethtool -K <iface> gro off lro off tso off gso off`) when doing timing-sensitive analysis. Compare switch SPAN counters, NIC counters, and application capture-drop metrics under peak load.

## Wi-Fi limitations and workflow

Wi-Fi requires a second adapter dedicated to monitor mode. Driver support, not the printed chipset brand, is decisive. Verify before buying/using it:

```bash
iw list | sed -n '/Supported interface modes:/,/Band/p'
```

Look for `* monitor`. Stop any service managing **only that adapter**, set monitor mode using the driver/tool's documented process, lock it to one authorized channel, and capture to a rotating PCAP. Do not disconnect clients, transmit deauthentication frames, impersonate access points, or capture outside the authorized SSIDs/channels.

Example capture after a monitor interface already exists:

```bash
sudo dumpcap -i wlan0mon -b duration:300 -b files:24 -w /var/capture/wifi.pcapng
```

This example retains roughly two hours in 5-minute files. Size limits should also be used on busy channels. Open completed PCAP/PCAPNG files in Wireshark or another PCAP-compatible analyser. Channel hopping loses packets and makes timing analysis unreliable; use multiple radios for simultaneous channels.

## Visibility test

Generate no traffic from the capture NIC. Instead, use already authorized client activity and confirm that the capture sees:

- Expected source/destination IP and MAC pairs
- DNS/DHCP/NTP where present
- VLAN identifiers where the TAP/SPAN preserves them
- Known S7comm/PROFINET/OPC UA conversations in the ICS dashboards
- Suricata events and Zeek connection logs

If only broadcasts appear, the SPAN/TAP is probably misconfigured. If only one direction appears, fix the mirror source. If capture drops increase, reduce mirrored scope or use faster capture hardware.

## Wireshark-compatible evidence capture

Install Wireshark CLI tools and add the capture account to the distro's approved capture group/process:

```bash
sudo apt install tshark
sudo mkdir -p /var/capture
sudo ./scripts/capture-pcapng.sh enp0s20f0u1 /var/capture 300 24 2048
```

The capture script refuses an interface with an IP address, writes PCAPNG using `dumpcap`, rotates by time and size, limits the number of files, records capture metadata, and creates SHA-256 hashes after capture. Keep capture files encrypted and access-controlled: PCAP can contain credentials, proprietary process values, personal data, and files. ntopng and Zeek may observe the interface concurrently, but test packet loss under load; multiple capture consumers increase CPU work.

Useful Wireshark display filters (these do not generate traffic):

| Purpose | Display filter |
|---|---|
| Siemens S7 | `s7comm \|\| s7comm_plus` |
| OPC UA | `opcua` |
| PROFINET | `pn_dcp \|\| pn_io \|\| dcerpc` |
| Ethernet broadcast | `eth.dst == ff:ff:ff:ff:ff:ff` |
| IPv4 multicast | `ip.dst == 224.0.0.0/4` |
| IPv6 multicast | `ipv6.dst == ff00::/8` |
| ARP | `arp` |
| Spanning Tree | `stp` |
| Switch/AP advertisements | `lldp \|\| cdp` |
| Wi-Fi beacons/probes | `wlan.fc.type == 0` |
| TCP retransmission clues | `tcp.analysis.retransmission \|\| tcp.analysis.fast_retransmission` |

Run `./scripts/pcap-summary.sh file.pcapng` for a reproducible text/CSV summary before opening Wireshark.
