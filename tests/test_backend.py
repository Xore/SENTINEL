"""Backend regression suite for the Network Probe dashboard.

Stdlib unittest only (no pytest) so it runs against the app venv with zero extra
installs. Every test runs against ISOLATED temp state: all of the app's state
paths are env-configurable and are pointed at a throwaway directory here, BEFORE
dashboard.app is imported (those paths are read at import time). Auth is disabled
by pointing the token file at a nonexistent path.

Focus: the multi-collector / signed-update surface added for collector nodes,
plus a smoke test of the /api/map assembler.

Run:  python -m unittest discover -s tests   (or scripts/run-tests.sh)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# --- isolate ALL state before importing the app --------------------------------
_TMP = Path(tempfile.mkdtemp(prefix="probe-tests-"))
_DIST = _TMP / "dist"
_DIST.mkdir()
# A fake release the aggregator can "hand out" and sign for.
_BIN = _DIST / "collector-linux-amd64"
_BIN.write_bytes(b"\x7fELF fake collector binary for tests")
(_DIST / "manifest.json").write_text(json.dumps(
    {"version": "9.9.9", "files": {"linux/amd64": "collector-linux-amd64"}}))

os.environ.update({
    "PROBE_WEB_DB": str(_TMP / "web.db"),
    "PROBE_SETTINGS_FILE": str(_TMP / "settings.json"),
    "PROBE_MONITOR_DB": str(_TMP / "monitor.db"),
    "PROBE_MONITOR_CONFIG": str(_TMP / "monitor-config.json"),
    "PROBE_COLLECTOR_DIST": str(_DIST),
    "PROBE_AUTH_TOKEN_FILE": str(_TMP / "no-such-token"),  # -> auth disabled
    "PROBE_RECONCILE_DESIRED_DIR": str(_TMP / "reconcile-desired"),
    "PROBE_RECONCILE_STATE_DIR": str(_TMP / "reconcile-state"),
})

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import app as appmod  # noqa: E402

# reconcile caches its dirs at import; pin them to ours regardless of the order
# test modules got imported in (test_reconciler uses a different temp tree).
appmod.reconcile.DESIRED_DIR = Path(os.environ["PROBE_RECONCILE_DESIRED_DIR"])
appmod.reconcile.STATE_DIR = Path(os.environ["PROBE_RECONCILE_STATE_DIR"])


def sign(secret: str, version: str, os_arch: str, sha256hex: str) -> str:
    msg = f"{version}\n{os_arch}\n{sha256hex}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.c = appmod.app.test_client()
        # State lives in shared temp files, so isolate each test: start every one
        # with the master switch off (tests that need it on flip it explicitly).
        self._accept_external(False)

    # --- multinode toggle ------------------------------------------------------
    def test_multinode_default_off(self):
        r = self.c.get("/api/multinode").get_json()
        self.assertEqual(r["role"], "standalone")
        self.assertFalse(r["accept_external_collectors"])

    def _accept_external(self, on=True):
        return self.c.post("/api/multinode", json={"accept_external_collectors": on})

    def test_ingest_refused_when_toggle_off(self):
        self._accept_external(False)
        # even a syntactically fine heartbeat is refused with the master switch off
        r = self.c.post("/api/ingest/heartbeat", json={"version": "0.1.0"},
                        headers={"X-Ingest-Key": "whatever"})
        self.assertEqual(r.status_code, 403)

    # --- enrollment / key lifecycle -------------------------------------------
    def test_enroll_returns_key_and_secret_once(self):
        r = self.c.post("/api/collectors", json={"name": "unit-a"})
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertTrue(body["key"])
        self.assertTrue(body["update_secret"])
        # the listing must never leak key material or the signing secret
        lst = self.c.get("/api/collectors").get_json()
        row = next(x for x in lst["collectors"] if x["collector_id"] == body["collector_id"])
        self.assertNotIn("update_secret", row)
        self.assertNotIn("key", row)

    def test_key_auth_enroll_revoke_rotate(self):
        self._accept_external(True)
        body = self.c.post("/api/collectors", json={"name": "unit-b"}).get_json()
        cid, key = body["collector_id"], body["key"]

        ok = self.c.post("/api/ingest/heartbeat", json={"version": "0.1.0"},
                         headers={"X-Ingest-Key": key})
        self.assertEqual(ok.status_code, 200)

        bad = self.c.post("/api/ingest/heartbeat", json={"version": "0.1.0"},
                          headers={"X-Ingest-Key": "wrong"})
        self.assertEqual(bad.status_code, 401)

        # revoke -> old key rejected
        self.c.post(f"/api/collectors/{cid}/revoke")
        self.assertEqual(self.c.post("/api/ingest/heartbeat", json={"version": "0.1.0"},
                                     headers={"X-Ingest-Key": key}).status_code, 401)

        # rotate -> brand new key works, and is different
        new = self.c.post(f"/api/collectors/{cid}/rotate").get_json()
        self.assertNotEqual(new["key"], key)
        self.assertEqual(self.c.post("/api/ingest/heartbeat", json={"version": "0.1.0"},
                                     headers={"X-Ingest-Key": new["key"]}).status_code, 200)

    # --- check plan delivery ---------------------------------------------------
    def test_ingest_checks_reflects_monitor_config(self):
        self._accept_external(True)
        key = self.c.post("/api/collectors", json={"name": "unit-c"}).get_json()["key"]
        self.c.put("/api/monitor/config", json={
            "targets": [{"name": "gw", "address": "192.168.1.1", "group": "internal",
                         "enabled": True, "started": True}],
            "ports": [{"name": "ssh", "host": "192.168.1.1", "port": 22, "proto": "tcp",
                       "enabled": True, "started": True}],
        })
        plan = self.c.get("/api/ingest/checks", headers={"X-Ingest-Key": key}).get_json()
        self.assertEqual([t["name"] for t in plan["targets"]], ["gw"])
        self.assertEqual([p["port"] for p in plan["ports"]], [22])

    def test_ingest_checks_needs_key(self):
        self._accept_external(True)
        self.assertEqual(self.c.get("/api/ingest/checks").status_code, 401)

    # --- the security core: signed self-update --------------------------------
    def test_update_instruction_is_correctly_signed(self):
        self._accept_external(True)
        body = self.c.post("/api/collectors", json={"name": "unit-upd"}).get_json()
        cid, key, secret = body["collector_id"], body["key"], body["update_secret"]

        # operator requests the update; a release (9.9.9) exists in the temp dist
        req = self.c.post(f"/api/collectors/{cid}/update")
        self.assertEqual(req.status_code, 200)
        self.assertEqual(req.get_json()["target_version"], "9.9.9")

        # heartbeat from an OLD version on linux/amd64 -> signed update offered
        hb = self.c.post("/api/ingest/heartbeat",
                         json={"version": "0.0.1", "meta": {"os": "linux", "arch": "amd64"}},
                         headers={"X-Ingest-Key": key}).get_json()
        upd = hb.get("update")
        self.assertIsNotNone(upd, "expected an update instruction")
        self.assertEqual(upd["version"], "9.9.9")

        expected_sha = hashlib.sha256(_BIN.read_bytes()).hexdigest()
        self.assertEqual(upd["sha256"], expected_sha)
        self.assertEqual(upd["sig"], sign(secret, "9.9.9", "linux/amd64", expected_sha),
                         "backend signature must match the shared-secret HMAC the agent verifies")

    def test_no_update_when_not_requested(self):
        self._accept_external(True)
        key = self.c.post("/api/collectors", json={"name": "unit-noupd"}).get_json()["key"]
        hb = self.c.post("/api/ingest/heartbeat",
                         json={"version": "0.0.1", "meta": {"os": "linux", "arch": "amd64"}},
                         headers={"X-Ingest-Key": key}).get_json()
        self.assertNotIn("update", hb)

    def test_binary_served_only_with_key(self):
        self._accept_external(True)
        key = self.c.post("/api/collectors", json={"name": "unit-bin"}).get_json()["key"]
        self.assertEqual(self.c.get("/api/ingest/binary?os=linux&arch=amd64").status_code, 401)
        ok = self.c.get("/api/ingest/binary?os=linux&arch=amd64",
                        headers={"X-Ingest-Key": key})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data, _BIN.read_bytes())
        # unknown platform -> 404, and no path traversal
        self.assertEqual(self.c.get("/api/ingest/binary?os=linux&arch=sparc",
                                    headers={"X-Ingest-Key": key}).status_code, 404)

    # --- Wi-Fi spectrum / interference model -----------------------------------
    def test_spectrum_model(self):
        from monitor.wifi_survey import spectrum
        # Three APs crowd 2.4 GHz ch6; ch1/ch11 stay clear, so 2.4 should be
        # recommended toward 1 or 11, never 6.
        aps = [
            {"band": "2.4 GHz", "channel": 6, "signal_dbm": -40, "ssid": "A"},
            {"band": "2.4 GHz", "channel": 6, "signal_dbm": -50, "ssid": "B"},
            {"band": "2.4 GHz", "channel": 5, "signal_dbm": -55, "ssid": "C"},
            {"band": "5 GHz", "channel": 36, "signal_dbm": -60, "ssid": "D"},
        ]
        s = spectrum(aps)
        b24 = next(b for b in s["bands"] if b["band"] == "2.4 GHz")
        self.assertIn(b24["recommend"]["channel"], (1, 11))
        self.assertNotEqual(b24["recommend"]["channel"], 6)
        # ch6 slot must carry more occupancy than ch1 (which no AP overlaps).
        occ = {r["channel"]: r["occupancy"] for r in b24["channels"]}
        self.assertGreater(occ[6], occ[1])
        # 5 GHz was heard, so it appears as its own band.
        self.assertTrue(any(b["band"] == "5 GHz" for b in s["bands"]))

    def test_spectrum_empty(self):
        from monitor.wifi_survey import spectrum
        self.assertEqual(spectrum([])["bands"], [])

    # --- network settings via the reconciler -----------------------------------
    def _fake_nics(self):
        # interfaces() reads /sys/class/net (empty off-Linux), so give the
        # validator a real-looking NIC to accept.
        appmod._network_ifaces = lambda: [
            {"name": "wlp2s0", "up": True, "wired": False, "addresses": "192.168.50.32/24"},
        ]

    def test_network_default_state(self):
        r = self.c.get("/api/network").get_json()
        self.assertEqual(r["state"]["status"], "none")
        self.assertFalse(r["awaiting_confirm"])

    def test_network_rejects_unknown_iface(self):
        self._fake_nics()
        r = self.c.post("/api/network", json={"interface": "eth9", "method": "auto"})
        self.assertEqual(r.status_code, 400)

    def test_network_manual_requires_valid_address(self):
        self._fake_nics()
        r = self.c.post("/api/network",
                        json={"interface": "wlp2s0", "method": "manual",
                              "address": "not-an-ip", "prefix": 24})
        self.assertEqual(r.status_code, 400)

    def test_network_submit_is_confirm_armed(self):
        self._fake_nics()
        r = self.c.post("/api/network",
                        json={"interface": "wlp2s0", "method": "auto"})
        self.assertEqual(r.status_code, 200)
        # The written desired doc must always arm auto-rollback.
        desired = appmod.reconcile.get_desired("network")
        self.assertTrue(desired["confirm"])
        self.assertEqual(desired["payload"]["method"], "auto")
        self.assertGreaterEqual(desired["revision"], 1)

    def test_network_confirm_sets_confirmed_revision(self):
        self._fake_nics()
        self.c.post("/api/network",
                    json={"interface": "wlp2s0", "method": "manual",
                          "address": "192.168.50.40", "prefix": 24,
                          "gateway": "192.168.50.1", "dns": "1.1.1.1, 8.8.8.8"})
        desired = appmod.reconcile.get_desired("network")
        self.assertEqual(desired["payload"]["dns"], ["1.1.1.1", "8.8.8.8"])
        r = self.c.post("/api/network/confirm").get_json()
        self.assertEqual(appmod.reconcile.get_desired("network")["confirmed_revision"],
                         desired["revision"])

    # --- map assembler smoke ---------------------------------------------------
    def test_map_returns_graph_with_self(self):
        r = self.c.get("/api/map")
        self.assertEqual(r.status_code, 200)
        g = r.get_json()
        for field in ("nodes", "edges"):
            self.assertIn(field, g)
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn("self", ids)


if __name__ == "__main__":
    unittest.main()
