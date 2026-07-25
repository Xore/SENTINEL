"""Dashboard side of the generic privileged reconciler.

The web process never holds root. For any privileged knob, it writes a
*desired-state* JSON file that the root reconciler daemon (scripts/reconciler.py)
enacts, and it reads back the daemon's *result-state* file. This module is that
thin, unprivileged file contract - load / submit (bump revision) / confirm /
read state - shared by every reconciled resource (network settings, and any
future one). It runs no commands and imports nothing privileged.

See scripts/reconciler.py for the daemon and the full file contract.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

DESIRED_DIR = Path(os.environ.get("PROBE_RECONCILE_DESIRED_DIR",
                                  "/var/lib/network-probe/reconcile"))
STATE_DIR = Path(os.environ.get("PROBE_RECONCILE_STATE_DIR",
                                 "/run/network-probe-reconcile"))

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DEFAULT_GRACE = 120


def _valid(name: str) -> None:
    if not NAME_RE.match(name):
        raise ValueError(f"invalid resource name {name!r}")


def desired_path(name: str) -> Path:
    _valid(name)
    return DESIRED_DIR / f"{name}.desired.json"


def state_path(name: str) -> Path:
    _valid(name)
    return STATE_DIR / f"{name}.state.json"


def _read(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + "-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o644)  # no secrets; the daemon reads it
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_desired(name: str) -> dict:
    return _read(desired_path(name), {})


def get_state(name: str) -> dict:
    """The daemon's last result for this resource (status/detail/deadline/...)."""
    return _read(state_path(name), {"status": "none", "applied_revision": 0,
                                    "detail": "reconciler has not run for this resource yet"})


def snapshot(name: str) -> dict:
    """Everything the UI needs in one shot: desired + daemon state + a derived
    `awaiting_confirm` flag with seconds left on the auto-rollback timer."""
    desired = get_desired(name)
    state = get_state(name)
    out = {"resource": name, "desired": desired, "state": state,
           "awaiting_confirm": False, "seconds_left": None}
    if state.get("status") == "pending_confirm" and \
            state.get("applied_revision") == desired.get("revision"):
        out["awaiting_confirm"] = True
        left = int((state.get("deadline") or 0) - time.time())
        out["seconds_left"] = max(0, left)
    return out


def submit(name: str, payload: dict, confirm: bool = False,
           grace_seconds: int = DEFAULT_GRACE) -> dict:
    """Record a new desired state, bumping the monotonic revision so the daemon
    picks it up. `confirm=True` arms the auto-rollback timer - the change reverts
    unless confirm() is called within grace_seconds. Returns the written doc."""
    _valid(name)
    prev = get_desired(name)
    try:
        revision = int(prev.get("revision", 0)) + 1
    except (TypeError, ValueError):
        revision = 1
    doc = {
        "revision": revision,
        "payload": payload,
        "confirm": bool(confirm),
        "grace_seconds": max(10, min(int(grace_seconds), 3600)),
        "confirmed_revision": int(prev.get("confirmed_revision", 0) or 0),
        "requested_at": int(time.time()),
    }
    _write(desired_path(name), doc)
    return doc


def confirm(name: str) -> dict:
    """Keep the currently-applied change: set confirmed_revision to the live
    revision so the daemon cancels the pending auto-rollback."""
    doc = get_desired(name)
    if not doc:
        raise ValueError("nothing to confirm")
    doc["confirmed_revision"] = int(doc.get("revision", 0))
    _write(desired_path(name), doc)
    return doc
