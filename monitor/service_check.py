"""Read-only service-health profile: DNS, clock/NTP, TCP, TLS and HTTP.

The dashboard's "Service health" action runs this against one host. It is a
Level-1/2 *safe active* check in the probe's model: a single DNS query to the
resolver, a local clock read, one bounded TCP connect, one TLS handshake (no
data sent beyond ClientHello) and at most one HTTP GET. It never sends OT
payloads, never scans a range and never writes - TLS/HTTP are only attempted on
standard web/TLS ports so pointing it at an OT device just yields DNS + clock +
a TCP connect.

CLI:
  service_check.py --host <ip|name> [--port 443] [--name <dns-name>]
Prints one JSON object on stdout; exits 0 even on partial failure (each section
carries its own ok/error).
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import subprocess
import time

WEB_PORTS = {80, 443, 8080, 8443, 8000, 8888}
TLS_PORTS = {443, 8443, 993, 995, 465, 636, 989, 990, 5061}


def _run(cmd: list[str], timeout: float, stdin: str = "") -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           input=stdin, check=False)
        return r.returncode, r.stdout + r.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def check_dns(name: str) -> dict:
    """One resolver query for `name` (A/AAAA), with server and timing."""
    code, out = _run(["dig", "+tries=1", "+time=2", "+noall", "+answer", "+stats", name], 6)
    if code == 127:
        return {"ok": False, "error": out.strip()}
    answers = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] in ("A", "AAAA", "CNAME", "PTR"):
            answers.append(f"{parts[3]} {parts[4]}")
    qtime = re.search(r"Query time:\s*(\d+)\s*msec", out)
    server = re.search(r"SERVER:\s*([^\s#]+)", out)
    return {"ok": bool(answers), "query": name, "answers": answers,
            "server": server.group(1) if server else "",
            "time_ms": int(qtime.group(1)) if qtime else None,
            "error": "" if answers else "no answer records"}


def check_clock() -> dict:
    """Probe clock/NTP discipline from chrony (offset, stratum, source)."""
    code, out = _run(["chronyc", "-n", "tracking"], 5)
    if code != 0:
        return {"ok": False, "error": (out or "chronyc unavailable").strip()[:200]}
    fields = {}
    for line in out.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()
    stratum = fields.get("Stratum", "")
    offset = fields.get("Last offset", "")
    off_m = re.search(r"([-+]?\d+\.?\d*)", offset)
    return {"ok": True, "stratum": stratum, "reference": fields.get("Reference ID", ""),
            "last_offset_s": float(off_m.group(1)) if off_m else None,
            "leap": fields.get("Leap status", ""), "source": fields.get("Reference ID", "")}


def check_tcp(host: str, port: int) -> dict:
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=5):
            return {"open": True, "connect_ms": round((time.monotonic() - start) * 1000, 1)}
    except OSError as exc:
        return {"open": False, "error": str(exc)}


def check_tls(host: str, port: int, name: str) -> dict:
    """Certificate + handshake facts via a single TLS connection (no app data)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # read the cert even if self-signed (switches/APs)
    try:
        with socket.create_connection((host, port), timeout=6) as raw:
            with ctx.wrap_socket(raw, server_hostname=name or host) as tls:
                version = tls.version()
                cipher = tls.cipher()
                der = tls.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError) as exc:
        return {"ok": False, "error": str(exc)}
    info = _parse_cert_der(der)
    return {"ok": True, "version": version, "cipher": cipher[0] if cipher else "", **info}


def _parse_cert_der(der: bytes) -> dict:
    """Subject/issuer/validity/SANs via openssl x509 on the DER cert."""
    # subprocess must run in binary mode - DER is not text.
    try:
        r = subprocess.run(["openssl", "x509", "-inform", "DER", "-noout", "-subject",
                            "-issuer", "-enddate", "-startdate", "-ext", "subjectAltName"],
                           input=der, capture_output=True, timeout=6, check=False)
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}
    subject = re.search(r"subject=(.*)", out)
    issuer = re.search(r"issuer=(.*)", out)
    notafter = re.search(r"notAfter=(.*)", out)
    sans = re.findall(r"DNS:([^,\s]+)", out)
    days_left = None
    if notafter:
        try:
            exp = time.strptime(notafter.group(1).strip(), "%b %d %H:%M:%S %Y %Z")
            days_left = round((time.mktime(exp) - time.time()) / 86400, 1)
        except (ValueError, OverflowError):
            days_left = None
    return {"subject": subject.group(1).strip() if subject else "",
            "issuer": issuer.group(1).strip() if issuer else "",
            "not_after": notafter.group(1).strip() if notafter else "",
            "days_left": days_left, "sans": sans[:20]}


def check_http(host: str, port: int) -> dict:
    scheme = "https" if port in TLS_PORTS else "http"
    url = f"{scheme}://{host}:{port}/"
    fmt = "%{http_code}|%{time_namelookup}|%{time_connect}|%{time_appconnect}|%{time_starttransfer}|%{time_total}|%{url_effective}|%{redirect_url}"
    code, out = _run(["curl", "-sS", "-k", "-m", "8", "-o", "/dev/null", "-w", fmt, url], 10)
    if "|" not in out:
        return {"ok": False, "url": url, "error": out.strip()[:200]}
    p = out.strip().split("|")
    ms = lambda v: round(float(v) * 1000, 1) if v else None
    return {"ok": p[0] not in ("000", ""), "url": url, "status": p[0],
            "times_ms": {"dns": ms(p[1]), "connect": ms(p[2]), "tls": ms(p[3]),
                         "ttfb": ms(p[4]), "total": ms(p[5])},
            "final_url": p[6] if len(p) > 6 else "", "redirect": p[7] if len(p) > 7 else ""}


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only DNS/clock/TCP/TLS/HTTP service health.")
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=443)
    ap.add_argument("--name", default="")
    args = ap.parse_args()
    host, port = args.host, args.port
    name = args.name or host
    result = {"host": host, "port": port, "name": name,
              "dns": check_dns(name), "clock": check_clock(), "tcp": check_tcp(host, port)}
    if port in TLS_PORTS:
        result["tls"] = check_tls(host, port, name)
    if port in WEB_PORTS or port in TLS_PORTS:
        result["http"] = check_http(host, port)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
