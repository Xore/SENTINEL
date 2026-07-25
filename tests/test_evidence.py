"""Tests for freeze-evidence bundles (task #47).

Two layers, stdlib unittest:
  1. dashboard.evidence — the pure manifest/digest/disk-reserve/rotation policy,
     fed synthetic inputs (no disk, no Flask).
  2. /api/evidence/* — the endpoints on dashboard.app against a synthetic
     monitor.db, writing to a throwaway bundle dir. _isolation must import
     before dashboard.app.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolation  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard import app as appmod  # noqa: E402
from dashboard import evidence  # noqa: E402


# --------------------------------------------------------------------------- #
# Pure module: dashboard.evidence
# --------------------------------------------------------------------------- #
class BundleIdTests(unittest.TestCase):
    def test_bundle_id_shape_and_sortability(self):
        a = evidence.bundle_id(1000.0, "abc123")
        b = evidence.bundle_id(2000.0, "def456")
        self.assertTrue(a.startswith("evidence-"))
        self.assertTrue(evidence.is_valid_bundle_id(a))
        self.assertTrue(evidence.is_valid_bundle_id(b))
        self.assertLess(a, b)  # lexical order tracks time

    def test_bundle_id_sanitises_nonce(self):
        bid = evidence.bundle_id(1000.0, "../../etc/passwd")
        self.assertTrue(evidence.is_valid_bundle_id(bid))
        self.assertNotIn("/", bid)
        self.assertNotIn(".", bid.split("-")[-1])

    def test_empty_nonce_gets_placeholder(self):
        bid = evidence.bundle_id(1000.0, "")
        self.assertTrue(evidence.is_valid_bundle_id(bid))

    def test_invalid_ids_rejected(self):
        for bad in ("", "evidence", "../evil", "evidence-bad",
                    "evidence-20260101T000000Z-", "evidence-20260101T000000Z-toolongnonce123",
                    "other-20260101T000000Z-abc"):
            self.assertFalse(evidence.is_valid_bundle_id(bad), bad)


class ManifestTests(unittest.TestCase):
    def test_manifest_hashes_and_digest(self):
        files = {"b.json": b"world", "a.json": b"hello"}
        m = evidence.build_manifest("evidence-x", 1000.0, files, {"note": "hi"})
        self.assertEqual(set(m["files"]), {"a.json", "b.json"})
        self.assertEqual(m["files"]["a.json"]["bytes"], 5)
        self.assertEqual(m["files"]["a.json"]["sha256"], evidence.sha256_hex(b"hello"))
        self.assertEqual(len(m["bundle_digest"]), 64)
        self.assertEqual(m["meta"], {"note": "hi"})

    def test_verify_roundtrips(self):
        files = {"t.json": b"data", "r.json": b"more"}
        m = evidence.build_manifest("evidence-x", 1000.0, files)
        self.assertTrue(evidence.verify_manifest(m, files))

    def test_verify_detects_tamper(self):
        files = {"t.json": b"data"}
        m = evidence.build_manifest("evidence-x", 1000.0, files)
        self.assertFalse(evidence.verify_manifest(m, {"t.json": b"tampered"}))

    def test_verify_detects_missing_or_extra_file(self):
        files = {"t.json": b"data"}
        m = evidence.build_manifest("evidence-x", 1000.0, files)
        self.assertFalse(evidence.verify_manifest(m, {}))
        self.assertFalse(evidence.verify_manifest(m, {"t.json": b"data", "x": b"y"}))

    def test_digest_is_order_independent(self):
        f1 = {"a": b"1", "b": b"2"}
        f2 = {"b": b"2", "a": b"1"}
        self.assertEqual(
            evidence.build_manifest("x", 1.0, f1)["bundle_digest"],
            evidence.build_manifest("x", 1.0, f2)["bundle_digest"])


class DiskReserveTests(unittest.TestCase):
    def test_ok_when_room_remains(self):
        self.assertTrue(evidence.disk_reserve_ok(1000, 100, 500))

    def test_refused_when_below_floor(self):
        self.assertFalse(evidence.disk_reserve_ok(1000, 600, 500))

    def test_exact_floor_allowed(self):
        self.assertTrue(evidence.disk_reserve_ok(1000, 500, 500))


class RotationTests(unittest.TestCase):
    def _bundles(self, sizes):
        return [{"id": f"evidence-{i}", "created": float(i), "bytes": b}
                for i, b in enumerate(sizes)]

    def test_count_cap_drops_oldest(self):
        doomed = evidence.select_for_rotation(
            self._bundles([10, 10, 10, 10]), max_bundles=2, max_total_bytes=0)
        self.assertEqual(doomed, ["evidence-0", "evidence-1"])

    def test_size_cap_drops_oldest(self):
        doomed = evidence.select_for_rotation(
            self._bundles([100, 100, 100]), max_bundles=0, max_total_bytes=250)
        self.assertEqual(doomed, ["evidence-0"])  # 100+100+100=300 -> drop one

    def test_nothing_dropped_when_within_caps(self):
        self.assertEqual(
            evidence.select_for_rotation(self._bundles([10, 10]),
                                         max_bundles=50, max_total_bytes=10_000), [])


class PolicyTests(unittest.TestCase):
    def test_defaults_applied(self):
        p = evidence.policy({})
        self.assertEqual(p["reserve_bytes"], evidence.DEFAULT_RESERVE_MB * 1024 * 1024)
        self.assertEqual(p["max_bundles"], evidence.DEFAULT_MAX_BUNDLES)
        self.assertEqual(p["window_minutes"], evidence.DEFAULT_WINDOW_MINUTES)

    def test_overrides_and_clamping(self):
        p = evidence.policy({"reserve_mb": 10, "max_bundles": 3,
                             "max_total_mb": 5, "window_minutes": 9000})
        self.assertEqual(p["reserve_bytes"], 10 * 1024 * 1024)
        self.assertEqual(p["max_bundles"], 3)
        self.assertEqual(p["max_total_bytes"], 5 * 1024 * 1024)
        self.assertEqual(p["window_minutes"], 1440)  # clamped to max

    def test_bad_values_fall_back_to_defaults(self):
        p = evidence.policy({"reserve_mb": "nonsense"})
        self.assertEqual(p["reserve_bytes"], evidence.DEFAULT_RESERVE_MB * 1024 * 1024)


# --------------------------------------------------------------------------- #
# Endpoints: /api/evidence/*
# --------------------------------------------------------------------------- #
def _seed_monitor_db(path: Path) -> None:
    now = time.time()
    db = sqlite3.connect(str(path))
    db.executescript(
        """
        CREATE TABLE ping_samples (ts REAL, target TEXT, ok INTEGER, rtt_ms REAL);
        CREATE TABLE service_samples (ts REAL, name TEXT, kind TEXT, ok INTEGER,
            duration_ms REAL, detail TEXT);
        CREATE TABLE events (id INTEGER PRIMARY KEY, started REAL, ended REAL,
            kind TEXT, failed_targets TEXT, snapshot TEXT);
        CREATE TABLE tcp_samples (ts REAL, in_segs INTEGER, out_segs INTEGER,
            retrans_segs INTEGER, out_rsts INTEGER, attempt_fails INTEGER,
            estab_resets INTEGER, tcp_syn_retrans INTEGER, tcp_lost_retransmit INTEGER);
        CREATE TABLE wifi_samples (ts REAL, connected INTEGER, signal_dbm REAL);
        """
    )
    for i in range(30):
        ts = now - (30 - i) * 10
        ok = 0 if i == 5 else 1
        db.execute("INSERT INTO ping_samples VALUES (?,?,?,?)",
                   (ts, "8.8.8.8", ok, 12.0 if ok else None))
    db.commit()
    db.close()


class EndpointTests(unittest.TestCase):
    def setUp(self):
        appmod.AUTH_DISABLED = True
        self.c = appmod.app.test_client()
        self._db = Path(os.environ["PROBE_MONITOR_DB"])
        if self._db.exists():
            self._db.unlink()
        # Point the bundle dir at a throwaway tree per test.
        self._bundle_dir = Path(tempfile.mkdtemp(prefix="probe-evidence-"))
        self._saved_dir = appmod.EVIDENCE_DIR
        appmod.EVIDENCE_DIR = self._bundle_dir

    def tearDown(self):
        appmod.EVIDENCE_DIR = self._saved_dir
        shutil.rmtree(self._bundle_dir, ignore_errors=True)

    def test_freeze_creates_verifiable_bundle(self):
        _seed_monitor_db(self._db)
        r = self.c.post("/api/evidence/freeze")
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        bid = body["bundle_id"]
        self.assertTrue(evidence.is_valid_bundle_id(bid))
        self.assertIn("report.json", body["files"])

        # Bundle on disk verifies against its manifest.
        bundle = self._bundle_dir / bid
        manifest = json.loads((bundle / evidence.MANIFEST_NAME).read_text())
        files = {n: (bundle / n).read_bytes() for n in manifest["files"]}
        self.assertTrue(evidence.verify_manifest(manifest, files))
        self.assertEqual(manifest["bundle_digest"], body["bundle_digest"])

    def test_freeze_then_list(self):
        _seed_monitor_db(self._db)
        self.c.post("/api/evidence/freeze")
        r = self.c.get("/api/evidence")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(len(data["bundles"]), 1)
        self.assertIn("free_bytes", data)
        self.assertIn("reserve_bytes", data)

    def test_manifest_endpoint(self):
        _seed_monitor_db(self._db)
        bid = self.c.post("/api/evidence/freeze").get_json()["bundle_id"]
        r = self.c.get(f"/api/evidence/{bid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["bundle_id"], bid)

    def test_file_download_endpoint(self):
        _seed_monitor_db(self._db)
        bid = self.c.post("/api/evidence/freeze").get_json()["bundle_id"]
        r = self.c.get(f"/api/evidence/{bid}/report.json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(report_ok := r.get_data(as_text=True).strip().startswith("{"))
        self.assertTrue(report_ok)

    def test_invalid_bundle_id_rejected(self):
        self.assertEqual(self.c.get("/api/evidence/..%2f..%2fetc").status_code, 400)
        self.assertEqual(self.c.get("/api/evidence/not-a-bundle").status_code, 400)

    def test_file_traversal_rejected(self):
        _seed_monitor_db(self._db)
        bid = self.c.post("/api/evidence/freeze").get_json()["bundle_id"]
        r = self.c.get(f"/api/evidence/{bid}/..%2f..%2fsettings.json")
        self.assertIn(r.status_code, (400, 404))

    def test_freeze_refused_when_reserve_breached(self):
        _seed_monitor_db(self._db)
        # A reserve larger than the disk guarantees the floor is breached.
        appmod.settings_store.apply_update(
            {"evidence": {"reserve_mb": 1_000_000}})
        try:
            r = self.c.post("/api/evidence/freeze")
            self.assertEqual(r.status_code, 507)
            self.assertIn("reserve", r.get_json()["error"])
        finally:
            appmod.settings_store.apply_update({"evidence": {"reserve_mb": 512}})

    def test_rotation_keeps_newest(self):
        _seed_monitor_db(self._db)
        appmod.settings_store.apply_update({"evidence": {"max_bundles": 2}})
        try:
            ids = []
            for _ in range(4):
                ids.append(self.c.post("/api/evidence/freeze").get_json()["bundle_id"])
                time.sleep(1.05)  # distinct second-resolution ids + created order
            remaining = {b["id"] for b in self.c.get("/api/evidence").get_json()["bundles"]}
            self.assertLessEqual(len(remaining), 2)
            self.assertIn(ids[-1], remaining)   # newest kept
            self.assertNotIn(ids[0], remaining)  # oldest rotated out
        finally:
            appmod.settings_store.apply_update({"evidence": {"max_bundles": 50}})

    def test_freeze_with_no_db_still_succeeds(self):
        # No monitor DB -> empty buffers, but a bundle is still produced.
        r = self.c.post("/api/evidence/freeze")
        self.assertEqual(r.status_code, 201)


if __name__ == "__main__":
    unittest.main()
