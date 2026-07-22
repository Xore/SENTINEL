"""Persistent, dashboard-editable settings for the probe.

The dashboard runs unprivileged (`probe-dashboard`) under a hardened systemd
unit whose only writable path is the state directory. So operator-editable
configuration lives in ONE JSON file there, written atomically with 0600
permissions (it can hold SNMP credentials).

Everything the UI can change persists here: SNMP credentials, per-interface
capture overrides, and dashboard-added approved-scope endpoints. Operator files
that ship read-only in /etc (targets.csv, allow-lists) are still honoured and
merged on top - this store only ever *adds* to them.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SETTINGS_FILE = Path(os.environ.get("PROBE_SETTINGS_FILE", "/var/lib/network-probe/settings.json"))

DEFAULTS: dict = {
    "snmp": {
        "version": "2c",          # "2c" | "3"
        "community": "",          # v2c read community (secret)
        "timeout": 3,
        "retries": 1,
        "v3": {
            "user": "",
            "level": "authPriv",   # noAuthNoPriv | authNoPriv | authPriv
            "auth_proto": "SHA",   # MD5 | SHA | SHA-256 ...
            "auth_key": "",        # secret
            "priv_proto": "AES",   # DES | AES | AES-256 ...
            "priv_key": "",        # secret
        },
    },
    # iface name -> {"capture_allowed": bool}. Lets the operator opt an
    # interface (even one carrying an IP) into capture/monitor use.
    "interface_overrides": {},
    # Dashboard-added approved endpoints, merged with the read-only targets.csv.
    "approved_scope": [],
    # Dashboard-added traffic-generator destinations, merged with the read-only
    # /etc allow-list. Each entry: {"host","port","proto"}. Sending payloads is
    # an active action, so it stays allow-list-gated - but the list is now
    # operator-editable from the dashboard instead of only /etc.
    "traffic_allow": [],
}

# Dotted paths whose values are secrets: never returned to the browser in the
# clear (replaced with a boolean "<field>_set").
SECRET_PATHS = ("snmp.community", "snmp.v3.auth_key", "snmp.v3.priv_key")


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            out[key] = _merge(base[key], value)
        else:
            out[key] = value
    return out


def load() -> dict:
    """Full settings dict (defaults merged with the stored file)."""
    try:
        stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    return _merge(DEFAULTS, stored if isinstance(stored, dict) else {})


def save(settings: dict) -> None:
    """Atomically persist settings with owner-only permissions."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(SETTINGS_FILE.parent), prefix=".settings-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, SETTINGS_FILE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _walk(obj: dict, dotted: str):
    node, *rest = dotted.split(".")
    if node not in obj:
        return None, None
    if rest:
        return _walk(obj[node], ".".join(rest)) if isinstance(obj[node], dict) else (None, None)
    return obj, node


def redacted() -> dict:
    """Settings safe to send to the browser: secrets become '<name>_set' bools."""
    data = load()
    for path in SECRET_PATHS:
        parent, key = _walk(data, path)
        if parent is None:
            continue
        parent[f"{key}_set"] = bool(parent.get(key))
        parent[key] = ""
    return data


def apply_update(incoming: dict) -> dict:
    """Merge a partial UI update over the stored settings and persist it.

    Empty-string secret fields are treated as 'leave unchanged' so the browser
    can submit the form without knowing the current secret. Returns the new
    redacted settings.
    """
    current = load()
    merged = _merge(current, incoming or {})
    # Preserve existing secrets when the update left them blank.
    for path in SECRET_PATHS:
        cur_parent, key = _walk(current, path)
        new_parent, _ = _walk(merged, path)
        if new_parent is not None and not new_parent.get(key) and cur_parent:
            new_parent[key] = cur_parent.get(key, "")
    save(merged)
    return redacted()
