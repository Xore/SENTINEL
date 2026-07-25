"""Thin, independent frontend server for the Network Probe dashboard.

This process serves ONLY the static single-page app (index.html, monitor.html
and /static/*) and reverse-proxies every other path to the backend API on an
internal port. It deliberately imports nothing from the backend (app.py) so it
keeps serving the shell even when the backend is down or restarting — API calls
then return 502 and the UI shows a "backend offline" banner instead of the whole
dashboard being unreachable.

Auth is DELEGATED to the backend: it is the single source of truth for the
username/password session login (see app.py require_session). The proxy adds no
auth layer of its own — it forwards the request `Cookie` header inbound and the
backend's `Set-Cookie` outbound, so the np_session cookie flows through
transparently. The static shell is always served unauthenticated (like any SPA)
so the login modal can render; every /api call is governed by the backend.

Run under waitress:  waitress-serve --listen=<addr>:8088 dashboard.frontend:app
The backend runs on PROBE_BACKEND_URL (default http://127.0.0.1:8090).
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, Response, render_template, request, send_from_directory

ROOT = Path(__file__).resolve().parent
BACKEND_URL = os.environ.get("PROBE_BACKEND_URL", "http://127.0.0.1:8090").rstrip("/")
PROXY_TIMEOUT = float(os.environ.get("PROBE_PROXY_TIMEOUT", "60"))

# Hop-by-hop headers must not be forwarded (RFC 7230 §6.1). Note: `set-cookie`
# and `cookie` are deliberately NOT here — they must pass through both ways so
# the backend's session login governs auth across the proxy.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length", "host",
}

app = Flask(__name__, static_folder=str(ROOT / "static"), template_folder=str(ROOT / "templates"))


# --- Static SPA, served locally so it survives the backend being down ---
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/monitor")
def monitor():
    return render_template("monitor.html")


@app.get("/static/<path:name>")
def static_files(name: str):
    return send_from_directory(app.static_folder, name)


# --- Everything else is proxied to the backend API ---
def _proxy(path: str) -> Response:
    url = f"{BACKEND_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('latin-1')}"
    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    body = request.get_data() if request.method not in ("GET", "HEAD") else None
    proxy_req = urllib.request.Request(url, data=body, method=request.method, headers=fwd_headers)
    try:
        with urllib.request.urlopen(proxy_req, timeout=PROXY_TIMEOUT) as resp:
            content = resp.read()
            status = resp.status
            headers = [(k, v) for k, v in resp.getheaders() if k.lower() not in HOP_BY_HOP]
    except urllib.error.HTTPError as exc:  # backend replied with 4xx/5xx — pass it through
        content = exc.read()
        status = exc.code
        headers = [(k, v) for k, v in (exc.headers.items() if exc.headers else []) if k.lower() not in HOP_BY_HOP]
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return app.response_class(
            '{"error":"backend offline","backend":false}\n', 502, {"Content-Type": "application/json"}
        )
    return Response(content, status=status, headers=headers)


@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def proxy_path(path: str) -> Response:
    return _proxy(path)


if __name__ == "__main__":
    app.run(host=os.environ.get("PROBE_BIND", "127.0.0.1"),
            port=int(os.environ.get("PROBE_FRONTEND_PORT", "8088")), debug=False)
