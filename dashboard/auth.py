"""Dashboard credential store (username + salted password hash).

Replaces the old rotating-token Basic auth with a real, configurable login. The
password is never stored in plaintext: we keep a PBKDF2-HMAC-SHA256 hash with a
per-credential random salt (stdlib only, no extra deps). Sessions themselves are
in-memory in the web process (see app.py), so every restart signs everyone out.

Store file (0600, owner-only - it holds a password hash):
    { "username": "admin",
      "algo": "pbkdf2_sha256", "iterations": N,
      "salt": "<hex>", "hash": "<hex>",
      "must_change": true,          # default admin/admin -> force a change
      "updated": <epoch> }

On first use with no file, the store bootstraps to admin/admin with
must_change=True so a fresh install is reachable but nags you to set a password.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

AUTH_FILE = Path(os.environ.get("PROBE_AUTH_FILE", "/etc/network-probe/dashboard-auth.json"))
ITERATIONS = 240_000
DEFAULT_USER = "admin"
DEFAULT_PASS = "admin"


def _hash(password: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def _make_record(username: str, password: str, must_change: bool) -> dict:
    salt = secrets.token_bytes(16)
    return {
        "username": username.strip() or DEFAULT_USER,
        "algo": "pbkdf2_sha256",
        "iterations": ITERATIONS,
        "salt": salt.hex(),
        "hash": _hash(password, salt),
        "must_change": bool(must_change),
        "updated": int(time.time()),
    }


def _write(record: dict) -> None:
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(AUTH_FILE.parent), prefix=".dashboard-auth-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o600)  # contains a password hash - owner only
        os.replace(tmp, AUTH_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load() -> dict:
    """Return the stored credential record, bootstrapping admin/admin on first
    use. Best-effort: if the file is unreadable/corrupt, fall back to defaults in
    memory (so a broken file never bricks the login)."""
    try:
        rec = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        if isinstance(rec, dict) and rec.get("hash") and rec.get("salt"):
            return rec
    except (OSError, ValueError):
        pass
    rec = _make_record(DEFAULT_USER, DEFAULT_PASS, must_change=True)
    try:
        _write(rec)
    except OSError:
        pass  # read-only fs: still allow login with the in-memory default
    return rec


def verify(username: str, password: str) -> bool:
    """Constant-time-ish check of a username+password against the store."""
    rec = load()
    if (username or "").strip() != rec.get("username"):
        # Still compute a hash to avoid trivial user-enumeration timing.
        _hash(password or "", b"decoy", int(rec.get("iterations", ITERATIONS)))
        return False
    try:
        salt = bytes.fromhex(rec["salt"])
        want = rec["hash"]
    except (KeyError, ValueError):
        return False
    got = _hash(password or "", salt, int(rec.get("iterations", ITERATIONS)))
    return hmac.compare_digest(got, want)


def set_credentials(username: str, new_password: str,
                    must_change: bool = False) -> dict:
    """Replace the stored credentials. Raises ValueError on a weak input."""
    username = (username or "").strip()
    if not username:
        raise ValueError("username is required")
    if len(new_password or "") < 6:
        raise ValueError("password must be at least 6 characters")
    rec = _make_record(username, new_password, must_change)
    _write(rec)
    return rec


def status() -> dict:
    """Non-secret view for the UI - never exposes salt/hash."""
    rec = load()
    return {"username": rec.get("username", DEFAULT_USER),
            "must_change": bool(rec.get("must_change")),
            "updated": rec.get("updated")}
