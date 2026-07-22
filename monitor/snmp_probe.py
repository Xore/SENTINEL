"""Single-target, read-only SNMP identity probe for the network probe.

Reads a small, standard set of SNMP OIDs from ONE device using credentials
stored by the dashboard (settings.json). It wraps the net-snmp CLI tools
(snmpget/snmpwalk from the `snmp` package) so there is no extra Python
dependency, and it is deliberately NOT a sweep: one host, a bounded OID list,
a short timeout, read (GET) only.

Safety: SNMP reads are low-impact but still touch a device. Point this at
infrastructure you are authorised to query; do not walk large OT trees on a
production line without a change window. There is no SET path here.

CLI (used by the dashboard):
  snmp_probe.py --host 10.0.255.1 --settings /var/lib/network-probe/settings.json [--interfaces]
Prints a JSON summary on stdout.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

# System group identity OIDs (RFC 1213 / SNMPv2-MIB), numeric to avoid needing MIBs.
SYS_OIDS = {
    "sysDescr": "1.3.6.1.2.1.1.1.0",
    "sysObjectID": "1.3.6.1.2.1.1.2.0",
    "sysUpTime": "1.3.6.1.2.1.1.3.0",
    "sysContact": "1.3.6.1.2.1.1.4.0",
    "sysName": "1.3.6.1.2.1.1.5.0",
    "sysLocation": "1.3.6.1.2.1.1.6.0",
}
IFDESCR = "1.3.6.1.2.1.2.2.1.2"   # ifDescr column (interface names)


def _auth_args(snmp: dict) -> list[str] | None:
    """Build net-snmp version/credential arguments from stored settings."""
    version = str(snmp.get("version", "2c"))
    timeout = str(int(snmp.get("timeout", 3)))
    retries = str(int(snmp.get("retries", 1)))
    common = ["-t", timeout, "-r", retries]
    if version in ("1", "2c"):
        community = snmp.get("community", "")
        if not community:
            return None
        return ["-v", version, "-c", community, *common]
    v3 = snmp.get("v3", {})
    user = v3.get("user", "")
    if not user:
        return None
    level = v3.get("level", "authPriv")
    args = ["-v", "3", "-u", user, "-l", level, *common]
    if level in ("authNoPriv", "authPriv"):
        args += ["-a", v3.get("auth_proto", "SHA"), "-A", v3.get("auth_key", "")]
    if level == "authPriv":
        args += ["-x", v3.get("priv_proto", "AES"), "-X", v3.get("priv_key", "")]
    return args


def _get(auth: list[str], host: str, oid: str) -> str | None:
    try:
        result = subprocess.run(["snmpget", "-Oqv", *auth, host, oid],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip().strip('"')
    return value or None


def _walk_ifaces(auth: list[str], host: str) -> list[str]:
    try:
        result = subprocess.run(["snmpwalk", "-Oqv", *auth, host, IFDESCR],
                                capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip().strip('"') for line in result.stdout.splitlines() if line.strip()][:64]


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only single-host SNMP identity probe.")
    ap.add_argument("--host", required=True)
    ap.add_argument("--settings", required=True)
    ap.add_argument("--interfaces", action="store_true", help="also walk ifDescr")
    args = ap.parse_args()

    if not shutil.which("snmpget"):
        json.dump({"status": "unavailable", "note": "net-snmp tools not installed (apt install snmp)."}, sys.stdout)
        return 0
    try:
        snmp = json.loads(open(args.settings, encoding="utf-8").read()).get("snmp", {})
    except (OSError, ValueError):
        snmp = {}
    auth = _auth_args(snmp)
    if auth is None:
        json.dump({"status": "no_credentials",
                   "note": "Set SNMP credentials in Settings first (community for v2c, or a v3 user)."}, sys.stdout)
        return 0

    system = {name: _get(auth, args.host, oid) for name, oid in SYS_OIDS.items()}
    reachable = any(v is not None for v in system.values())
    result = {
        "status": "ok" if reachable else "no_response",
        "host": args.host,
        "version": snmp.get("version", "2c"),
        "system": system,
        "note": "" if reachable else "No SNMP response (wrong community/credentials, filtered, or SNMP disabled).",
    }
    if reachable and args.interfaces:
        result["interfaces"] = _walk_ifaces(auth, args.host)
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
