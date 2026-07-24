"""Dashboard-editable IDS capture-adapter configuration.

Suricata's capture interface(s) are chosen by a small root daemon
(scripts/ids-adapter-manager.sh) that re-reads a JSON config every cycle and
enacts it - validating the rewritten suricata.yaml with `suricata -T` and
rolling back on failure. That config lives in the shared state directory and is
owned by the `probe-dashboard` account, so the website can edit it directly
without the web process ever touching Suricata or holding root:

    /var/lib/network-probe/ids-adapter.json
      { "mode": "auto|all|manual", "interfaces": [..], "recheck_seconds": N }

The reconciler pattern: the (unprivileged) dashboard writes *desired state*, the
(root) daemon reconciles the *actual* Suricata config toward it. This module is
the dashboard side - load, validate, atomic-write. It never runs Suricata.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

CONFIG_FILE = Path(os.environ.get(
    "PROBE_IDS_ADAPTER_CONFIG", "/var/lib/network-probe/ids-adapter.json"))

MODES = {"auto", "all", "manual"}
MIN_RECHECK, MAX_RECHECK, DEFAULT_RECHECK = 10, 86400, 60

DEFAULTS = {"mode": "auto", "interfaces": [], "recheck_seconds": DEFAULT_RECHECK}


def _clamp_int(value, low: int, high: int, fallback: int) -> int:
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return fallback


def load() -> dict:
    """Current desired-state config, normalised. Tolerates the legacy single
    `interface` string schema so an older config still reads cleanly."""
    try:
        stored = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    mode = stored.get("mode")
    mode = mode if mode in MODES else "auto"
    ifaces = stored.get("interfaces")
    if not isinstance(ifaces, list):
        one = str(stored.get("interface") or "").strip()  # legacy schema
        ifaces = [one] if one else []
    ifaces = [str(x).strip() for x in ifaces if str(x).strip()]
    return {
        "mode": mode,
        "interfaces": ifaces,
        "recheck_seconds": _clamp_int(stored.get("recheck_seconds", DEFAULT_RECHECK),
                                      MIN_RECHECK, MAX_RECHECK, DEFAULT_RECHECK),
    }


def validate(payload: dict, valid_names: set[str]) -> tuple[dict, list[str]]:
    """Turn a raw request body into a clean config. `valid_names` is the set of
    real NIC names on this host - `manual` mode may only name those."""
    errors: list[str] = []
    mode = str(payload.get("mode", "auto")).strip().lower()
    if mode not in MODES:
        errors.append(f"mode must be one of {sorted(MODES)}")
        mode = "auto"

    raw = payload.get("interfaces", [])
    if not isinstance(raw, list):
        errors.append("interfaces must be a list")
        raw = []
    # De-dupe, preserve order.
    seen: set[str] = set()
    ifaces: list[str] = []
    for item in raw:
        name = str(item).strip()
        if not name or name in seen:
            continue
        if name not in valid_names:
            errors.append(f"unknown interface '{name}'")
            continue
        seen.add(name)
        ifaces.append(name)

    if mode == "manual" and not ifaces:
        errors.append("manual mode needs at least one interface")

    recheck = _clamp_int(payload.get("recheck_seconds", DEFAULT_RECHECK),
                         MIN_RECHECK, MAX_RECHECK, DEFAULT_RECHECK)
    # auto/all ignore the interface list; keep it tidy so the file reflects intent.
    if mode != "manual":
        ifaces = []
    return {"mode": mode, "interfaces": ifaces, "recheck_seconds": recheck}, errors


def save(cfg: dict) -> None:
    """Atomically replace the config. Works even if the existing file is
    root-owned: the state dir is owned by this account, so the rename succeeds."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(CONFIG_FILE.parent), prefix=".ids-adapter-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o644)  # no secrets; the daemon + desktop selector read it
        os.replace(tmp, CONFIG_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
