"""Tests for the roadmap-P5 dangerous-actions gate (task #55).

This is a SAFETY test: it asserts that the register is inert. The whole point of
the feature is that the excluded-by-default techniques are surfaced and gated but
NEVER executed - so the strongest test is that `run_action` / the /run endpoint
refuse in every state, including fully unlocked (master switch on + acknowledged).
If someone ever makes an action `implemented=True` and wires a real technique,
`test_no_action_is_implemented` fails loudly and this test file must be revisited.

Stdlib unittest only. State is isolated via _isolation, imported before app.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolation  # noqa: E402,F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import app as appmod  # noqa: E402
from dashboard import dangerous  # noqa: E402
from dashboard import history  # noqa: E402
from dashboard import settings as settings_store  # noqa: E402


def _fully_unlocked(action_id: str) -> dict:
    """Settings with the master switch on AND the action acknowledged."""
    return {"dangerous_actions": {"enabled": True,
                                  "acknowledged": {action_id: True}}}


class RegisterTests(unittest.TestCase):
    def test_register_covers_every_excluded_category(self):
        cats = {a["category"] for a in dangerous.ACTIONS}
        self.assertEqual(cats, {"scanning", "credentials", "wireless", "ot", "control"})

    def test_no_action_is_implemented(self):
        # SAFETY INVARIANT: nothing here is a working technique.
        for a in dangerous.ACTIONS:
            self.assertFalse(a["implemented"], f"{a['id']} must stay unimplemented")

    def test_ids_are_unique(self):
        ids = [a["id"] for a in dangerous.ACTIONS]
        self.assertEqual(len(ids), len(set(ids)))


class GateTests(unittest.TestCase):
    def test_disabled_by_default_denies(self):
        allowed, reason = dangerous.gate({}, "wifi_deauth")
        self.assertFalse(allowed)
        self.assertIn("disabled", reason)

    def test_enabled_but_unacknowledged_denies(self):
        cfg = {"dangerous_actions": {"enabled": True, "acknowledged": {}}}
        allowed, reason = dangerous.gate(cfg, "wifi_deauth")
        self.assertFalse(allowed)
        self.assertIn("acknowledge", reason)

    def test_fully_unlocked_still_denies_unimplemented(self):
        # the crux: even master-on + acknowledged must NOT allow, because the
        # technique is not implemented.
        allowed, reason = dangerous.gate(_fully_unlocked("wifi_deauth"), "wifi_deauth")
        self.assertFalse(allowed)
        self.assertIn("does not implement", reason)

    def test_unknown_action_denies(self):
        allowed, _ = dangerous.gate(_fully_unlocked("nope"), "nope")
        self.assertFalse(allowed)

    def test_run_action_never_executes(self):
        for a in dangerous.ACTIONS:
            res = dangerous.run_action(_fully_unlocked(a["id"]), a["id"])
            self.assertFalse(res["executed"], f"{a['id']} must never execute")
            self.assertFalse(res["allowed"], f"{a['id']} must never be allowed")


class EndpointTests(unittest.TestCase):
    def setUp(self):
        appmod.AUTH_DISABLED = True
        self.c = appmod.app.test_client()
        settings_store.save({**settings_store.load(),
                             "dangerous_actions": {"enabled": False, "acknowledged": {}}})

    def test_get_lists_register_disabled(self):
        d = self.c.get("/api/dangerous").get_json()
        self.assertFalse(d["enabled"])
        self.assertTrue(d["actions"])
        self.assertFalse(any(a["unlocked"] for a in d["actions"]))

    def test_run_refused_and_audited_even_when_unlocked(self):
        # unlock fully via the real settings path
        self.c.put("/api/settings", json=_fully_unlocked("wifi_deauth"))
        before = len(history.list_audit(1000))
        r = self.c.post("/api/dangerous/wifi_deauth/run")
        self.assertEqual(r.status_code, 403)
        body = r.get_json()
        self.assertFalse(body["executed"])
        self.assertFalse(body["allowed"])
        # the attempt must be recorded
        entries = history.list_audit(5)
        self.assertGreater(len(history.list_audit(1000)), before)
        self.assertEqual(entries[0]["action"], "dangerous.run")
        self.assertEqual(entries[0]["target"], "wifi_deauth")

    def test_enabling_master_switch_persists(self):
        self.c.put("/api/settings", json={"dangerous_actions": {"enabled": True}})
        self.assertTrue(settings_store.load()["dangerous_actions"]["enabled"])
        d = self.c.get("/api/dangerous").get_json()
        self.assertTrue(d["enabled"])

    def test_invalid_ack_type_rejected(self):
        r = self.c.put("/api/settings",
                       json={"dangerous_actions": {"acknowledged": {"wifi_deauth": "yes"}}})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
