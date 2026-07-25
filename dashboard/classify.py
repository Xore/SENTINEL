"""Device classification for the network map (task #39).

Pure, dependency-free inference of a node's device *kind* from the passive
signals the probe already gathers: OUI/vendor string, hostname, open services,
SNMP sysDescr, and the node's graph role (gateway, Wi-Fi AP, the probe itself).

Everything here is a best-effort *guess* layered on top of observed data - it
never launches a scan and never overrides a stronger graph-derived role. A
manual operator tag (stored in settings, applied in app.py) always wins over
whatever this module infers; see docs/07-network-map-and-monitoring-roadmap.md
phase C.
"""
from __future__ import annotations

import re

# The kinds this classifier can assign, richest-first for reporting only. The
# authoritative promotion order lives in app.py (_KIND_RANK): this module only
# ever *proposes* a kind for a node that is still generic (host/neighbour/hop/
# unknown); it must not demote an already-specific role.
GENERIC_KINDS = {"unknown", "host", "hop", "neighbour", "target"}

# --- vendor / OUI keyword table -------------------------------------------
# Substrings matched case-insensitively against the OUI-derived vendor string.
# First hit wins, so order from most-specific role to least. This is a small
# curated table (no giant vendored OUI DB): the vendor string itself already
# comes from the OUI lookup upstream; we only map it to a device role.
_VENDOR_RULES: list[tuple[str, str]] = [
    # network infrastructure
    ("ubiquiti", "ap"), ("mikrotik", "router"), ("cisco", "switch"),
    ("juniper", "switch"), ("aruba", "ap"), ("ruckus", "ap"),
    ("meraki", "ap"), ("tp-link", "router"), ("netgear", "router"),
    ("d-link", "router"), ("zyxel", "router"), ("fortinet", "firewall"),
    ("palo alto", "firewall"), ("sonicwall", "firewall"), ("watchguard", "firewall"),
    ("pfsense", "firewall"), ("ubnt", "ap"),
    # printers
    ("hewlett", "printer"), ("hp inc", "printer"), ("canon", "printer"),
    ("epson", "printer"), ("brother", "printer"), ("lexmark", "printer"),
    ("xerox", "printer"), ("kyocera", "printer"), ("ricoh", "printer"),
    ("zebra", "printer"),
    # phones / VoIP
    ("polycom", "phone"), ("yealink", "phone"), ("grandstream", "phone"),
    ("avaya", "phone"), ("snom", "phone"),
    # IoT / embedded
    ("raspberry", "iot"), ("espressif", "iot"), ("tuya", "iot"),
    ("sonos", "iot"), ("nest", "iot"), (" recon", "iot"), ("shelly", "iot"),
    ("axis communications", "camera"), ("hikvision", "camera"),
    ("dahua", "camera"), ("hanwha", "camera"),
    # servers / hypervisors
    ("vmware", "server"), ("supermicro", "server"), ("synology", "server"),
    ("qnap", "server"),
    # workstations / general compute
    ("dell", "workstation"), ("lenovo", "workstation"), ("intel corporate", "workstation"),
    ("micro-star", "workstation"), ("asustek", "workstation"), ("gigabyte", "workstation"),
    ("apple", "workstation"), ("samsung", "phone"), ("huawei", "phone"),
    ("xiaomi", "phone"), ("google", "iot"),
]

# --- hostname keyword table -----------------------------------------------
# Stems match anywhere a word starts (so "printer" hits "print"); the leading
# \b anchors to a word start to avoid mid-word false positives.
_HOSTNAME_RULES: list[tuple[str, str]] = [
    (r"\b(print|prn|mfp|laserjet)", "printer"),
    (r"\b(unifi|uap|wap|ap\d)", "ap"),
    (r"\b(switch|sfp)", "switch"),
    (r"\b(router|gateway|rtr)", "router"),
    (r"\b(firewall|fw\d|edge)", "firewall"),
    (r"\b(phone|voip|sip)", "phone"),
    (r"\b(camera|ipcam|nvr|cam\d)", "camera"),
    (r"\b(server|srv|esxi|esx|vcenter|nas)", "server"),
    (r"\b(desktop|laptop|workstation|ws\d)", "workstation"),
    (r"\b(iot|sensor|thermostat|plc|hmi)", "iot"),
]

# --- open-service (port) table --------------------------------------------
# A responding port is a strong signal. Keyed by port number -> kind. Only
# unambiguous role ports here; generic 22/80/443 are handled as a weak
# "server" fallback so a lone web port doesn't mislabel a workstation.
_SERVICE_PORT_KIND: dict[int, str] = {
    515: "printer", 631: "printer", 9100: "printer",
    5060: "phone", 5061: "phone",
    554: "camera",   # RTSP
    3389: "workstation",  # RDP
    445: "workstation",   # SMB (weak, but end-user-ish)
    102: "iot", 502: "iot", 20000: "iot", 44818: "iot", 47808: "iot",  # OT/ICS
}
_GENERIC_SERVER_PORTS = {80, 443, 8080, 8443, 3306, 5432, 25, 587, 53}
_INFRA_PORTS = {161, 23}  # SNMP / telnet-managed → infrastructure

# --- SNMP sysDescr keyword table ------------------------------------------
_SNMP_RULES: list[tuple[str, str]] = [
    ("router", "router"), ("switch", "switch"), ("access point", "ap"),
    ("firewall", "firewall"), ("printer", "printer"), ("jetdirect", "printer"),
    ("camera", "camera"), ("linux", "server"), ("windows", "workstation"),
]


def _match_vendor(vendor: str) -> str | None:
    v = (vendor or "").lower()
    if not v:
        return None
    for needle, kind in _VENDOR_RULES:
        if needle.strip() in v:
            return kind
    return None


def _match_hostname(hostname: str) -> str | None:
    h = (hostname or "").lower()
    if not h:
        return None
    for pattern, kind in _HOSTNAME_RULES:
        if re.search(pattern, h):
            return kind
    return None


def _match_services(services) -> str | None:
    """Highest-confidence role among a node's responding ports."""
    ports: set[int] = set()
    for svc in services or []:
        try:
            ports.add(int(svc))
        except (TypeError, ValueError):
            continue
    for port, kind in _SERVICE_PORT_KIND.items():
        if port in ports:
            return kind
    if ports & _INFRA_PORTS:
        return "switch"
    if ports & _GENERIC_SERVER_PORTS:
        return "server"
    return None


def _match_snmp(sys_descr: str) -> str | None:
    d = (sys_descr or "").lower()
    if not d:
        return None
    for needle, kind in _SNMP_RULES:
        if needle in d:
            return kind
    return None


def classify(
    *,
    current_kind: str = "unknown",
    vendor: str = "",
    hostname: str = "",
    services=None,
    sys_descr: str = "",
    is_gateway: bool = False,
    is_ap: bool = False,
) -> dict | None:
    """Propose a device kind for a node. Returns ``None`` when the node already
    has a specific graph-derived role (leave it alone) or when no signal fires.

    On a hit returns ``{"kind", "source", "reason"}``. Signals are tried
    strongest-first: explicit role → open services → SNMP → vendor OUI →
    hostname. The caller decides how to apply it (and a manual tag overrides
    all of this).
    """
    if current_kind and current_kind not in GENERIC_KINDS:
        return None  # never demote an already-specific role (ap/router/self/…)

    if is_gateway:
        return {"kind": "router", "source": "role", "reason": "default-route gateway"}
    if is_ap:
        return {"kind": "ap", "source": "role", "reason": "beaconing Wi-Fi AP"}

    hit = _match_services(services)
    if hit:
        return {"kind": hit, "source": "service", "reason": "open service port"}

    hit = _match_snmp(sys_descr)
    if hit:
        return {"kind": hit, "source": "snmp", "reason": "SNMP sysDescr"}

    hit = _match_vendor(vendor)
    if hit:
        return {"kind": hit, "source": "vendor", "reason": f"OUI vendor {vendor}".strip()}

    hit = _match_hostname(hostname)
    if hit:
        return {"kind": hit, "source": "hostname", "reason": f"hostname {hostname}".strip()}

    return None
