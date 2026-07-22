"""Read-only reader for the Suricata IDS alert stream (EVE JSON).

The probe runs Suricata as a passive signature-based IDS (see
scripts/install-ids.sh). Suricata writes newline-delimited JSON events to
eve.json; this module tails that file and summarises recent `alert` events for
the dashboard's Security view. It never starts, stops, or reconfigures
Suricata - it only reads.

Design notes:
- Tails a bounded number of bytes from the end of the (potentially large)
  eve.json so it stays cheap regardless of log size.
- Understands the rotated files eve.json.1 / eve.json.<n> so a recent rotation
  does not blank the view.
- Emits a compact JSON summary: engine status, counts by severity/category,
  the top signatures and talkers, and the most recent alert rows.

CLI (used by the dashboard):
  ids_reader.py [--log /var/log/suricata/eve.json] [--limit 100] [--bytes N]
Prints a JSON summary on stdout. Exits 0 even when Suricata is absent - the
'status' field carries that ('not_installed' / 'no_log' / 'ok').
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from collections import Counter

DEFAULT_LOG = "/var/log/suricata/eve.json"
# How much of the tail to read. EVE lines are ~0.5-2 KB; 4 MB covers a few
# thousand recent events without loading a multi-GB file into memory.
DEFAULT_BYTES = 4 * 1024 * 1024
# Severity 1 is most urgent in Suricata's convention.
SEVERITY_LABEL = {1: "critical", 2: "major", 3: "minor", 4: "info"}


def _tail_bytes(path: str, max_bytes: int) -> str:
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()  # discard the partial line we landed in
        return fh.read().decode("utf-8", "replace")


def _iter_alerts(path: str, max_bytes: int):
    """Yield parsed `alert` event dicts from the tail of one eve.json file."""
    for line in _tail_bytes(path, max_bytes).splitlines():
        line = line.strip()
        if not line or line[0] != "{" or '"event_type":"alert"' not in line.replace(" ", ""):
            continue
        try:
            evt = json.loads(line)
        except ValueError:
            continue
        if evt.get("event_type") == "alert":
            yield evt


def _log_family(log: str) -> list[str]:
    """The live log plus any rotated siblings, newest first."""
    found = [p for p in (log, log + ".1") if os.path.exists(p)]
    # Numeric rotations eve.json.2, .3, ... (bounded to a handful).
    for n in range(2, 6):
        p = f"{log}.{n}"
        if os.path.exists(p):
            found.append(p)
    return found


def _engine_status(log: str) -> dict:
    installed = shutil.which("suricata") is not None
    active = False
    if shutil.which("systemctl"):
        try:
            active = subprocess.run(
                ["systemctl", "is-active", "--quiet", "suricata"], timeout=5
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            active = False
    out = {"installed": installed, "service_active": active, "log": log}
    if os.path.exists(log):
        st = os.stat(log)
        out["log_size"] = st.st_size
        out["log_age_seconds"] = max(0, int(time.time() - st.st_mtime))
    return out


def collect(log: str, limit: int, max_bytes: int) -> dict:
    status = _engine_status(log)
    if not status["installed"]:
        return {"status": "not_installed", "engine": status, "alerts": [],
                "note": "Suricata is not installed. Run scripts/install-ids.sh --apply."}
    files = _log_family(log)
    if not files:
        return {"status": "no_log", "engine": status, "alerts": [],
                "note": "No eve.json yet - Suricata may be starting or seeing no traffic."}

    rows: list[dict] = []
    # Read newest file first; stop once we have comfortably more than `limit`.
    for path in files:
        for evt in _iter_alerts(path, max_bytes):
            a = evt.get("alert", {})
            sev = a.get("severity")
            rows.append({
                "time": evt.get("timestamp", "")[:19].replace("T", " "),
                "severity": sev,
                "severity_label": SEVERITY_LABEL.get(sev, str(sev)),
                "signature": a.get("signature", "(unknown)"),
                "category": a.get("category", ""),
                "sid": a.get("signature_id"),
                "proto": evt.get("proto", ""),
                "src": evt.get("src_ip", ""),
                "sport": evt.get("src_port"),
                "dst": evt.get("dest_ip", ""),
                "dport": evt.get("dest_port"),
                "flow_id": evt.get("flow_id"),
                "app_proto": evt.get("app_proto", ""),
            })
        if len(rows) >= limit * 4:
            break

    rows.sort(key=lambda r: r["time"], reverse=True)
    recent = rows[:limit]

    by_sev = Counter(r["severity_label"] for r in rows)
    by_cat = Counter(r["category"] for r in rows if r["category"])
    by_sig = Counter(r["signature"] for r in rows)
    by_src = Counter(r["src"] for r in rows if r["src"])
    return {
        "status": "ok",
        "engine": status,
        "total_alerts_scanned": len(rows),
        "by_severity": dict(by_sev),
        "top_categories": by_cat.most_common(8),
        "top_signatures": by_sig.most_common(8),
        "top_sources": by_src.most_common(8),
        "alerts": recent,
    }


def detail(log: str, flow_id: str, max_bytes: int) -> dict:
    """Every EVE event sharing one flow_id - the alert plus any correlated
    http/dns/tls/fileinfo/flow records. This is the 'everything around this
    alert' drill-down for the dashboard."""
    files = _log_family(log)
    if not files:
        return {"status": "no_log", "flow_id": flow_id, "events": []}
    fid = str(flow_id)
    events: list[dict] = []
    for path in files:
        for line in _tail_bytes(path, max_bytes).splitlines():
            line = line.strip()
            # Cheap pre-filter: the flow id must appear literally on the line.
            if not line or line[0] != "{" or fid not in line:
                continue
            try:
                evt = json.loads(line)
            except ValueError:
                continue
            if str(evt.get("flow_id", "")) == fid:
                events.append(evt)
    events.sort(key=lambda e: e.get("timestamp", ""))
    alert = next((e for e in events if e.get("event_type") == "alert"), None)
    return {
        "status": "ok" if events else "not_found",
        "flow_id": flow_id,
        "count": len(events),
        "event_types": sorted({e.get("event_type", "") for e in events}),
        "alert": alert,
        "events": events[:200],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarise recent Suricata IDS alerts (read-only).")
    ap.add_argument("--log", default=os.environ.get("PROBE_IDS_LOG", DEFAULT_LOG))
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--bytes", type=int, default=DEFAULT_BYTES, dest="max_bytes")
    ap.add_argument("--flow", default="", help="return every EVE event for this flow_id")
    args = ap.parse_args()
    limit = max(1, min(args.limit, 1000))
    try:
        if args.flow:
            result = detail(args.log, args.flow, max(65536, args.max_bytes))
        else:
            result = collect(args.log, limit, max(65536, args.max_bytes))
    except PermissionError:
        result = {"status": "no_access", "alerts": [],
                  "note": f"Cannot read {args.log}. The dashboard account needs group read on /var/log/suricata."}
    except OSError as exc:
        result = {"status": "error", "alerts": [], "note": str(exc)}
    json.dump(result, __import__("sys").stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
