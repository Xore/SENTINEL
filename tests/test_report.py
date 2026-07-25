"""Tests for the session / acceptance report (task #48).

Two layers, stdlib unittest:
  1. dashboard.report  — the pure assembler + renderers + SHA-256 digest, fed
     synthetic row lists (no DB, no Flask).
  2. /api/report/session — the endpoint on dashboard.app against a synthetic
     monitor.db. _isolation must import before dashboard.app.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolation  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard import app as appmod  # noqa: E402
from dashboard import report  # noqa: E402


def _pings(target, oks, base_ts=1000.0):
    """oks: list of (ok, rtt_ms)."""
    return [{"ts": base_ts + i, "target": target, "ok": ok, "rtt_ms": rtt}
            for i, (ok, rtt) in enumerate(oks)]


class BuildReportTests(unittest.TestCase):
    def _report(self, **kw):
        base = dict(now=2000.0, window_start=1000.0, window_end=2000.0,
                    host="probe-x", version="test", role="standalone")
        base.update(kw)
        return report.build_report(**base)

    def test_per_target_availability_and_loss(self):
        rows = _pings("8.8.8.8", [(1, 10.0), (1, 20.0), (0, None), (1, 30.0)])
        rep = self._report(ping_rows=rows)
        t = rep["targets"][0]
        self.assertEqual(t["target"], "8.8.8.8")
        self.assertEqual(t["samples"], 4)
        self.assertEqual(t["up"], 3)
        self.assertEqual(t["down"], 1)
        self.assertEqual(t["availability_pct"], 75.0)
        self.assertEqual(t["loss_pct"], 25.0)
        self.assertEqual(t["rtt_median_ms"], 20.0)

    def test_rtt_percentiles_ignore_failed_samples(self):
        # failed sample has rtt_ms None and must not poison the percentile
        rows = _pings("h", [(1, 10.0), (0, None), (1, 30.0)])
        t = self._report(ping_rows=rows)["targets"][0]
        self.assertEqual(t["rtt_median_ms"], 20.0)  # median of [10,30]

    def test_multiple_targets_sorted(self):
        rows = _pings("z", [(1, 1.0)]) + _pings("a", [(1, 1.0)])
        rep = self._report(ping_rows=rows)
        self.assertEqual([t["target"] for t in rep["targets"]], ["a", "z"])

    def test_service_failure_pct(self):
        svc = [{"ts": 1, "name": "dns:1.1.1.1", "kind": "dns", "ok": 1, "duration_ms": 4.0},
               {"ts": 2, "name": "dns:1.1.1.1", "kind": "dns", "ok": 0, "duration_ms": None},
               {"ts": 3, "name": "dns:1.1.1.1", "kind": "dns", "ok": 1, "duration_ms": 6.0},
               {"ts": 4, "name": "dns:1.1.1.1", "kind": "dns", "ok": 1, "duration_ms": 8.0}]
        s = self._report(service_rows=svc)["services"][0]
        self.assertEqual(s["checks"], 4)
        self.assertEqual(s["fail"], 1)
        self.assertEqual(s["failure_pct"], 25.0)
        self.assertEqual(s["avg_duration_ms"], 6.0)  # (4+6+8)/3

    def test_event_json_failed_targets_parsed(self):
        events = [{"id": 5, "started": 1100.0, "ended": 1160.0, "kind": "outage",
                   "failed_targets": json.dumps(["8.8.8.8", "1.1.1.1"])}]
        e = self._report(event_rows=events)["events"][0]
        self.assertEqual(e["failed_targets"], ["8.8.8.8", "1.1.1.1"])
        self.assertEqual(e["duration_s"], 60.0)
        self.assertFalse(e["ongoing"])

    def test_open_event_is_ongoing(self):
        # healthy reachability but an outage event still open -> attention
        events = [{"id": 6, "started": 1100.0, "ended": None, "kind": "outage",
                   "failed_targets": "[]"}]
        rep = self._report(ping_rows=_pings("h", [(1, 10.0)] * 50), event_rows=events)
        self.assertTrue(rep["events"][0]["ongoing"])
        self.assertIsNone(rep["events"][0]["duration_s"])
        self.assertEqual(rep["summary"]["events_open"], 1)
        self.assertEqual(rep["summary"]["verdict"], "attention")

    def test_clean_run_verdict_pass(self):
        rows = _pings("h", [(1, 10.0)] * 100)
        rep = self._report(ping_rows=rows)
        self.assertEqual(rep["summary"]["verdict"], "pass")
        self.assertEqual(rep["summary"]["overall_availability_pct"], 100.0)

    def test_low_availability_flags_attention(self):
        rows = _pings("h", [(1, 10.0), (0, None)])  # 50%
        rep = self._report(ping_rows=rows)
        self.assertEqual(rep["summary"]["verdict"], "attention")
        self.assertTrue(rep["summary"]["reasons"])

    def test_no_samples_is_insufficient_data(self):
        rep = self._report()
        self.assertEqual(rep["summary"]["verdict"], "insufficient_data")

    def test_degraded_trend_flags_attention(self):
        rows = _pings("h", [(1, 10.0)] * 100)
        rep = self._report(ping_rows=rows,
                           trend_verdicts={"tcp": {"state": "degraded", "latest": 0.1}})
        self.assertEqual(rep["summary"]["verdict"], "attention")

    def test_wifi_summary(self):
        wifi = [{"ts": 1, "connected": 1, "signal_dbm": -60},
                {"ts": 2, "connected": 1, "signal_dbm": -70},
                {"ts": 3, "connected": 0, "signal_dbm": None}]
        rep = self._report(wifi_rows=wifi)
        self.assertEqual(rep["wifi"]["samples"], 3)
        self.assertEqual(rep["wifi"]["signal_min_dbm"], -70)
        self.assertEqual(rep["wifi"]["signal_max_dbm"], -60)


class DigestTests(unittest.TestCase):
    def _rep(self):
        return report.build_report(
            now=2000.0, window_start=1000.0, window_end=2000.0, host="h",
            ping_rows=_pings("8.8.8.8", [(1, 10.0), (1, 12.0)]))

    def test_finalize_stamps_digest(self):
        rep = report.finalize(self._rep())
        self.assertTrue(rep["meta"]["digest"])
        self.assertEqual(len(rep["meta"]["digest"]), 64)  # sha256 hex

    def test_digest_is_stable(self):
        self.assertEqual(report.compute_digest(self._rep()),
                         report.compute_digest(self._rep()))

    def test_verify_true_after_finalize(self):
        self.assertTrue(report.verify(report.finalize(self._rep())))

    def test_tamper_detected(self):
        rep = report.finalize(self._rep())
        rep["targets"][0]["availability_pct"] = 0.0  # forge the data
        self.assertFalse(report.verify(rep))

    def test_digest_independent_of_its_own_field(self):
        # the digest must be computed with the digest slot blanked, so stamping
        # it does not change what a recomputation produces
        rep = self._rep()
        before = report.compute_digest(rep)
        report.finalize(rep)
        self.assertEqual(before, report.compute_digest(rep))


class RendererTests(unittest.TestCase):
    def _rep(self):
        rep = report.build_report(
            now=2000.0, window_start=1000.0, window_end=2000.0, host="probe-x",
            ping_rows=_pings("8.8.8.8", [(1, 10.0), (0, None)]),
            service_rows=[{"ts": 1, "name": "dns:1.1.1.1", "kind": "dns",
                           "ok": 1, "duration_ms": 4.0}],
            event_rows=[{"id": 1, "started": 1100.0, "ended": 1160.0,
                         "kind": "outage", "failed_targets": '["8.8.8.8"]'}],
            trend_verdicts={"tcp": {"state": "stable", "latest": 0.01}})
        return report.finalize(rep)

    def test_json_roundtrips(self):
        text, ctype, fname = report.render(self._rep(), "json")
        self.assertEqual(ctype, "application/json")
        self.assertTrue(fname.endswith(".json"))
        parsed = json.loads(text)
        self.assertEqual(parsed["meta"]["host"], "probe-x")
        self.assertTrue(report.verify(parsed))  # digest survives a JSON round-trip

    def test_csv_has_sections_and_parses(self):
        text, ctype, fname = report.render(self._rep(), "csv")
        self.assertEqual(ctype, "text/csv")
        self.assertIn("[targets]", text)
        self.assertIn("[services]", text)
        self.assertIn("[events]", text)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertTrue(any(r and r[0] == "8.8.8.8" for r in rows))

    def test_html_is_self_contained_and_shows_digest(self):
        rep = self._rep()
        text, ctype, fname = report.render(rep, "html")
        self.assertTrue(ctype.startswith("text/html"))
        self.assertIn("<!doctype html>", text.lower())
        self.assertNotIn("http://", text.replace("http://www.w3.org", ""))  # no external refs
        self.assertIn(rep["meta"]["digest"], text)  # digest is visible for verification

    def test_html_escapes_target_names(self):
        rep = report.finalize(report.build_report(
            now=2000.0, window_start=1000.0, window_end=2000.0, host="h",
            ping_rows=_pings("<script>", [(1, 1.0)])))
        text, _, _ = report.render(rep, "html")
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)

    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            report.render(self._rep(), "pdf")


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
        ok = 0 if i == 5 else 1  # one failed sample
        db.execute("INSERT INTO ping_samples VALUES (?,?,?,?)",
                   (ts, "8.8.8.8", ok, 12.0 if ok else None))
        db.execute("INSERT INTO service_samples VALUES (?,?,?,?,?,?)",
                   (ts, "dns:1.1.1.1", "dns", 1, 5.0, ""))
    db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
               (1, now - 200, now - 140, "outage", '["8.8.8.8"]', "{}"))
    db.commit()
    db.close()


class EndpointTests(unittest.TestCase):
    def setUp(self):
        appmod.AUTH_DISABLED = True
        self.c = appmod.app.test_client()
        self._db = Path(os.environ["PROBE_MONITOR_DB"])
        if self._db.exists():
            self._db.unlink()

    def test_json_report_with_header(self):
        _seed_monitor_db(self._db)
        r = self.c.get("/api/report/session?format=json&minutes=60")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["Content-Type"].startswith("application/json"))
        digest = r.headers.get("X-Report-SHA256")
        self.assertTrue(digest and len(digest) == 64)
        data = r.get_json()
        self.assertEqual(data["meta"]["digest"], digest)
        self.assertTrue(report.verify(data))
        self.assertEqual(data["targets"][0]["target"], "8.8.8.8")
        self.assertEqual(data["summary"]["events_total"], 1)

    def test_csv_report(self):
        _seed_monitor_db(self._db)
        r = self.c.get("/api/report/session?format=csv&minutes=60")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertIn("[targets]", r.get_data(as_text=True))

    def test_html_report_inline(self):
        _seed_monitor_db(self._db)
        r = self.c.get("/api/report/session?format=html&minutes=60")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["Content-Type"])
        self.assertIn("inline", r.headers["Content-Disposition"])
        self.assertIn("Session Acceptance Report", r.get_data(as_text=True))

    def test_default_format_is_json(self):
        _seed_monitor_db(self._db)
        r = self.c.get("/api/report/session?minutes=60")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["Content-Type"].startswith("application/json"))

    def test_bad_format_returns_400(self):
        _seed_monitor_db(self._db)
        r = self.c.get("/api/report/session?format=pdf")
        self.assertEqual(r.status_code, 400)

    def test_bad_minutes_returns_400(self):
        r = self.c.get("/api/report/session?minutes=notanumber")
        self.assertEqual(r.status_code, 400)

    def test_until_before_since_returns_400(self):
        r = self.c.get("/api/report/session?since=2000&until=1000")
        self.assertEqual(r.status_code, 400)

    def test_no_db_still_returns_valid_report(self):
        # absent monitor DB -> empty but well-formed, verifiable report
        r = self.c.get("/api/report/session?minutes=60")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(report.verify(data))
        self.assertEqual(data["summary"]["verdict"], "insufficient_data")
        self.assertEqual(data["targets"], [])


if __name__ == "__main__":
    unittest.main()
