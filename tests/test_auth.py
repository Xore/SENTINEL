"""Auth tests: login/logout, password change, and sessions-die-on-restart.

Runs with auth ENABLED against an isolated credential store, unlike
test_backend.py which disables auth. Both import the same dashboard.app module,
so we pin the auth toggle + store path on the module after import (import order
between test modules is not guaranteed).

Run:  python -m unittest discover -s tests   (or scripts/run-tests.sh)
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Shared isolation env before the app import (see _isolation).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolation  # noqa: E402,F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import app as appmod  # noqa: E402
from dashboard import auth  # noqa: E402


class AuthTest(unittest.TestCase):
    def setUp(self):
        # Pin auth ON + our store here (import order between test modules can flip
        # the shared module-level toggle, so re-assert it per test).
        appmod.AUTH_DISABLED = False
        auth.AUTH_FILE = Path(os.environ["PROBE_AUTH_FILE"])
        # Fresh store (bootstraps admin/admin) + empty session table each test.
        try:
            auth.AUTH_FILE.unlink()
        except OSError:
            pass
        appmod.SESSIONS.clear()
        self.c = appmod.app.test_client()

    def login(self, user="admin", password="admin"):
        return self.c.post("/api/login", json={"username": user, "password": password})

    # --- gate ------------------------------------------------------------------
    def test_api_blocked_without_session(self):
        r = self.c.get("/api/network")
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.get_json().get("login_required"))

    def test_shell_and_status_are_open(self):
        self.assertEqual(self.c.get("/healthz").status_code, 200)
        r = self.c.get("/api/auth/status").get_json()
        self.assertTrue(r["auth_enabled"])
        self.assertFalse(r["authenticated"])

    # --- login -----------------------------------------------------------------
    def test_default_admin_login_and_must_change(self):
        r = self.login()
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["must_change"])  # default admin/admin nags
        # cookie now grants access to a protected API
        self.assertEqual(self.c.get("/api/network").status_code, 200)

    def test_bad_password_rejected(self):
        self.assertEqual(self.login(password="nope").status_code, 401)
        self.assertEqual(self.c.get("/api/network").status_code, 401)

    def test_logout_clears_session(self):
        self.login()
        self.assertEqual(self.c.get("/api/network").status_code, 200)
        self.c.post("/api/logout")
        self.assertEqual(self.c.get("/api/network").status_code, 401)

    # --- password change -------------------------------------------------------
    def test_change_password_requires_current(self):
        self.login()
        r = self.c.post("/api/auth/password",
                        json={"current_password": "wrong", "new_password": "sup3rsecret"})
        self.assertEqual(r.status_code, 403)

    def test_change_password_then_relogin(self):
        self.login()
        r = self.c.post("/api/auth/password",
                        json={"current_password": "admin", "new_password": "sup3rsecret"})
        self.assertEqual(r.status_code, 200)
        # old password no longer works; new one does; must_change cleared
        fresh = appmod.app.test_client()
        self.assertEqual(fresh.post("/api/login",
                         json={"username": "admin", "password": "admin"}).status_code, 401)
        ok = fresh.post("/api/login", json={"username": "admin", "password": "sup3rsecret"})
        self.assertEqual(ok.status_code, 200)
        self.assertFalse(ok.get_json()["must_change"])

    def test_weak_new_password_rejected(self):
        self.login()
        r = self.c.post("/api/auth/password",
                        json={"current_password": "admin", "new_password": "x"})
        self.assertEqual(r.status_code, 400)

    def test_password_change_invalidates_other_sessions(self):
        self.login()                       # session A (self.c)
        other = appmod.app.test_client()
        other.post("/api/login", json={"username": "admin", "password": "admin"})  # session B
        self.assertEqual(other.get("/api/network").status_code, 200)
        # A changes the password -> B's session must be dropped, A keeps working
        self.c.post("/api/auth/password",
                    json={"current_password": "admin", "new_password": "sup3rsecret"})
        self.assertEqual(self.c.get("/api/network").status_code, 200)
        self.assertEqual(other.get("/api/network").status_code, 401)

    # --- sessions die on restart -----------------------------------------------
    def test_sessions_die_on_restart(self):
        self.login()
        self.assertEqual(self.c.get("/api/network").status_code, 200)
        appmod.SESSIONS.clear()            # simulate a process restart
        self.assertEqual(self.c.get("/api/network").status_code, 401)

    # --- store never leaks the hash --------------------------------------------
    def test_status_hides_secrets(self):
        s = auth.status()
        self.assertIn("username", s)
        self.assertNotIn("hash", s)
        self.assertNotIn("salt", s)

    def test_stored_password_is_hashed_not_plaintext(self):
        auth.load()  # bootstrap
        raw = auth.AUTH_FILE.read_text(encoding="utf-8")
        self.assertNotIn("admin\"", raw.replace('"username": "admin"', ""))
        self.assertIn("pbkdf2_sha256", raw)


if __name__ == "__main__":
    unittest.main()
