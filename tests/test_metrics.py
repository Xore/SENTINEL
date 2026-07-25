"""Tests for the Prometheus/OpenMetrics export (task #52, roadmap P4).

Two layers:
  1. dashboard.metrics.render — a pure function, tested with synthetic snapshots
     (format lines, label escaping, None-skipping, counter suffixes).
  2. the /metrics endpoint on dashboard.app — disabled by default (404), enabled
     via settings, optionally bearer-token gated, and reads a synthetic monitor DB.

Stdlib unittest only. State is isolated to a throwaway tree via _isolation, which
must be imported before dashboard.app (state paths are read at import time).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolation  # noqa: E402,F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import app as appmod  # noqa: E402
from dashboard import metrics  # noqa: E402
from dashboard import settings as settings_store  # noqa: E402


class RenderTests(unittest.TestCase):
    def test_minimal_snapshot_has_declarations_and_samples(self):
        text = metrics.render({"scrape": {"monitor_up": 1}})
        self.assertIn("# HELP network_probe_build_info", text)
        self.assertIn("# TYPE network_probe_build_info gauge", text)
        self.assertIn("network_probe_monitor_up 1", text)
        # events default to 0 and are always emitted
        self.assertIn("network_probe_events_open 0", text)
        self.assertTrue(text.endswith("\n"))

    def test_targets_render_all_three_series(self):
        text = metrics.render({"targets": [
            {"name": "gw", "group": "internal", "up": 1, "rtt_ms": 2.5, "loss_pct": 0.0},
        ]})
        self.assertIn('network_probe_target_up{target="gw",group="internal"} 1', text)
        self.assertIn('network_probe_target_rtt_ms{target="gw",group="internal"} 2.5', text)
        self.assertIn('network_probe_target_loss_ratio{target="gw",group="internal"} 0', text)

    def test_none_values_are_skipped_not_rendered_as_none(self):
        text = metrics.render({"targets": [
            {"name": "x", "up": 0, "rtt_ms": None, "loss_pct": None},
        ]})
        self.assertIn('network_probe_target_up{target="x"} 0', text)
        self.assertNotIn("None", text)
        # a target with rtt=None must not emit an rtt sample line for it
        self.assertNotIn('network_probe_target_rtt_ms{target="x"}', text)

    def test_label_values_are_escaped(self):
        text = metrics.render({"services": [
            {"name": 'we"ird\\', "kind": "http", "up": 1, "duration_ms": 5},
        ]})
        self.assertIn(r'service="we\"ird\\"', text)

    def test_interface_counters_have_total_suffix_and_counter_type(self):
        text = metrics.render({"interfaces": [
            {"interface": "eth0", "rx_dropped": 3, "tx_dropped": 0,
             "rx_errors": 1, "tx_errors": 0, "multicast": 42},
        ]})
        self.assertIn("# TYPE network_probe_iface_rx_dropped_total counter", text)
        self.assertIn('network_probe_iface_rx_dropped_total{interface="eth0"} 3', text)
        self.assertIn('network_probe_iface_multicast_total{interface="eth0"} 42', text)

    def test_bool_and_float_formatting(self):
        text = metrics.render({"scrape": {"monitor_up": True},
                               "targets": [{"name": "a", "up": True, "rtt_ms": 1.0}]})
        self.assertIn("network_probe_monitor_up 1", text)
        # 1.0 collapses to integer form
        self.assertIn('network_probe_target_up{target="a"} 1', text)
        self.assertIn('network_probe_target_rtt_ms{target="a"} 1', text)

    def test_declaration_emitted_once_per_metric(self):
        text = metrics.render({"targets": [
            {"name": "a", "up": 1}, {"name": "b", "up": 0},
        ]})
        self.assertEqual(text.count("# TYPE network_probe_target_up gauge"), 1)


def _seed_monitor_db(path: Path) -> None:
    """Create a synthetic monitor.db matching the outage-monitor schema."""
    now = time.time()
    db = sqlite3.connect(str(path))
    db.executescript(
        """
        CREATE TABLE ping_samples (ts REAL, target TEXT, ok INTEGER, rtt_ms REAL);
        CREATE TABLE service_samples (ts REAL, name TEXT, kind TEXT, ok INTEGER,
                                      duration_ms REAL, detail TEXT);
        CREATE TABLE iface_samples (ts REAL, interface TEXT, rx_packets INTEGER,
            rx_dropped INTEGER, rx_errors INTEGER, tx_packets INTEGER,
            tx_dropped INTEGER, tx_errors INTEGER, multicast INTEGER);
        CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL,
            ended REAL, kind TEXT, failed_targets TEXT, snapshot TEXT);
        """
    )
    db.executemany("INSERT INTO ping_samples VALUES (?,?,?,?)", [
        (now - 10, "gw", 1, 1.5), (now - 5, "gw", 1, 2.5),
        (now - 10, "dns", 1, 3.0), (now - 5, "dns", 0, None),  # last sample down
    ])
    db.execute("INSERT INTO service_samples VALUES (?,?,?,?,?,?)",
               (now - 5, "dns:1.1.1.1", "dns", 1, 12.3, ""))
    db.execute("INSERT INTO iface_samples VALUES (?,?,?,?,?,?,?,?,?)",
               (now - 5, "wlp2s0", 100, 2, 0, 200, 0, 1, 9))
    db.execute("INSERT INTO events (started, ended, kind) VALUES (?,?,?)",
               (now - 100, None, "loss"))              # still open
    db.execute("INSERT INTO events (started, ended, kind) VALUES (?,?,?)",
               (now - 3600, now - 3500, "loss"))       # closed, within 24h
    db.commit()
    db.close()


class EndpointTests(unittest.TestCase):
    def setUp(self):
        appmod.AUTH_DISABLED = False   # /metrics must work even with auth ON
        self.c = appmod.app.test_client()
        # reset the metrics settings between tests
        settings_store.save({**settings_store.load(),
                             "metrics": {"enabled": False, "token": ""}})
        self._db = Path(os.environ["PROBE_MONITOR_DB"])
        if self._db.exists():
            self._db.unlink()

    def _enable(self, token: str = ""):
        cfg = settings_store.load()
        cfg["metrics"] = {"enabled": True, "token": token}
        settings_store.save(cfg)

    def test_disabled_returns_404(self):
        r = self.c.get("/metrics")
        self.assertEqual(r.status_code, 404)

    def test_enabled_no_db_still_renders_monitor_down(self):
        self._enable()
        r = self.c.get("/metrics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/plain", r.headers["Content-Type"])
        body = r.get_data(as_text=True)
        self.assertIn("network_probe_monitor_up 0", body)

    def test_enabled_with_db_exposes_targets_and_events(self):
        _seed_monitor_db(self._db)
        self._enable()
        body = self.c.get("/metrics").get_data(as_text=True)
        self.assertIn("network_probe_monitor_up 1", body)
        self.assertIn('network_probe_target_up{target="gw"} 1', body)
        self.assertIn('network_probe_target_up{target="dns"} 0', body)   # last down
        self.assertIn('network_probe_service_up{service="dns:1.1.1.1",kind="dns"} 1', body)
        self.assertIn('network_probe_iface_rx_dropped_total{interface="wlp2s0"} 2', body)
        self.assertIn("network_probe_events_open 1", body)
        # both seeded events started within 24h (one open, one closed)
        self.assertIn("network_probe_events_24h 2", body)

    def test_token_required_when_set(self):
        self._enable(token="s3cret")
        r = self.c.get("/metrics")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers.get("WWW-Authenticate"), "Bearer")

    def test_token_accepted_when_correct(self):
        self._enable(token="s3cret")
        r = self.c.get("/metrics", headers={"Authorization": "Bearer s3cret"})
        self.assertEqual(r.status_code, 200)

    def test_wrong_token_rejected(self):
        self._enable(token="s3cret")
        r = self.c.get("/metrics", headers={"Authorization": "Bearer nope"})
        self.assertEqual(r.status_code, 401)

    def test_token_is_redacted_in_settings_api(self):
        self._enable(token="s3cret")
        red = settings_store.redacted()
        self.assertNotIn("s3cret", str(red))

    def test_put_settings_enables_metrics_and_hides_token(self):
        appmod.AUTH_DISABLED = True  # exercise the settings PUT without a session
        r = self.c.put("/api/settings",
                       json={"metrics": {"enabled": True, "token": "abc123"}})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        # response is redacted: token blanked, *_set flag present
        self.assertEqual(body["metrics"]["token"], "")
        self.assertTrue(body["metrics"]["token_set"])
        self.assertTrue(settings_store.load()["metrics"]["enabled"])
        # a blank token on a later save must not wipe the stored one
        self.c.put("/api/settings", json={"metrics": {"enabled": True, "token": ""}})
        self.assertEqual(settings_store.load()["metrics"]["token"], "abc123")


if __name__ == "__main__":
    unittest.main()
