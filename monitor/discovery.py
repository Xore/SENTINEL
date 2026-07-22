"""Broad-view LAN host discovery for the network probe.

Builds an inventory of the devices on a directly-connected subnet: IP, MAC,
best-effort vendor (from an embedded OUI table skewed toward IT/OT/network
gear), reverse-DNS name and how the host was seen. Passive-leaning and light:
an ICMP/ARP host sweep plus the kernel neighbour cache - NOT a port scan and
never a payload against OT devices.

Safety:
- Only subnets directly connected to the probe are scanned. An explicit
  --subnet must still fall inside one of those connected networks.
- The subnet is bounded (prefix 22..30, i.e. <= 1024 addresses) so a typo
  cannot sweep the internet.
- No TCP/UDP application probing here; discovery only. Use the port monitor or
  the (allow-listed) traffic generator for anything that sends payloads.

CLI (used by the dashboard, args validated again here):
  discovery.py --iface enp0s31f6 [--subnet 10.0.255.0/24] [--timeout 3]
Prints a JSON summary on stdout.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

MIN_PREFIX = 22   # <= 1024 addresses
MAX_PREFIX = 30

# Compact OUI -> vendor table, focused on the vendors this probe cares about
# (industrial control, network infrastructure, common endpoints). Best-effort
# labelling only; a blank vendor is not an error.
OUI = {
    "00:1b:1b": "Siemens", "00:0e:8c": "Siemens", "00:1f:f8": "Siemens",
    "00:1c:06": "Siemens", "28:63:36": "Siemens", "00:18:18": "Siemens",
    "8c:f3:19": "Siemens", "20:87:56": "Siemens",
    "00:a0:45": "Phoenix Contact", "a8:74:1d": "Phoenix Contact",
    "00:01:05": "Beckhoff", "00:1b:c5": "Beckhoff",
    "00:00:bc": "Rockwell/Allen-Bradley", "00:1d:9c": "Rockwell/Allen-Bradley",
    "e4:90:69": "Rockwell/Allen-Bradley",
    "00:80:f4": "Telemecanique/Schneider", "00:00:54": "Schneider Electric",
    "00:20:4a": "Pronet/WAGO", "00:30:de": "WAGO",
    "00:0c:29": "VMware", "00:50:56": "VMware", "00:1c:14": "VMware",
    "00:15:5d": "Microsoft Hyper-V", "52:54:00": "QEMU/KVM",
    "00:1a:a0": "Dell", "00:14:22": "Dell", "18:03:73": "Dell",
    "b8:ca:3a": "Dell", "a4:34:d9": "Intel", "00:1b:21": "Intel",
    "00:00:0c": "Cisco", "00:1a:a1": "Cisco", "00:25:45": "Cisco",
    "00:0b:86": "HP/Aruba", "00:1a:1e": "HP/Aruba", "24:de:c6": "HP/Aruba",
    "fc:ec:da": "Ubiquiti", "24:a4:3c": "Ubiquiti", "b4:fb:e4": "Ubiquiti",
    "00:11:32": "Synology", "00:1f:33": "Netgear", "00:14:6c": "Netgear",
    "b8:27:eb": "Raspberry Pi", "dc:a6:32": "Raspberry Pi", "e4:5f:01": "Raspberry Pi",
}

_MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")


def vendor_for(mac: str) -> str:
    return OUI.get(mac.lower()[:8], "")


def connected_subnets(iface: str | None) -> list[ipaddress.IPv4Network]:
    cmd = ["ip", "-o", "-f", "inet", "addr", "show"]
    if iface:
        cmd += ["dev", iface]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    nets = []
    for line in out.splitlines():
        match = re.search(r"\binet (\d+\.\d+\.\d+\.\d+/\d+)", line)
        if match:
            net = ipaddress.ip_network(match.group(1), strict=False)
            if isinstance(net, ipaddress.IPv4Network) and not net.is_loopback:
                nets.append(net)
    return nets


def resolve_subnet(iface: str | None, override: str | None) -> ipaddress.IPv4Network:
    connected = connected_subnets(iface)
    if not connected:
        raise ValueError(f"no IPv4 subnet on {iface or 'any interface'}")
    if override:
        want = ipaddress.ip_network(override, strict=False)
        if not any(want.subnet_of(net) or want == net for net in connected):
            raise ValueError(f"{override} is not a directly-connected subnet ({', '.join(map(str, connected))})")
        target = want
    else:
        target = connected[0]
    if not MIN_PREFIX <= target.prefixlen <= MAX_PREFIX:
        raise ValueError(f"subnet {target} prefix /{target.prefixlen} out of range /{MIN_PREFIX}../{MAX_PREFIX}")
    return target


def nmap_sweep(subnet: ipaddress.IPv4Network, timeout: float) -> set[str]:
    """Host-discovery only (-sn), no name resolution (-n). Falls back cleanly
    if nmap is missing - the neighbour cache still gives us hosts."""
    up: set[str] = set()
    try:
        result = subprocess.run(
            ["nmap", "-sn", "-n", "--host-timeout", f"{int(timeout)}s", str(subnet)],
            capture_output=True, text=True, timeout=max(60, subnet.num_addresses // 8))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return up
    for line in result.stdout.splitlines():
        match = re.search(r"Nmap scan report for (\d+\.\d+\.\d+\.\d+)", line)
        if match:
            up.add(match.group(1))
    return up


def neighbour_cache(subnet: ipaddress.IPv4Network) -> dict[str, str]:
    """IP -> MAC from the kernel ARP/neighbour cache (unprivileged)."""
    macs: dict[str, str] = {}
    try:
        out = subprocess.run(["ip", "-4", "neigh", "show"], capture_output=True, text=True, timeout=5).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return macs
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] not in ("FAILED", "INCOMPLETE"):
            ip = parts[0]
            try:
                in_net = ipaddress.ip_address(ip) in subnet
            except ValueError:
                continue
            if in_net and "lladdr" in parts:
                mac = parts[parts.index("lladdr") + 1].lower()
                if _MAC_RE.match(mac):
                    macs[ip] = mac
    return macs


def reverse_dns(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (OSError, socket.herror):
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Broad-view LAN host discovery.")
    parser.add_argument("--iface")
    parser.add_argument("--subnet")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args(argv)

    try:
        subnet = resolve_subnet(args.iface, args.subnet)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2

    swept = nmap_sweep(subnet, args.timeout)
    cached = neighbour_cache(subnet)
    ips = sorted(swept | set(cached), key=lambda value: tuple(int(part) for part in value.split(".")))

    with ThreadPoolExecutor(max_workers=32) as pool:
        names = dict(zip(ips, pool.map(reverse_dns, ips)))

    hosts = []
    for ip in ips:
        mac = cached.get(ip, "")
        seen = "arp+ping" if ip in swept and ip in cached else ("ping" if ip in swept else "arp")
        hosts.append({
            "ip": ip, "mac": mac, "vendor": vendor_for(mac) if mac else "",
            "name": names.get(ip, ""), "seen": seen,
        })

    print(json.dumps({
        "subnet": str(subnet), "interface": args.iface or "(default route)",
        "host_count": len(hosts), "hosts": hosts,
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
