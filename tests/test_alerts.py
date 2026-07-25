"""Tests for sustained-state alerting (task #53).

Layers:
  1. dashboard.alerts — pure evaluate() transition logic, is_alerting bands,
     formatters, and webhook/email delivery with the network mocked.
  2. dashboard.config_validation — the new alerting section validator.
  3. /api/alerts endpoints on dashboard.app, against a synthetic monitor.db.

Stdlib unittest only; _isolation must import before dashboard.app.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolation  # noqa: E402,F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import alerts  # noqa: E402
from dashboard import app as appmod  # noqa: E402
from dashboard import config_validation as cv  # noqa: E402
from dashboard import settings as settings_store  # noqa: E402


def _sig(sid, state):
    return {"id": sid, "title": sid, "state": state}


class IsAlertingTests(unittest.TestCase):
    def test_default_min_state_is_rising(self):
        self.assertFalse(alerts.is_alerting("spike"))
        self.assertTrue(alerts.is_alerting("rising"))
        self.assertTrue(alerts.is_alerting("degraded"))

    def test_stable_and_insufficient_never_alert(self):
        self.assertFalse(alerts.is_alerting("stable", "spike"))
        self.assertFalse(alerts.is_alerting("insufficient_data", "spike"))

    def test_min_state_spike_includes_spike(self):
        self.assertTrue(alerts.is_alerting("spike", "spike"))

    def test_min_state_degraded_excludes_rising(self):
        self.assertFalse(alerts.is_alerting("rising", "degraded"))
        self.assertTrue(alerts.is_alerting("degraded", "degraded"))


class EvaluateTests(unittest.TestCase):
    def test_first_cross_fires_once(self):
        events, new = alerts.evaluate([_sig("tcp", "degraded")], {})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "firing")
        self.assertTrue(new["tcp"]["alerting"])

    def test_steady_alerting_does_not_refire(self):
        _, state1 = alerts.evaluate([_sig("tcp", "rising")], {})
        events, _ = alerts.evaluate([_sig("tcp", "degraded")], state1)
        self.assertEqual(events, [])  # already alerting -> no new edge

    def test_recovery_resolves_once(self):
        _, state1 = alerts.evaluate([_sig("tcp", "degraded")], {})
        events, state2 = alerts.evaluate([_sig("tcp", "stable")], state1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "resolved")
        events2, _ = alerts.evaluate([_sig("tcp", "stable")], state2)
        self.assertEqual(events2, [])  # stays resolved, silent

    def test_spike_does_not_fire_at_default_min_state(self):
        events, _ = alerts.evaluate([_sig("tcp", "spike")], {})
        self.assertEqual(events, [])

    def test_spike_fires_when_min_state_lowered(self):
        events, _ = alerts.evaluate([_sig("tcp", "spike")], {}, min_state="spike")
        self.assertEqual(len(events), 1)

    def test_dropped_signal_leaves_no_stuck_state(self):
        _, state1 = alerts.evaluate([_sig("a", "degraded"), _sig("b", "stable")], {})
        _, state2 = alerts.evaluate([_sig("b", "stable")], state1)
        self.assertNotIn("a", state2)


class FormatterTests(unittest.TestCase):
    def test_subject_firing_vs_resolved(self):
        self.assertIn("FIRING", alerts.render_subject(
            {"kind": "firing", "title": "TCP", "state": "degraded"}))
        self.assertIn("RESOLVED", alerts.render_subject(
            {"kind": "resolved", "title": "TCP", "state": "stable"}))

    def test_body_includes_detail(self):
        body = alerts.render_body({"kind": "firing", "id": "dns", "title": "DNS",
                                   "state": "rising", "summary": "5% failures",
                                   "value": "5.0%", "ts": time.time()})
        self.assertIn("5% failures", body)
        self.assertIn("dns", body)


class DeliveryTests(unittest.TestCase):
    def test_webhook_no_url_is_error_not_raise(self):
        r = alerts.deliver_webhook("", {"id": "x"})
        self.assertFalse(r["ok"])

    def test_webhook_posts_json(self):
        captured = {}

        class FakeResp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["data"] = req.data
            captured["ctype"] = req.headers.get("Content-type")
            return FakeResp()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            r = alerts.deliver_webhook("https://hook.example/x",
                                       {"id": "tcp", "kind": "firing", "state": "degraded"})
        self.assertTrue(r["ok"])
        self.assertEqual(captured["url"], "https://hook.example/x")
        self.assertIn(b"tcp", captured["data"])
        self.assertEqual(captured["ctype"], "application/json")

    def test_webhook_http_error_is_captured(self):
        import urllib.error
        def boom(req, timeout=None):
            raise urllib.error.URLError("connection refused")
        with mock.patch("urllib.request.urlopen", boom):
            r = alerts.deliver_webhook("https://hook.example/x", {"id": "x"})
        self.assertFalse(r["ok"])
        self.assertIn("refused", r["error"])

    def test_email_missing_fields_is_error(self):
        r = alerts.deliver_email({"smtp_host": "", "from_addr": "", "to_addrs": ""},
                                 {"id": "x", "kind": "firing", "state": "degraded"})
        self.assertFalse(r["ok"])

    def test_email_sends_via_smtp(self):
        sent = {}

        class FakeSMTP:
            def __init__(self, host, port, timeout=None):
                sent["host"] = host; sent["port"] = port
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def starttls(self): sent["tls"] = True
            def login(self, u, p): sent["login"] = (u, p)
            def send_message(self, msg): sent["subject"] = msg["Subject"]

        cfg = {"smtp_host": "smtp.example", "smtp_port": 587, "use_tls": True,
               "username": "u", "password": "p", "from_addr": "a@x",
               "to_addrs": "b@x, c@x"}
        with mock.patch("smtplib.SMTP", FakeSMTP):
            r = alerts.deliver_email(cfg, {"id": "tcp", "kind": "firing",
                                           "state": "degraded", "title": "TCP"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["recipients"], 2)
        self.assertTrue(sent["tls"])
        self.assertEqual(sent["login"], ("u", "p"))
        self.assertIn("FIRING", sent["subject"])

    def test_dispatch_only_enabled_channels(self):
        cfg = {"webhook": {"enabled": False, "url": "https://x"},
               "email": {"enabled": False}}
        self.assertEqual(alerts.dispatch({"id": "x"}, cfg), {})


class StatePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(os.environ["PROBE_ALERT_STATE"])
        if self.path.exists():
            self.path.unlink()

    def test_missing_file_returns_empty(self):
        state = alerts.load_state(self.path)
        self.assertEqual(state, {"signals": {}, "history": []})

    def test_round_trip(self):
        alerts.save_state({"signals": {"a": {"alerting": True}}, "history": [{"id": "a"}]},
                          self.path)
        state = alerts.load_state(self.path)
        self.assertTrue(state["signals"]["a"]["alerting"])

    def test_history_is_trimmed(self):
        big = {"signals": {}, "history": [{"n": i} for i in range(alerts.HISTORY_LIMIT + 50)]}
        alerts.save_state(big, self.path)
        state = alerts.load_state(self.path)
        self.assertEqual(len(state["history"]), alerts.HISTORY_LIMIT)
        self.assertEqual(state["history"][-1]["n"], alerts.HISTORY_LIMIT + 49)


class ValidationTests(unittest.TestCase):
    def test_valid_config_passes(self):
        errs = cv.validate_settings({"alerting": {
            "enabled": True, "min_state": "rising", "poll_seconds": 60,
            "webhook": {"enabled": True, "url": "https://hook.example/x"}}})
        self.assertEqual(errs, [])

    def test_bad_min_state_rejected(self):
        errs = cv.validate_settings({"alerting": {"min_state": "nope"}})
        self.assertTrue(any("min_state" in e for e in errs))

    def test_non_http_webhook_url_rejected(self):
        errs = cv.validate_settings({"alerting": {"webhook": {"url": "ftp://x"}}})
        self.assertTrue(any("webhook.url" in e for e in errs))

    def test_bad_poll_seconds_rejected(self):
        errs = cv.validate_settings({"alerting": {"poll_seconds": 2}})
        self.assertTrue(any("poll_seconds" in e for e in errs))

    def test_bad_smtp_port_rejected(self):
        errs = cv.validate_settings({"alerting": {"email": {"smtp_port": 70000}}})
        self.assertTrue(any("smtp_port" in e for e in errs))


class SecretRedactionTests(unittest.TestCase):
    def test_email_password_is_redacted(self):
        self.assertIn("alerting.email.password", settings_store.SECRET_PATHS)


def _seed_monitor_db(path: Path, *, dns_ok: bool = True, outage: bool = False) -> None:
    now = time.time()
    db = sqlite3.connect(str(path))
    db.executescript(
        """
        CREATE TABLE tcp_samples (ts REAL, in_segs INTEGER, out_segs INTEGER,
            retrans_segs INTEGER, out_rsts INTEGER, attempt_fails INTEGER,
            estab_resets INTEGER, tcp_syn_retrans INTEGER, tcp_lost_retransmit INTEGER);
        CREATE TABLE service_samples (ts REAL, name TEXT, kind TEXT, ok INTEGER,
            duration_ms REAL, detail TEXT);
        CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL,
            ended REAL, kind TEXT, failed_targets TEXT, snapshot TEXT);
        """
    )
    for i in range(20):
        ts = now - (20 - i) * 30
        db.execute("INSERT INTO tcp_samples VALUES (?,?,?,?,?,?,?,?,?)",
                   (ts, 0, 1000 * (i + 1), 10 * (i + 1), 0, 0, 0, 0, 0))
        db.execute("INSERT INTO service_samples VALUES (?,?,?,?,?,?)",
                   (ts, "dns:1.1.1.1", "dns", 1 if dns_ok else 0, 5.0, ""))
    if outage:
        db.execute("INSERT INTO events (started, ended, kind, failed_targets) VALUES (?,?,?,?)",
                   (now - 100, None, "loss", '["gw"]'))
    db.commit()
    db.close()


class EndpointTests(unittest.TestCase):
    def setUp(self):
        appmod.AUTH_DISABLED = True
        self.c = appmod.app.test_client()
        self._db = Path(os.environ["PROBE_MONITOR_DB"])
        if self._db.exists():
            self._db.unlink()
        self._state = Path(os.environ["PROBE_ALERT_STATE"])
        if self._state.exists():
            self._state.unlink()
        settings_store.save({**settings_store.load(),
                             "alerting": {**settings_store.DEFAULTS["alerting"]}})

    def _enable(self, **over):
        cfg = {**settings_store.DEFAULTS["alerting"], "enabled": True, **over}
        settings_store.save({**settings_store.load(), "alerting": cfg})

    def test_status_when_disabled(self):
        r = self.c.get("/api/alerts")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["config"]["enabled"])

    def test_evaluate_disabled_is_noop(self):
        r = self.c.post("/api/alerts/evaluate")
        self.assertEqual(r.get_json(), {"enabled": False, "events": 0})

    def test_evaluate_fires_on_outage_signal(self):
        _seed_monitor_db(self._db, outage=True)
        self._enable()
        r = self.c.post("/api/alerts/evaluate")
        data = r.get_json()
        self.assertTrue(data["enabled"])
        self.assertGreaterEqual(data["events"], 1)  # open outage -> firing
        # second run is silent (edge already crossed)
        r2 = self.c.post("/api/alerts/evaluate")
        self.assertEqual(r2.get_json()["events"], 0)

    def test_evaluate_healthy_fires_nothing(self):
        _seed_monitor_db(self._db, dns_ok=True, outage=False)
        self._enable()
        self.assertEqual(self.c.post("/api/alerts/evaluate").get_json()["events"], 0)

    def test_test_endpoint_requires_a_channel(self):
        self._enable()
        r = self.c.post("/api/alerts/test")
        self.assertEqual(r.status_code, 400)

    def test_test_endpoint_dispatches_webhook(self):
        self._enable(webhook={"enabled": True, "url": "https://hook.example/x"})

        class FakeResp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with mock.patch("urllib.request.urlopen", lambda req, timeout=None: FakeResp()):
            r = self.c.post("/api/alerts/test")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["delivery"]["webhook"]["ok"])

    def test_password_not_leaked_in_status(self):
        self._enable(email={**settings_store.DEFAULTS["alerting"]["email"],
                            "password": "sekret"})
        body = self.c.get("/api/alerts").get_data(as_text=True)
        self.assertNotIn("sekret", body)


if __name__ == "__main__":
    unittest.main()
