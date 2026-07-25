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
import re
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
    # Operator-defined custom services (named ports), merged into the known
    # IT/OT service catalogue for the Actions pickers. Each entry:
    # {"name","port","proto","category":"custom"}.
    "custom_services": [],
    # Dashboard-added traffic-generator destinations, merged with the read-only
    # /etc allow-list. Each entry: {"host","port","proto"}. Sending payloads is
    # an active action, so it stays allow-list-gated - but the list is now
    # operator-editable from the dashboard instead of only /etc.
    "traffic_allow": [],
    # Multi-node role + the master switch for accepting pushed data from remote
    # collectors. Per-collector keys are enrolled/revoked separately and stored
    # (hashed) in the history DB, not here. A standalone node is self-sufficient
    # and MAY act as the aggregator others push to; that ingest is off until the
    # operator turns this on.
    "multinode": {
        "role": "standalone",                 # standalone | collector
        "accept_external_collectors": False,
    },
    # Operator device tags for the network map (task #39): manual overrides that
    # win over the automatic classifier. Keyed by map node id (an IP, "mac:..",
    # etc). Each value: {"kind","label","notes","tags":[...]}. Any subset of
    # fields may be set; empty/omitted fields fall back to the inferred value.
    "device_tags": {},
    # Prometheus/OpenMetrics scrape endpoint (task #52, roadmap P4). Off by
    # default: /metrics returns 404 until enabled. If `token` is set, a scraper
    # must present it as `Authorization: Bearer <token>` (never in the URL).
    "metrics": {
        "enabled": False,
        "token": "",   # secret; optional bearer token gating /metrics
    },
    # Sustained-state alerting (task #53, roadmap P4). Off by default. A
    # background evaluator watches the trend verdicts from task #50 (TCP
    # retransmit, DNS failure) and open outage events, and notifies once per
    # transition - when a signal crosses UP into the alerting band (>= min_state)
    # and again when it recovers. Deliberately edge-triggered on the
    # sustained-vs-spike classification, so a single spike never pages anyone.
    "alerting": {
        "enabled": False,
        "min_state": "rising",       # spike | rising | degraded - alert at/above this
        "poll_seconds": 60,          # how often the evaluator runs
        "window_minutes": 60,        # trend look-back handed to the analysers
        "signals": {                 # which signals to watch
            "tcp_retransmit": True,
            "dns_failure": True,
            "outage": True,
        },
        "webhook": {
            "enabled": False,
            "url": "",               # POST target for a JSON alert payload
        },
        "email": {
            "enabled": False,
            "smtp_host": "",
            "smtp_port": 587,
            "use_tls": True,
            "username": "",
            "password": "",          # secret; SMTP auth password (replayed, not hashed)
            "from_addr": "",
            "to_addrs": "",          # comma-separated recipients
        },
    },
    # Roadmap P5 - explicitly excluded-by-default capabilities (task #55). This
    # is a safety governance gate, NOT an attack toolkit: the master switch and
    # the per-action flags below are all off, and even when turned on the probe
    # does NOT perform the destructive technique - deauth/injection/exploit/
    # credential-guessing/PLC-writes remain unimplemented by design. Turning a
    # flag on only records acknowledged intent (audited) and unhides the item;
    # the runtime still refuses to execute it. Keeps these behaviours visibly
    # excluded rather than silently absent.
    "dangerous_actions": {
        "enabled": False,          # master switch; all items stay hidden until on
        "acknowledged": {},        # per-action-id: operator ticked the warning box
    },
}

# Dotted paths whose values are secrets: never returned to the browser in the
# clear (replaced with a boolean "<field>_set").
SECRET_PATHS = ("snmp.community", "snmp.v3.auth_key", "snmp.v3.priv_key",
                "metrics.token", "alerting.email.password")


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


# Map-node ids are IPs, "mac:..", "subnet:..", "lldp:..", "internet", "self".
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/\-]{0,127}$")
# Kinds an operator may assign by hand (mirrors the map's node kinds).
TAG_KINDS = {
    "router", "switch", "ap", "firewall", "server", "workstation",
    "printer", "phone", "camera", "iot", "host", "unknown",
}


def get_device_tags() -> dict:
    """All operator device tags, keyed by node id."""
    tags = load().get("device_tags", {})
    return tags if isinstance(tags, dict) else {}


def set_device_tag(node_id: str, *, kind: str = "", label: str = "",
                   notes: str = "", tags=None) -> dict:
    """Create or update one node's manual tag. Empty fields are dropped so a
    partially-tagged node still falls back to inferred values. Returns the
    stored entry. Raises ValueError on a bad node id or unknown kind."""
    node_id = (node_id or "").strip()
    if not _NODE_ID_RE.match(node_id):
        raise ValueError("invalid node id")
    kind = (kind or "").strip().lower()
    if kind and kind not in TAG_KINDS:
        raise ValueError("unknown device kind")
    entry: dict = {}
    if kind:
        entry["kind"] = kind
    if (label or "").strip():
        entry["label"] = label.strip()[:80]
    if (notes or "").strip():
        entry["notes"] = notes.strip()[:500]
    clean_tags = [t.strip()[:40] for t in (tags or []) if isinstance(t, str) and t.strip()]
    if clean_tags:
        entry["tags"] = clean_tags[:20]

    current = load()
    store = current.get("device_tags")
    if not isinstance(store, dict):
        store = {}
    if entry:
        store[node_id] = entry
    else:
        store.pop(node_id, None)  # clearing every field removes the tag
    current["device_tags"] = store
    save(current)
    return entry


def delete_device_tag(node_id: str) -> bool:
    """Remove one node's manual tag. Returns True if something was removed."""
    current = load()
    store = current.get("device_tags")
    if not isinstance(store, dict) or node_id not in store:
        return False
    store.pop(node_id, None)
    current["device_tags"] = store
    save(current)
    return True


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
