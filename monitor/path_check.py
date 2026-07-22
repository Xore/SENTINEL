"""Read-only path-health profile: route, path MTU, latency and loss.

The dashboard's "Path" health profile runs this against one host. Everything it
does is passive/safe-active in the probe's model: an ICMP/UDP tracepath (the
same probe traffic `tracepath` always sends), an unprivileged ICMP echo run for
latency/loss, and - only when a port is given - one bounded TCP connect. It
never sends OT payloads, never sweeps a range and never writes.

CLI:
  path_check.py --host <ip|name> [--port N] [--count 10]
Prints one JSON object on stdout; exits 0 even on partial failure (each section
carries its own ok/error).
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import time


def _run(cmd: list[str], timeout: float) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return r.returncode, r.stdout + r.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def check_route(host: str) -> dict:
    """tracepath: hop list plus the discovered path MTU."""
    code, out = _run(["tracepath", "-n", "-m", "20", host], 35)
    if code == 127:
        return {"ok": False, "error": out.strip()}
    hops, seen = [], set()
    for line in out.splitlines():
        m = re.match(r"\s*(\d+):\s+(\S+)\s+(.*)", line)
        if not m:
            continue
        hopno, addr = m.group(1), m.group(2)
        if addr in ("no", "reply") or addr == "[LOCALHOST]":
            continue
        rtt = re.search(r"([\d.]+)ms", m.group(3))
        key = (hopno, addr)
        if key in seen:
            continue
        seen.add(key)
        hops.append({"hop": int(hopno), "address": addr,
                     "rtt_ms": float(rtt.group(1)) if rtt else None})
    pmtu = re.findall(r"pmtu (\d+)", out)
    reached = "reached" in out.lower()
    return {"ok": bool(hops), "hops": hops, "hop_count": len({h["hop"] for h in hops}),
            "pmtu": int(pmtu[-1]) if pmtu else None, "reached": reached,
            "error": "" if hops else "no hops parsed"}


def check_latency(host: str, count: int) -> dict:
    """Unprivileged ICMP echo run: loss and RTT min/avg/max/jitter."""
    count = max(3, min(count, 30))
    code, out = _run(["ping", "-n", "-c", str(count), "-w", str(count + 5), host], count + 12)
    if code == 127:
        return {"ok": False, "error": out.strip()}
    loss = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
    recv = re.search(r"(\d+) received", out)
    rtt = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", out)
    ok = rtt is not None or (recv is not None and int(recv.group(1)) > 0)
    return {"ok": ok, "sent": count,
            "received": int(recv.group(1)) if recv else None,
            "loss_pct": float(loss.group(1)) if loss else (100.0 if not ok else None),
            "rtt_min_ms": float(rtt.group(1)) if rtt else None,
            "rtt_avg_ms": float(rtt.group(2)) if rtt else None,
            "rtt_max_ms": float(rtt.group(3)) if rtt else None,
            "jitter_ms": float(rtt.group(4)) if rtt else None,
            "error": "" if ok else "no echo replies (host may block ICMP)"}


def check_tcp(host: str, port: int) -> dict:
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=5):
            return {"open": True, "port": port, "connect_ms": round((time.monotonic() - start) * 1000, 1)}
    except OSError as exc:
        return {"open": False, "port": port, "error": str(exc)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only route/MTU/latency/loss profile.")
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--count", type=int, default=10)
    args = ap.parse_args()
    result = {"host": args.host, "route": check_route(args.host),
              "latency": check_latency(args.host, args.count)}
    if 0 < args.port < 65536:
        result["tcp"] = check_tcp(args.host, args.port)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
