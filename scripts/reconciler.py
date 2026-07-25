#!/usr/bin/env python3
"""Generic privileged reconciler (root daemon).

One small root process that reconciles *actual* system state toward *desired*
state the unprivileged dashboard writes as JSON. It is the general form of the
IDS capture-adapter daemon (scripts/ids-adapter-manager.sh): instead of one
bespoke daemon per privileged knob, a resource just drops an "applier" script in
scripts/reconcile.d/ and the dashboard writes its desired-state file.

Why this exists
---------------
The web process never holds root and never touches a privileged resource. It
only writes desired state; this daemon enacts it. Every apply is guarded:

  * snapshot -> apply -> (applier self-validates) -> record result
  * if apply fails, the daemon rolls back from the snapshot
  * for changes flagged `confirm`, the daemon starts an AUTO-ROLLBACK timer:
    the change reverts itself unless the operator confirms before the deadline.
    This is what makes it safe to reconfigure the network of a box you can only
    reach *over* that network - if you lock yourself out you cannot click
    "keep", so it rolls back and your connection returns.

File contract
-------------
Desired state (dashboard-owned, 0644):
  $PROBE_RECONCILE_DESIRED_DIR/<name>.desired.json
    { "revision": <int, monotonic>,
      "payload": { ... resource-specific ... },
      "confirm": <bool>,          # arm the auto-rollback timer
      "grace_seconds": <int>,     # how long to wait for confirmation
      "confirmed_revision": <int> # operator sets == revision to keep the change
    }

Result state (daemon-owned, world-readable):
  $PROBE_RECONCILE_STATE_DIR/<name>.state.json
    { "resource","status","applied_revision","detail","deadline","actual","updated" }

status is one of:
  none | applied | failed | pending_confirm | rolled_back

Applier contract  (scripts/reconcile.d/<name>, executable):
  <applier> apply    <desired.json> <snapshot_dir>   # snapshot current, enact
  <applier> rollback <snapshot_dir>                  # restore from snapshot
  <applier> report                                   # print actual state JSON (optional)
An applier's `apply` must validate its own change and exit non-zero on failure;
the daemon then rolls it back.

CLI:
  reconciler.py once     # one reconcile pass over every desired file, then exit
  reconciler.py daemon   # loop `once` every tick
  reconciler.py status   # print all resource state as JSON (no root needed)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESIRED_DIR = Path(os.environ.get("PROBE_RECONCILE_DESIRED_DIR",
                                  "/var/lib/network-probe/reconcile"))
STATE_DIR = Path(os.environ.get("PROBE_RECONCILE_STATE_DIR",
                                 "/run/network-probe-reconcile"))
APPLIER_DIR = Path(os.environ.get("PROBE_RECONCILE_APPLIER_DIR", HERE / "reconcile.d"))
SNAP_ROOT = STATE_DIR / "snapshots"
TICK = int(os.environ.get("PROBE_RECONCILE_TICK", "3"))
DEFAULT_GRACE = 120

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")  # no path traversal


def _read_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: dict, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + "-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def desired_path(name: str) -> Path:
    return DESIRED_DIR / f"{name}.desired.json"


def state_path(name: str) -> Path:
    return STATE_DIR / f"{name}.state.json"


def applier_for(name: str) -> Path | None:
    p = APPLIER_DIR / name
    return p if p.is_file() and os.access(p, os.X_OK) else None


def list_resources() -> list[str]:
    if not DESIRED_DIR.is_dir():
        return []
    names = []
    for f in sorted(DESIRED_DIR.glob("*.desired.json")):
        name = f.name[: -len(".desired.json")]
        if NAME_RE.match(name):
            names.append(name)
    return names


def _run_applier(applier: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run([str(applier), *args], capture_output=True,
                              text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return 124, "applier timed out"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def _report(applier: Path):
    rc, out = _run_applier(applier, "report")
    if rc != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def _set_state(name: str, status: str, applied_revision: int, detail: str,
               deadline=None, actual=None, snapshot=None) -> dict:
    state = {
        "resource": name, "status": status,
        "applied_revision": applied_revision, "detail": detail,
        "deadline": deadline, "actual": actual, "snapshot": snapshot,
        "updated": int(time.time()),
    }
    _write_json(state_path(name), state)
    return state


def reconcile_resource(name: str, now: float | None = None) -> dict:
    """Run the state machine for one resource once. Returns its new state.

    Pure enough to unit-test: point the env dirs at temp paths and drop a fake
    applier in APPLIER_DIR."""
    now = time.time() if now is None else now
    desired = _read_json(desired_path(name), {})
    state = _read_json(state_path(name),
                       {"status": "none", "applied_revision": 0, "snapshot": None})
    applier = applier_for(name)
    if applier is None:
        return _set_state(name, "failed", state.get("applied_revision", 0),
                          f"no executable applier at {APPLIER_DIR / name}")

    try:
        revision = int(desired.get("revision", 0))
    except (TypeError, ValueError):
        revision = 0
    applied_rev = int(state.get("applied_revision", 0) or 0)
    status = state.get("status", "none")

    # 1) A newer desired revision than we've enacted -> apply it.
    if revision > applied_rev:
        snap = SNAP_ROOT / name / str(revision)
        if snap.exists():
            shutil.rmtree(snap, ignore_errors=True)
        snap.mkdir(parents=True, exist_ok=True)
        rc, out = _run_applier(applier, "apply", str(desired_path(name)), str(snap))
        if rc != 0:
            _run_applier(applier, "rollback", str(snap))  # best effort
            return _set_state(name, "failed", applied_rev,
                              f"apply failed (rc={rc}): {out[:400]}",
                              actual=_report(applier))
        if desired.get("confirm"):
            try:
                grace = max(10, min(int(desired.get("grace_seconds", DEFAULT_GRACE)), 3600))
            except (TypeError, ValueError):
                grace = DEFAULT_GRACE
            return _set_state(name, "pending_confirm", revision,
                              f"applied revision {revision}; awaiting confirmation",
                              deadline=int(now + grace), actual=_report(applier),
                              snapshot=str(snap))
        return _set_state(name, "applied", revision,
                          f"applied revision {revision}", actual=_report(applier))

    # 2) Waiting on confirmation for the revision we applied.
    if status == "pending_confirm" and applied_rev == revision:
        try:
            confirmed = int(desired.get("confirmed_revision", 0))
        except (TypeError, ValueError):
            confirmed = 0
        if confirmed >= revision:
            return _set_state(name, "applied", revision,
                              f"confirmed revision {revision}", actual=_report(applier))
        if now >= float(state.get("deadline") or 0):
            snap = state.get("snapshot") or str(SNAP_ROOT / name / str(revision))
            _run_applier(applier, "rollback", snap)
            return _set_state(name, "rolled_back", revision,
                              f"revision {revision} not confirmed in time; rolled back",
                              actual=_report(applier))
        # still within grace: leave state as-is (keep ticking)
        return state
    return state


def reconcile_once() -> list[dict]:
    return [reconcile_resource(name) for name in list_resources()]


def status_blob() -> dict:
    out = {}
    for name in list_resources():
        out[name] = {
            "desired": _read_json(desired_path(name), {}),
            "state": _read_json(state_path(name), {"status": "none"}),
        }
    return out


def _need_root() -> None:
    if os.geteuid() != 0:  # type: ignore[attr-defined]
        sys.exit("reconciler: must run as root")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "status"
    if cmd == "once":
        _need_root()
        for st in reconcile_once():
            print(f"{st['resource']}: {st['status']} — {st['detail']}")
        return 0
    if cmd == "daemon":
        _need_root()
        print(f"reconciler: daemon started (desired: {DESIRED_DIR}, tick: {TICK}s)")
        while True:
            try:
                reconcile_once()
            except Exception as exc:  # never let one bad unit kill the loop
                print(f"reconciler: pass error: {exc}", file=sys.stderr)
            time.sleep(TICK)
    if cmd == "status":
        print(json.dumps(status_blob(), indent=2))
        return 0
    sys.exit(f"reconciler: unknown command '{cmd}' (once|daemon|status)")


if __name__ == "__main__":
    raise SystemExit(main())
