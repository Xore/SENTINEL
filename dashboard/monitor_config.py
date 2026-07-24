"""Dashboard-editable outage-monitor configuration.

The outage monitor historically read three root-owned CSVs from /etc
(monitor-targets/services/ports). To make "who to probe" editable from the web
without granting the web process shell/sudo, its configuration now also lives in
ONE JSON file in the shared state directory that BOTH services can reach: the
dashboard and the monitor run as the same `probe-dashboard` user, and the state
directory is the dashboard's only writable path and the monitor's ReadWritePath.

The monitor prefers this JSON when it exists and falls back to the /etc CSVs
otherwise, so an install with no dashboard edits keeps working unchanged. The
monitor hot-reloads it, so edits take effect within a few seconds - no
privileged service restart required.

This module is imported by the dashboard for load/save + validation. The monitor
reads the same file with its own small loader (no import coupling across the two
processes/venvs).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

CONFIG_FILE = Path(os.environ.get("PROBE_MONITOR_CONFIG", "/var/lib/network-probe/monitor-config.json"))

GROUPS = {"wifi-gateway", "eth-gateway", "internal", "external", "ap", "custom"}
SERVICE_KINDS = {"dns", "http", "tcp", "ntp"}

DEFAULTS = {
    "targets": [],
    "services": [],
    "ports": [],
    "ap_monitor": {"enabled": True, "interval": 60},
}


def load() -> dict:
    try:
        stored = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    out = {k: (stored[k] if isinstance(stored.get(k), type(v)) else v) for k, v in DEFAULTS.items()}
    ap = out.get("ap_monitor") or {}
    out["ap_monitor"] = {"enabled": bool(ap.get("enabled", True)),
                         "interval": _clamp_int(ap.get("interval", 60), 20, 3600, 60)}
    return out


def save(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(CONFIG_FILE.parent), prefix=".moncfg-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle, indent=2, sort_keys=True)
        os.chmod(tmp, 0o640)
        os.replace(tmp, CONFIG_FILE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


# --- Validation: return (clean_list, errors) --------------------------------

def _s(value) -> str:
    return str(value or "").strip()


def _enabled(item) -> bool:
    """A probe is curated-in unless explicitly turned off. Absent/true -> enabled;
    only a literal False (from the dashboard's Enabled checkbox) disables it."""
    return item.get("enabled", True) is not False


def _started(item) -> bool:
    """Whether this probe is currently running. Absent -> True so pre-existing
    configs (written before the start/stop toggle existed) keep running; only a
    literal False (from the dashboard's Start/stop toggle) stops it. New probes
    are added with started=False by the UI, so 'default stopped' still holds."""
    return item.get("started", True) is not False


def clean_targets(items) -> tuple[list[dict], list[str]]:
    out, errors, seen = [], [], set()
    for i, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        name, address = _s(item.get("name")), _s(item.get("address"))
        interface, group = _s(item.get("interface")), _s(item.get("group")) or "custom"
        if not name or not address:
            errors.append(f"target #{i+1}: name and address are required")
            continue
        if group not in GROUPS:
            errors.append(f"target '{name}': group must be one of {', '.join(sorted(GROUPS))}")
            continue
        if name in seen:
            errors.append(f"duplicate target name '{name}'")
            continue
        seen.add(name)
        out.append({"name": name, "address": address, "interface": interface,
                    "group": group, "enabled": _enabled(item), "started": _started(item)})
    return out, errors


def clean_services(items) -> tuple[list[dict], list[str]]:
    out, errors, seen = [], [], set()
    for i, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        name, kind, target = _s(item.get("name")), _s(item.get("kind")), _s(item.get("target"))
        if not name or not target:
            errors.append(f"service #{i+1}: name and target are required")
            continue
        if kind not in SERVICE_KINDS:
            errors.append(f"service '{name}': kind must be one of {', '.join(sorted(SERVICE_KINDS))}")
            continue
        if name in seen:
            errors.append(f"duplicate service name '{name}'")
            continue
        seen.add(name)
        out.append({"name": name, "kind": kind, "target": target,
                    "enabled": _enabled(item), "started": _started(item)})
    return out, errors


def clean_ports(items) -> tuple[list[dict], list[str]]:
    out, errors, seen = [], [], set()
    for i, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        name, host = _s(item.get("name")), _s(item.get("host"))
        proto = (_s(item.get("proto")) or "tcp").lower()
        try:
            port = int(item.get("port"))
        except (TypeError, ValueError):
            errors.append(f"port check #{i+1}: numeric port required")
            continue
        if not name or not host:
            errors.append(f"port check #{i+1}: name and host are required")
            continue
        if not 0 < port < 65536:
            errors.append(f"port check '{name}': port out of range")
            continue
        if proto not in ("tcp", "udp"):
            errors.append(f"port check '{name}': proto must be tcp or udp")
            continue
        if name in seen:
            errors.append(f"duplicate port-check name '{name}'")
            continue
        seen.add(name)
        out.append({"name": name, "host": host, "port": port, "proto": proto,
                    "send": _s(item.get("send")), "expect": _s(item.get("expect")),
                    "enabled": _enabled(item), "started": _started(item)})
    return out, errors
