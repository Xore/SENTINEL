"""Tests for the thin frontend reverse-proxy (dashboard.frontend, #35).

The frontend serves the static SPA locally and proxies everything else to the
backend. It imports nothing from the backend, so these tests never touch app.py
or a database — they monkeypatch urllib.request.urlopen to stand in for the
backend and assert the proxy's forwarding/error behaviour. Auth is delegated to
the backend, so the proxy must pass the request Cookie inbound and the backend
Set-Cookie outbound untouched, and must never gate anything itself.
"""
from __future__ import annotations

import io
import unittest
import urllib.error
import urllib.request

from dashboard import frontend


class _FakeResp:
    """Minimal stand-in for the object urlopen returns as a context manager."""

    def __init__(self, body: bytes, status: int = 200, headers=None):
        self._body = body
        self.status = status
        self._headers = list(headers or [])

    def read(self):
        return self._body

    def getheaders(self):
        return self._headers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FrontendProxyTests(unittest.TestCase):
    def setUp(self):
        frontend.app.testing = True
        self.client = frontend.app.test_client()
        self._real_urlopen = urllib.request.urlopen

    def tearDown(self):
        urllib.request.urlopen = self._real_urlopen

    def _patch_backend(self, handler):
        """Route urlopen to `handler(req) -> _FakeResp` (or raise)."""
        urllib.request.urlopen = lambda req, timeout=None: handler(req)

    # --- static shell is always served locally, no auth, no backend ---
    def test_shell_served_without_auth_or_backend(self):
        def boom(req):
            raise AssertionError("shell must not hit the backend")

        self._patch_backend(boom)
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("WWW-Authenticate", resp.headers)  # no proxy auth layer

    # --- an ordinary API call is proxied through with method/status/body ---
    def test_api_call_is_proxied(self):
        seen = {}

        def handler(req):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            return _FakeResp(b'{"ok":true}', 200, [("Content-Type", "application/json")])

        self._patch_backend(handler)
        resp = self.client.get("/api/auth/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"ok": True})
        self.assertTrue(seen["url"].endswith("/api/auth/status"))
        self.assertEqual(seen["method"], "GET")

    def test_query_string_is_forwarded(self):
        seen = {}

        def handler(req):
            seen["url"] = req.full_url
            return _FakeResp(b"[]", 200)

        self._patch_backend(handler)
        self.client.get("/api/map?collector=abc123")
        self.assertIn("?collector=abc123", seen["url"])

    # --- auth delegation: Cookie flows in, Set-Cookie flows back out ---
    def test_request_cookie_is_forwarded_to_backend(self):
        seen = {}

        def handler(req):
            seen["cookie"] = req.get_header("Cookie")
            return _FakeResp(b"{}", 200)

        self._patch_backend(handler)
        # The werkzeug test client carries cookies via its jar, not a raw header.
        self.client.set_cookie("np_session", "deadbeef")
        self.client.get("/api/whoami")
        self.assertEqual(seen["cookie"], "np_session=deadbeef")

    def test_backend_set_cookie_is_returned_to_client(self):
        def handler(req):
            return _FakeResp(b'{"ok":true}', 200, [("Set-Cookie", "np_session=xyz; Path=/; HttpOnly")])

        self._patch_backend(handler)
        resp = self.client.post("/api/login")
        self.assertIn("np_session=xyz", resp.headers.get("Set-Cookie", ""))

    # --- backend rejection (401) must pass straight through, not be masked ---
    def test_backend_401_passes_through(self):
        def handler(req):
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized",
                {"Content-Type": "application/json"},
                io.BytesIO(b'{"error":"authentication required","login_required":true}'),
            )

        self._patch_backend(handler)
        resp = self.client.get("/api/devices")
        self.assertEqual(resp.status_code, 401)
        self.assertTrue(resp.get_json()["login_required"])

    # --- backend down → 502 JSON so the UI can show an offline banner ---
    def test_backend_offline_returns_502(self):
        def handler(req):
            raise urllib.error.URLError("connection refused")

        self._patch_backend(handler)
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 502)
        body = resp.get_json()
        self.assertFalse(body["backend"])
        self.assertEqual(body["error"], "backend offline")

    # --- POST body is forwarded to the backend ---
    def test_post_body_is_forwarded(self):
        seen = {}

        def handler(req):
            seen["body"] = req.data
            seen["method"] = req.get_method()
            return _FakeResp(b"{}", 200)

        self._patch_backend(handler)
        self.client.post("/api/login", data=b'{"user":"admin"}',
                         content_type="application/json")
        self.assertEqual(seen["body"], b'{"user":"admin"}')
        self.assertEqual(seen["method"], "POST")


if __name__ == "__main__":
    unittest.main()
