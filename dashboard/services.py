"""Known-service catalogue for the dashboard.

Drives the custom-target dropdowns (pick a known service instead of typing a
port) and lets scope/traffic entries carry a meaningful protocol label. It is a
reference table only - it never changes how a probe runs; TCP checks stay TCP
connect, UDP stays payload-gated by the allow-list.
"""
from __future__ import annotations

# name, port, proto, category. OT/ICS ports flagged so the UI can warn before
# touching them.
KNOWN_SERVICES: list[dict] = [
    # --- IT / infrastructure ---
    {"name": "ssh", "port": 22, "proto": "tcp", "category": "it"},
    {"name": "telnet", "port": 23, "proto": "tcp", "category": "it"},
    {"name": "dns", "port": 53, "proto": "udp", "category": "it"},
    {"name": "dns-tcp", "port": 53, "proto": "tcp", "category": "it"},
    {"name": "dhcp", "port": 67, "proto": "udp", "category": "it"},
    {"name": "tftp", "port": 69, "proto": "udp", "category": "it"},
    {"name": "http", "port": 80, "proto": "tcp", "category": "it"},
    {"name": "ntp", "port": 123, "proto": "udp", "category": "it"},
    {"name": "netbios", "port": 137, "proto": "udp", "category": "it"},
    {"name": "snmp", "port": 161, "proto": "udp", "category": "it"},
    {"name": "snmp-trap", "port": 162, "proto": "udp", "category": "it"},
    {"name": "ldap", "port": 389, "proto": "tcp", "category": "it"},
    {"name": "https", "port": 443, "proto": "tcp", "category": "it"},
    {"name": "syslog", "port": 514, "proto": "udp", "category": "it"},
    {"name": "smb", "port": 445, "proto": "tcp", "category": "it"},
    {"name": "rdp", "port": 3389, "proto": "tcp", "category": "it"},
    {"name": "vnc", "port": 5900, "proto": "tcp", "category": "it"},
    {"name": "http-alt", "port": 8080, "proto": "tcp", "category": "it"},
    # --- OT / ICS (touch only in a change window) ---
    {"name": "s7-tcp", "port": 102, "proto": "tcp", "category": "ot"},        # Siemens S7 / ISO-TSAP
    {"name": "modbus-tcp", "port": 502, "proto": "tcp", "category": "ot"},
    {"name": "dnp3-tcp", "port": 20000, "proto": "tcp", "category": "ot"},
    {"name": "ethernetip-tcp", "port": 44818, "proto": "tcp", "category": "ot"},
    {"name": "ethernetip-udp", "port": 2222, "proto": "udp", "category": "ot"},
    {"name": "profinet-udp", "port": 34964, "proto": "udp", "category": "ot"},  # PN-IO CM
    {"name": "opcua-tcp", "port": 4840, "proto": "tcp", "category": "ot"},
    {"name": "bacnet-udp", "port": 47808, "proto": "udp", "category": "ot"},
    {"name": "fins-udp", "port": 9600, "proto": "udp", "category": "ot"},       # Omron FINS
    {"name": "iec104", "port": 2404, "proto": "tcp", "category": "ot"},         # IEC 60870-5-104
    {"name": "mqtt", "port": 1883, "proto": "tcp", "category": "ot"},
    {"name": "cip-udp", "port": 2222, "proto": "udp", "category": "ot"},
]

# Base transports plus every named profile above are valid protocol labels for a
# scope/traffic entry.
BASE_PROTOCOLS = {"tcp", "udp"}
VALID_PROTOCOLS = BASE_PROTOCOLS | {s["name"] for s in KNOWN_SERVICES}

# name -> (port, proto), for resolving a picked service.
BY_NAME = {s["name"]: s for s in KNOWN_SERVICES}


def transport(protocol: str) -> str:
    """Reduce a protocol label to its transport ('tcp' or 'udp')."""
    if protocol in BASE_PROTOCOLS:
        return protocol
    svc = BY_NAME.get(protocol)
    return svc["proto"] if svc else "tcp"


def label_for_port(port: int, proto: str = "tcp") -> str:
    for s in KNOWN_SERVICES:
        if s["port"] == port and s["proto"] == proto:
            return s["name"]
    return ""
