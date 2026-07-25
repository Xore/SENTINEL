"""State-machine tests for the generic privileged reconciler.

No root and no real privileged resource needed: we point the reconciler's env
dirs at a throwaway tree and drop a FAKE applier script that just writes marker
files (and can be told to fail on apply). That exercises every path - apply,
apply-failure -> rollback, confirm -> keep, deadline -> auto-rollback - purely
against the file contract shared by scripts/reconciler.py and dashboard/reconcile.py.

The applier is run as an executable via shebang, which only works on POSIX; those
tests skip on Windows (the daemon is a Linux-only, root component anyway). The
pure file-contract tests (dashboard submit/confirm/revision/name-safety) run
everywhere, including the Windows dev box.

Run:  python -m unittest discover -s tests   (or scripts/run-tests.sh)
"""
from __future__ import annotations

import importlib
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix="probe-reconcile-tests-"))
_DESIRED = _TMP / "desired"
_STATE = _TMP / "state"
_APPLIERS = _TMP / "reconcile.d"
for _d in (_DESIRED, _STATE, _APPLIERS):
    _d.mkdir(parents=True, exist_ok=True)

# Point BOTH sides (daemon + dashboard module) at the temp tree before import.
os.environ.update({
    "PROBE_RECONCILE_DESIRED_DIR": str(_DESIRED),
    "PROBE_RECONCILE_STATE_DIR": str(_STATE),
    "PROBE_RECONCILE_APPLIER_DIR": str(_APPLIERS),
})

sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))
reconciler = importlib.import_module("reconciler")  # scripts/reconciler.py
from dashboard import reconcile as webside  # noqa: E402

_POSIX = os.name == "posix"

# A fake applier: on `apply` it drops a marker file in the resource's actual
# state, snapshots the prior marker, and (if $FAIL_APPLY=1) exits non-zero AFTER
# a partial change so the daemon has something to roll back. `rollback` restores
# the snapshot; `report` prints the current marker as JSON.
_FAKE_APPLIER = """#!/usr/bin/env python3
import json, os, sys
ACTUAL = os.environ["FAKE_ACTUAL"]            # file holding the "live" value
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
def read():
    try:
        with open(ACTUAL) as f: return f.read()
    except OSError: return ""
if cmd == "apply":
    desired_path, snap = sys.argv[2], sys.argv[3]
    with open(desired_path) as f: desired = json.load(f)
    with open(os.path.join(snap, "prev"), "w") as f: f.write(read())   # snapshot
    with open(ACTUAL, "w") as f: f.write(str(desired["payload"].get("value", "")))
    sys.exit(7 if os.environ.get("FAIL_APPLY") == "1" else 0)
if cmd == "rollback":
    snap = sys.argv[2]
    prev = os.path.join(snap, "prev")
    with open(ACTUAL, "w") as f: f.write(open(prev).read() if os.path.exists(prev) else "")
    sys.exit(0)
if cmd == "report":
    print(json.dumps({"value": read()})); sys.exit(0)
sys.exit(2)
"""


class ReconcilerContractTest(unittest.TestCase):
    """Dashboard-side file contract - no privileged applier, runs everywhere."""

    RESOURCE = "contract"

    def setUp(self):
        for p in (_DESIRED, _STATE):
            for f in p.glob(f"{self.RESOURCE}.*"):
                f.unlink()

    def test_submit_bumps_revision(self):
        d1 = webside.submit(self.RESOURCE, {"value": "a"})
        self.assertEqual(d1["revision"], 1)
        d2 = webside.submit(self.RESOURCE, {"value": "b"})
        self.assertEqual(d2["revision"], 2)
        self.assertEqual(webside.get_desired(self.RESOURCE)["payload"]["value"], "b")

    def test_confirm_sets_confirmed_revision(self):
        webside.submit(self.RESOURCE, {"value": "a"}, confirm=True)
        doc = webside.confirm(self.RESOURCE)
        self.assertEqual(doc["confirmed_revision"], doc["revision"])

    def test_confirm_without_desired_raises(self):
        with self.assertRaises(ValueError):
            webside.confirm(self.RESOURCE)

    def test_grace_is_clamped(self):
        lo = webside.submit(self.RESOURCE, {"value": "a"}, confirm=True, grace_seconds=1)
        self.assertGreaterEqual(lo["grace_seconds"], 10)
        hi = webside.submit(self.RESOURCE, {"value": "a"}, confirm=True, grace_seconds=99999)
        self.assertLessEqual(hi["grace_seconds"], 3600)

    def test_state_default_before_daemon_runs(self):
        st = webside.get_state("never-touched")
        self.assertEqual(st["status"], "none")

    def test_bad_names_rejected(self):
        for bad in ("../etc", "a/b", "UPPER", "", "with space"):
            with self.assertRaises(ValueError):
                webside.submit(bad, {"value": "x"})


@unittest.skipUnless(_POSIX, "applier runs as an executable shebang script (POSIX only)")
class ReconcilerStateMachineTest(unittest.TestCase):
    """Full daemon state machine driven through a fake applier."""

    RESOURCE = "demo"

    def setUp(self):
        self.actual = _TMP / "actual.txt"
        self.actual.write_text("original")
        os.environ["FAKE_ACTUAL"] = str(self.actual)
        os.environ.pop("FAIL_APPLY", None)
        self.applier = _APPLIERS / self.RESOURCE
        self.applier.write_text(_FAKE_APPLIER)
        self.applier.chmod(self.applier.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        for p in (_DESIRED, _STATE):
            for f in p.glob(f"{self.RESOURCE}.*"):
                f.unlink()

    def _run(self, now=None):
        return reconciler.reconcile_resource(self.RESOURCE, now=now)

    def test_submit_then_apply(self):
        webside.submit(self.RESOURCE, {"value": "10.0.0.5"})
        st = self._run()
        self.assertEqual(st["status"], "applied")
        self.assertEqual(st["applied_revision"], 1)
        self.assertEqual(self.actual.read_text(), "10.0.0.5")
        self.assertEqual(webside.get_state(self.RESOURCE)["status"], "applied")

    def test_apply_failure_rolls_back(self):
        os.environ["FAIL_APPLY"] = "1"
        webside.submit(self.RESOURCE, {"value": "bad"})
        st = self._run()
        self.assertEqual(st["status"], "failed")
        self.assertEqual(self.actual.read_text(), "original")

    def test_confirm_keeps_change(self):
        webside.submit(self.RESOURCE, {"value": "192.168.1.2"}, confirm=True, grace_seconds=60)
        st = self._run(now=1000)
        self.assertEqual(st["status"], "pending_confirm")
        self.assertEqual(st["deadline"], 1060)
        self.assertTrue(webside.snapshot(self.RESOURCE)["awaiting_confirm"])
        webside.confirm(self.RESOURCE)
        st = self._run(now=1010)
        self.assertEqual(st["status"], "applied")
        self.assertEqual(self.actual.read_text(), "192.168.1.2")

    def test_deadline_auto_rolls_back(self):
        webside.submit(self.RESOURCE, {"value": "10.9.9.9"}, confirm=True, grace_seconds=60)
        st = self._run(now=1000)
        self.assertEqual(st["status"], "pending_confirm")
        self.assertEqual(self.actual.read_text(), "10.9.9.9")
        st = self._run(now=1030)  # still within grace
        self.assertEqual(st["status"], "pending_confirm")
        st = self._run(now=1061)  # past deadline, unconfirmed
        self.assertEqual(st["status"], "rolled_back")
        self.assertEqual(self.actual.read_text(), "original")

    def test_missing_applier_fails_closed(self):
        webside.submit("ghost", {"value": "x"})
        st = reconciler.reconcile_resource("ghost")
        self.assertEqual(st["status"], "failed")
        self.assertIn("no executable applier", st["detail"])

    def test_revision_bumps_and_reapplies(self):
        webside.submit(self.RESOURCE, {"value": "first"})
        self._run()
        doc = webside.submit(self.RESOURCE, {"value": "second"})
        self.assertEqual(doc["revision"], 2)
        st = self._run()
        self.assertEqual(st["applied_revision"], 2)
        self.assertEqual(self.actual.read_text(), "second")


if __name__ == "__main__":
    unittest.main()
