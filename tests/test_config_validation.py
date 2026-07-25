"""Tests for configuration validation and the audit trail (task #49, roadmap P1).

Three layers:
  1. dashboard.config_validation.validate_settings — pure per-section checks that
     reject a bad partial settings payload with specific messages.
  2. dashboard.config_validation.summarize_settings — a secret-free description of
     a change, for the audit trail (secret leaves never leak their value).
  3. dashboard.history.record_audit / list_audit and the /api/settings and
     /api/audit endpoints: a valid change is persisted AND recorded, an invalid
     one is rejected 400 and NOT recorded.

Stdlib unittest only. State is isolated to a throwaway tree via _isolation, which
must be imported before dashboard.app (state paths are read at import time).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolation  # noqa: E402,F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import app as appmod  # noqa: E402
from dashboard import config_validation as cv  # noqa: E402
from dashboard import history  # noqa: E402
from dashboard import settings as settings_store  # noqa: E402


class ValidateTests(unittest.TestCase):
    def test_empty_update_is_valid(self):
        self.assertEqual(cv.validate_settings({}), [])

    def test_non_object_update_rejected(self):
        self.assertTrue(cv.validate_settings([]))          # type: ignore[arg-type]

    def test_only_present_sections_are_checked(self):
        # a valid metrics section alone must not fault the absent snmp section
        self.assertEqual(cv.validate_settings({"metrics": {"enabled": True}}), [])

    def test_snmp_version_enum(self):
        self.assertEqual(cv.validate_settings({"snmp": {"version": "2c"}}), [])
        errs = cv.validate_settings({"snmp": {"version": "1"}})
        self.assertTrue(any("version" in e for e in errs))

    def test_snmp_timeout_range(self):
        self.assertTrue(cv.validate_settings({"snmp": {"timeout": -1}}))
        self.assertTrue(cv.validate_settings({"snmp": {"timeout": 999}}))
        self.assertEqual(cv.validate_settings({"snmp": {"timeout": 5}}), [])
        # a bool must not sneak through the number check
        self.assertTrue(cv.validate_settings({"snmp": {"retries": True}}))

    def test_snmp_v3_enums(self):
        self.assertTrue(cv.validate_settings(
            {"snmp": {"v3": {"level": "bogus"}}}))
        self.assertTrue(cv.validate_settings(
            {"snmp": {"v3": {"auth_proto": "rot13"}}}))
        # case-insensitive protocol match
        self.assertEqual(cv.validate_settings(
            {"snmp": {"v3": {"auth_proto": "sha", "priv_proto": "aes"}}}), [])

    def test_metrics_types(self):
        self.assertTrue(cv.validate_settings({"metrics": {"enabled": "yes"}}))
        self.assertTrue(cv.validate_settings({"metrics": {"token": 123}}))
        self.assertTrue(cv.validate_settings({"metrics": {"token": "a b"}}))
        self.assertTrue(cv.validate_settings({"metrics": {"token": "x" * 513}}))
        self.assertEqual(cv.validate_settings(
            {"metrics": {"enabled": True, "token": "s3cret"}}), [])

    def test_interface_overrides_shape(self):
        self.assertTrue(cv.validate_settings(
            {"interface_overrides": {"eth0": {"capture_allowed": "sure"}}}))
        self.assertEqual(cv.validate_settings(
            {"interface_overrides": {"eth0": {"capture_allowed": True}}}), [])

    def test_approved_scope_shape(self):
        self.assertTrue(cv.validate_settings({"approved_scope": "10.0.0.0/8"}))
        self.assertEqual(cv.validate_settings(
            {"approved_scope": ["10.0.0.0/8", {"cidr": "192.168.0.0/16"}]}), [])


class SummarizeTests(unittest.TestCase):
    def test_secret_leaf_never_leaks(self):
        s = cv.summarize_settings({"metrics": {"enabled": True, "token": "s3cret"}})
        self.assertNotIn("s3cret", s)
        self.assertIn("<set>", s)

    def test_cleared_secret_marked(self):
        s = cv.summarize_settings({"snmp": {"community": ""}})
        self.assertIn("<cleared>", s)

    def test_nested_dict_lists_keys_only(self):
        s = cv.summarize_settings({"snmp": {"v3": {"auth_key": "x", "user": "u"}}})
        self.assertNotIn("x", s.replace("metrics", ""))  # auth_key value not present
        self.assertIn("v3", s)

    def test_empty_update(self):
        self.assertEqual(cv.summarize_settings({}), "no changes")


class AuditStoreTests(unittest.TestCase):
    def test_record_then_list(self):
        history.record_audit("test.action", user="tester", target="thing",
                             detail="did a thing")
        entries = history.list_audit(10)
        self.assertTrue(entries)
        top = entries[0]
        self.assertEqual(top["action"], "test.action")
        self.assertEqual(top["user"], "tester")
        self.assertEqual(top["target"], "thing")

    def test_empty_action_is_noop(self):
        before = len(history.list_audit(1000))
        history.record_audit("")
        self.assertEqual(len(history.list_audit(1000)), before)

    def test_list_orders_newest_first(self):
        history.record_audit("a.one")
        history.record_audit("a.two")
        acts = [e["action"] for e in history.list_audit(5)]
        self.assertLess(acts.index("a.two"), acts.index("a.one"))


class EndpointTests(unittest.TestCase):
    def setUp(self):
        appmod.AUTH_DISABLED = True   # exercise settings/audit without a session
        self.c = appmod.app.test_client()
        settings_store.save({**settings_store.load(),
                             "metrics": {"enabled": False, "token": ""}})

    def test_invalid_settings_rejected_400_and_not_recorded(self):
        before = len(history.list_audit(1000))
        r = self.c.put("/api/settings",
                       json={"metrics": {"enabled": "not-a-bool"}})
        self.assertEqual(r.status_code, 400)
        body = r.get_json()
        self.assertEqual(body["error"], "invalid settings")
        self.assertTrue(body["details"])
        # a rejected change must leave no audit entry
        self.assertEqual(len(history.list_audit(1000)), before)

    def test_valid_settings_recorded_in_audit(self):
        r = self.c.put("/api/settings",
                       json={"metrics": {"enabled": True, "token": "abc123"}})
        self.assertEqual(r.status_code, 200)
        top = history.list_audit(1)[0]
        self.assertEqual(top["action"], "settings.update")
        self.assertIn("metrics", top["target"])
        # the recorded detail must not contain the secret token
        self.assertNotIn("abc123", top["detail"])

    def test_audit_endpoint_returns_entries(self):
        self.c.put("/api/settings", json={"metrics": {"enabled": True}})
        r = self.c.get("/api/audit")
        self.assertEqual(r.status_code, 200)
        self.assertIn("entries", r.get_json())

    def test_audit_endpoint_limit_validation(self):
        r = self.c.get("/api/audit?limit=abc")
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
