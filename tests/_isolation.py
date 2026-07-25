"""Shared test isolation: set EVERY app state path to a throwaway temp tree.

dashboard.app reads its state paths (dbs, settings, collector dist, reconcile
dirs, auth file) into module constants at IMPORT time. Whichever test module
imports the app first fixes those, so all of them must agree on the same env.
Import this module BEFORE importing dashboard.app in every test file:

    import _isolation  # noqa: F401  (sets env; must precede the app import)

It does not touch PROBE_AUTH_DISABLED - each test pins appmod.AUTH_DISABLED in
setUp (test_backend off, test_auth on), which is what actually gates auth.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="probe-tests-"))
DIST = TMP / "dist"
DIST.mkdir()
# A fake release the aggregator can "hand out" and sign for.
BIN = DIST / "collector-linux-amd64"
BIN.write_bytes(b"\x7fELF fake collector binary for tests")
(DIST / "manifest.json").write_text(json.dumps(
    {"version": "9.9.9", "files": {"linux/amd64": "collector-linux-amd64"}}))

AUTH_FILE = TMP / "dashboard-auth.json"

os.environ.update({
    "PROBE_WEB_DB": str(TMP / "web.db"),
    "PROBE_SETTINGS_FILE": str(TMP / "settings.json"),
    "PROBE_MONITOR_DB": str(TMP / "monitor.db"),
    "PROBE_MONITOR_CONFIG": str(TMP / "monitor-config.json"),
    "PROBE_COLLECTOR_DIST": str(DIST),
    "PROBE_AUTH_TOKEN_FILE": str(TMP / "no-such-token"),  # legacy, ignored now
    "PROBE_AUTH_FILE": str(AUTH_FILE),
    "PROBE_RECONCILE_DESIRED_DIR": str(TMP / "reconcile-desired"),
    "PROBE_RECONCILE_STATE_DIR": str(TMP / "reconcile-state"),
    "PROBE_ALERT_STATE": str(TMP / "alert-state.json"),
})


def sign(secret: str, version: str, os_arch: str, sha256hex: str) -> str:
    msg = f"{version}\n{os_arch}\n{sha256hex}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
