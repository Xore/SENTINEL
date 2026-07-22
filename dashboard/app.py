from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
CAPTURE_DIR = Path(os.environ.get("PROBE_CAPTURE_DIR", ROOT / "captures")).resolve()
SNAPSHOT_DIR = Path(os.environ.get("PROBE_SNAPSHOT_DIR", ROOT / "snapshots")).resolve()
TARGET_FILE = Path(os.environ.get("PROBE_TARGET_FILE", ROOT / "config" / "targets.csv")).resolve()
MONITOR_DB = Path(os.environ.get("PROBE_MONITOR_DB", "/var/lib/network-probe/monitor.db"))
MAX_OUTPUT = 120_000
NAME_RE = re.compile(r"^[A-Za-z0-9._:-]+$")

app = Flask(__name__)
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()

AUTH_TOKEN_FILE = Path(os.environ.get("PROBE_AUTH_TOKEN_FILE", "/etc/network-probe/dashboard-token"))


def auth_token() -> str:
    """Non-empty token = HTTP Basic auth required (any username). The install
    script generates the token; an empty/missing file disables auth, which is
    acceptable only when the dashboard binds to 127.0.0.1."""
    try:
        return AUTH_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@app.before_request
def require_token():
    token = auth_token()
    if not token or request.path == "/healthz":
        return None
    supplied = request.authorization
    if supplied and supplied.password == token:
        return None
    return app.response_class(
        "Authentication required.\n", 401, {"WWW-Authenticate": 'Basic realm="network-probe"'}
    )


def run(command: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        output = (result.stdout + result.stderr)[-MAX_OUTPUT:]
        return result.returncode, output
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def interfaces() -> list[dict]:
    found = []
    net_root = Path("/sys/class/net")
    if not net_root.exists():
        return found
    for item in sorted(net_root.iterdir()):
        name = item.name
        _, address_text = run(["ip", "-brief", "address", "show", "dev", name])
        stats = {}
        for key in ("rx_bytes", "rx_packets", "rx_dropped", "rx_errors", "tx_bytes", "tx_packets", "tx_dropped", "tx_errors"):
            try:
                stats[key] = int((item / "statistics" / key).read_text().strip())
            except (OSError, ValueError):
                stats[key] = 0
        found.append({
            "name": name,
            "state": (item / "operstate").read_text().strip(),
            "mac": (item / "address").read_text().strip(),
            "addresses": address_text.strip(),
            "capture_safe": not bool(re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}/|\b[0-9a-fA-F:]+/", address_text)),
            **stats,
        })
    return found


def targets() -> list[dict]:
    if not TARGET_FILE.is_file():
        return []
    rows = []
    with TARGET_FILE.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(line for line in handle if not line.lstrip().startswith("#")):
            if len(row) != 4:
                continue
            name, address, protocol, port = (value.strip() for value in row)
            if NAME_RE.fullmatch(name) and NAME_RE.fullmatch(address) and protocol in {"tcp", "s7-tcp", "opcua-tcp"} and port.isdigit():
                rows.append({"name": name, "address": address, "protocol": protocol, "port": int(port)})
    return rows


def launch_job(kind: str, command: list[str], timeout: int = 120) -> str:
    job_id = uuid.uuid4().hex[:12]
    with jobs_lock:
        jobs[job_id] = {"id": job_id, "kind": kind, "state": "running", "started": time.time(), "output": ""}

    def worker() -> None:
        code, output = run(command, timeout)
        with jobs_lock:
            jobs[job_id].update(state="complete" if code == 0 else "failed", code=code, output=output, ended=time.time())

    threading.Thread(target=worker, daemon=True).start()
    return job_id


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    disk = shutil.disk_usage(CAPTURE_DIR if CAPTURE_DIR.exists() else ROOT)
    return jsonify({
        "time": time.time(),
        "hostname": os.uname().nodename if hasattr(os, "uname") else "probe",
        "uptime_seconds": float(Path("/proc/uptime").read_text().split()[0]) if Path("/proc/uptime").exists() else 0,
        "load": list(os.getloadavg()) if hasattr(os, "getloadavg") else [0, 0, 0],
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free},
        "tools": {name: bool(shutil.which(name)) for name in ("dumpcap", "tshark", "nmap", "tracepath", "iw", "zeek", "suricata", "ntopng")},
        "interfaces": interfaces(),
        "targets": targets(),
    })


@app.get("/api/jobs")
def list_jobs():
    with jobs_lock:
        return jsonify(list(jobs.values())[-25:])


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


@app.post("/api/check/<name>")
def check_target(name: str):
    target = next((item for item in targets() if item["name"] == name), None)
    if not target:
        return jsonify(error="Target is not in the approved target file"), 404
    command = ["nmap", "-n", "-Pn", "-sT", "-T2", "--max-retries", "1", "--host-timeout", "10s", "-p", str(target["port"]), "--", target["address"]]
    return jsonify(job_id=launch_job("reachability", command, 20)), 202


@app.post("/api/trace/<name>")
def trace_target(name: str):
    target = next((item for item in targets() if item["name"] == name), None)
    if not target:
        return jsonify(error="Target is not in the approved target file"), 404
    return jsonify(job_id=launch_job("route", ["tracepath", "-n", target["address"]], 45)), 202


@app.post("/api/capture")
def capture():
    payload = request.get_json(silent=True) or {}
    iface = str(payload.get("interface", ""))
    try:
        seconds = int(payload.get("seconds", 300))
        files = int(payload.get("files", 12))
        size = int(payload.get("size_mib", 512))
    except (TypeError, ValueError):
        return jsonify(error="Capture limits must be numbers"), 400
    selected = next((item for item in interfaces() if item["name"] == iface), None)
    if not selected or not selected["capture_safe"]:
        return jsonify(error="Select an existing interface with no IP address"), 400
    if not (30 <= seconds <= 3600 and 1 <= files <= 96 and 16 <= size <= 4096):
        return jsonify(error="Capture limits are outside the allowed range"), 400
    command = [str(ROOT / "scripts" / "capture-pcapng.sh"), iface, str(CAPTURE_DIR), str(seconds), str(files), str(size)]
    return jsonify(job_id=launch_job("capture", command, seconds * files + 120)), 202


@app.post("/api/snapshot")
def system_snapshot():
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return jsonify(job_id=launch_job("system-snapshot", [str(ROOT / "scripts" / "network-snapshot.sh"), str(SNAPSHOT_DIR)], 90)), 202


@app.post("/api/l2-health")
def l2_health():
    payload = request.get_json(silent=True) or {}
    iface = str(payload.get("interface", ""))
    try:
        duration = int(payload.get("duration", 30))
    except (TypeError, ValueError):
        return jsonify(error="Duration must be a number"), 400
    selected = next((item for item in interfaces() if item["name"] == iface), None)
    if not selected or not selected["capture_safe"]:
        return jsonify(error="Select an existing no-IP capture interface"), 400
    if not 5 <= duration <= 120:
        return jsonify(error="Duration must be 5-120 seconds"), 400
    command = [str(ROOT / "scripts" / "l2-health.sh"), iface, str(duration)]
    return jsonify(job_id=launch_job("layer2-health", command, duration + 45)), 202


@app.get("/api/captures")
def captures():
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    result = []
    for path in sorted(CAPTURE_DIR.glob("*.pcapng"), key=lambda value: value.stat().st_mtime, reverse=True)[:100]:
        stat = path.stat()
        result.append({"name": path.name, "size": stat.st_size, "modified": stat.st_mtime})
    return jsonify(result)


@app.post("/api/summarize/<path:name>")
def summarize(name: str):
    safe_name = Path(name).name
    path = (CAPTURE_DIR / safe_name).resolve()
    if path.parent != CAPTURE_DIR or not path.is_file() or path.suffix != ".pcapng":
        return jsonify(error="Capture not found"), 404
    return jsonify(job_id=launch_job("pcap-summary", [str(ROOT / "scripts" / "pcap-summary.sh"), str(path)], 300)), 202


@app.get("/api/download/<path:name>")
def download(name: str):
    return send_from_directory(CAPTURE_DIR, Path(name).name, as_attachment=True)


@app.get("/api/wifi")
def wifi():
    devices = []
    for iface in interfaces():
        code, info = run(["iw", "dev", iface["name"], "info"], 3)
        if code == 0:
            _, station = run(["iw", "dev", iface["name"], "link"], 3)
            devices.append({"interface": iface["name"], "info": info, "link": station})
    return jsonify(devices)


def monitor_db() -> sqlite3.Connection | None:
    if not MONITOR_DB.is_file():
        return None
    db = sqlite3.connect(f"file:{MONITOR_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


@app.get("/monitor")
def monitor_page():
    return render_template("monitor.html")


@app.get("/api/monitor/series")
def monitor_series():
    """Downsampled ping series: per target, per bucket -> loss %% and median-ish RTT."""
    db = monitor_db()
    if db is None:
        return jsonify(error="monitor database not found; is the outage monitor running?"), 503
    try:
        minutes = max(5, min(int(request.args.get("minutes", 60)), 14 * 1440))
    except ValueError:
        return jsonify(error="minutes must be a number"), 400
    since = time.time() - minutes * 60
    bucket = max(1, minutes * 60 // 600)  # aim for <=600 points per target
    rows = db.execute(
        """
        SELECT target,
               CAST(ts / ? AS INTEGER) * ? AS bucket_ts,
               COUNT(*) AS total,
               SUM(ok) AS ok,
               AVG(CASE WHEN ok = 1 THEN rtt_ms END) AS rtt_avg,
               MAX(CASE WHEN ok = 1 THEN rtt_ms END) AS rtt_max
        FROM ping_samples WHERE ts >= ?
        GROUP BY target, bucket_ts ORDER BY bucket_ts
        """,
        (bucket, bucket, since),
    ).fetchall()
    series: dict[str, dict] = {}
    for row in rows:
        entry = series.setdefault(row["target"], {"ts": [], "loss_pct": [], "rtt_avg": [], "rtt_max": []})
        entry["ts"].append(row["bucket_ts"])
        entry["loss_pct"].append(round(100.0 * (row["total"] - row["ok"]) / row["total"], 1) if row["total"] else None)
        entry["rtt_avg"].append(round(row["rtt_avg"], 2) if row["rtt_avg"] is not None else None)
        entry["rtt_max"].append(round(row["rtt_max"], 2) if row["rtt_max"] is not None else None)
    wifi = db.execute(
        """
        SELECT CAST(ts / ? AS INTEGER) * ? AS bucket_ts,
               interface, MIN(connected) AS connected, AVG(signal_dbm) AS signal_dbm,
               AVG(tx_bitrate_mbps) AS tx_bitrate, MAX(tx_retries) AS tx_retries, MAX(tx_failed) AS tx_failed
        FROM wifi_samples WHERE ts >= ? GROUP BY interface, bucket_ts ORDER BY bucket_ts
        """,
        (bucket, bucket, since),
    ).fetchall()
    wifi_series: dict[str, dict] = {}
    for row in wifi:
        entry = wifi_series.setdefault(row["interface"], {"ts": [], "connected": [], "signal_dbm": [], "tx_bitrate": [], "tx_retries": [], "tx_failed": []})
        entry["ts"].append(row["bucket_ts"])
        entry["connected"].append(row["connected"])
        entry["signal_dbm"].append(round(row["signal_dbm"], 1) if row["signal_dbm"] is not None else None)
        entry["tx_bitrate"].append(round(row["tx_bitrate"], 1) if row["tx_bitrate"] is not None else None)
        entry["tx_retries"].append(row["tx_retries"])
        entry["tx_failed"].append(row["tx_failed"])
    db.close()
    return jsonify({"bucket_seconds": bucket, "since": since, "ping": series, "wifi": wifi_series})


@app.get("/api/monitor/events")
def monitor_events():
    db = monitor_db()
    if db is None:
        return jsonify(error="monitor database not found; is the outage monitor running?"), 503
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 500))
    except ValueError:
        return jsonify(error="limit must be a number"), 400
    rows = db.execute(
        "SELECT id, started, ended, kind, failed_targets, snapshot FROM events ORDER BY started DESC LIMIT ?",
        (limit,),
    ).fetchall()
    db.close()
    return jsonify([
        {
            "id": row["id"],
            "started": row["started"],
            "ended": row["ended"],
            "duration_s": round(row["ended"] - row["started"], 1) if row["ended"] else None,
            "kind": row["kind"],
            "failed_targets": json.loads(row["failed_targets"] or "[]"),
            "snapshot": row["snapshot"],
        }
        for row in rows
    ])


@app.get("/api/monitor/services")
def monitor_services():
    db = monitor_db()
    if db is None:
        return jsonify(error="monitor database not found; is the outage monitor running?"), 503
    try:
        minutes = max(5, min(int(request.args.get("minutes", 360)), 14 * 1440))
    except ValueError:
        return jsonify(error="minutes must be a number"), 400
    since = time.time() - minutes * 60
    bucket = max(60, minutes * 60 // 600)
    rows = db.execute(
        """
        SELECT name, kind, CAST(ts / ? AS INTEGER) * ? AS bucket_ts,
               COUNT(*) AS total, SUM(ok) AS ok, AVG(CASE WHEN ok = 1 THEN duration_ms END) AS duration_ms
        FROM service_samples WHERE ts >= ? GROUP BY name, bucket_ts ORDER BY bucket_ts
        """,
        (bucket, bucket, since),
    ).fetchall()
    series: dict[str, dict] = {}
    for row in rows:
        entry = series.setdefault(row["name"], {"kind": row["kind"], "ts": [], "ok_pct": [], "duration_ms": []})
        entry["ts"].append(row["bucket_ts"])
        entry["ok_pct"].append(round(100.0 * row["ok"] / row["total"], 1) if row["total"] else None)
        entry["duration_ms"].append(round(row["duration_ms"], 1) if row["duration_ms"] is not None else None)
    latest = db.execute(
        """
        SELECT s1.name, s1.kind, s1.ok, s1.duration_ms, s1.detail, s1.ts FROM service_samples s1
        JOIN (SELECT name, MAX(ts) AS mts FROM service_samples GROUP BY name) s2
          ON s1.name = s2.name AND s1.ts = s2.mts
        """
    ).fetchall()
    db.close()
    return jsonify({"bucket_seconds": bucket, "series": series, "latest": [dict(row) for row in latest]})


@app.get("/api/monitor/routes")
def monitor_routes():
    db = monitor_db()
    if db is None:
        return jsonify(error="monitor database not found; is the outage monitor running?"), 503
    state = db.execute("SELECT name, hops, updated FROM route_state ORDER BY name").fetchall()
    changes = db.execute(
        "SELECT ts, name, old_hops, new_hops FROM route_events ORDER BY ts DESC LIMIT 50"
    ).fetchall()
    db.close()
    return jsonify({"current": [dict(row) for row in state], "changes": [dict(row) for row in changes]})


@app.get("/api/monitor/throughput")
def monitor_throughput():
    """Packets/s and multicast/s per interface, derived from counter deltas."""
    db = monitor_db()
    if db is None:
        return jsonify(error="monitor database not found; is the outage monitor running?"), 503
    try:
        minutes = max(5, min(int(request.args.get("minutes", 360)), 14 * 1440))
    except ValueError:
        return jsonify(error="minutes must be a number"), 400
    since = time.time() - minutes * 60
    rows = db.execute(
        "SELECT ts, interface, rx_packets, tx_packets, rx_dropped, rx_errors, multicast "
        "FROM iface_samples WHERE ts >= ? ORDER BY interface, ts",
        (since,),
    ).fetchall()
    step = max(1, len(rows) // 1200)
    series: dict[str, dict] = {}
    previous: dict[str, sqlite3.Row] = {}
    index = 0
    for row in rows:
        iface = row["interface"]
        last = previous.get(iface)
        previous[iface] = row
        if last is None:
            continue
        dt = row["ts"] - last["ts"]
        if dt <= 0 or dt > 120:
            continue
        index += 1
        if index % step:
            continue
        entry = series.setdefault(iface, {"ts": [], "rx_pps": [], "tx_pps": [], "mcast_pps": [], "drop_pps": []})
        entry["ts"].append(row["ts"])
        entry["rx_pps"].append(round(max(0, row["rx_packets"] - last["rx_packets"]) / dt, 1))
        entry["tx_pps"].append(round(max(0, row["tx_packets"] - last["tx_packets"]) / dt, 1))
        entry["mcast_pps"].append(round(max(0, row["multicast"] - last["multicast"]) / dt, 1))
        entry["drop_pps"].append(round(max(0, (row["rx_dropped"] - last["rx_dropped"]) + (row["rx_errors"] - last["rx_errors"])) / dt, 2))
    db.close()
    return jsonify(series)


@app.get("/api/monitor/summary")
def monitor_summary():
    db = monitor_db()
    if db is None:
        return jsonify(error="monitor database not found; is the outage monitor running?"), 503
    day_ago = time.time() - 86400
    per_target = db.execute(
        """
        SELECT target, COUNT(*) AS total, SUM(ok) AS ok,
               AVG(CASE WHEN ok = 1 THEN rtt_ms END) AS rtt_avg, MAX(ts) AS last_ts,
               (SELECT ok FROM ping_samples p2 WHERE p2.target = p1.target ORDER BY ts DESC LIMIT 1) AS last_ok
        FROM ping_samples p1 WHERE ts >= ? GROUP BY target
        """,
        (day_ago,),
    ).fetchall()
    events_24h = db.execute("SELECT COUNT(*) AS n FROM events WHERE started >= ?", (day_ago,)).fetchone()["n"]
    open_event = db.execute("SELECT id, started, failed_targets FROM events WHERE ended IS NULL ORDER BY started DESC LIMIT 1").fetchone()
    db.close()
    return jsonify({
        "targets": [
            {
                "target": row["target"],
                "loss_pct_24h": round(100.0 * (row["total"] - row["ok"]) / row["total"], 2) if row["total"] else None,
                "rtt_avg_ms": round(row["rtt_avg"], 2) if row["rtt_avg"] is not None else None,
                "last_seen": row["last_ts"],
                "up": bool(row["last_ok"]),
            }
            for row in per_target
        ],
        "events_24h": events_24h,
        "open_event": dict(open_event) if open_event else None,
    })


if __name__ == "__main__":
    app.run(host=os.environ.get("PROBE_BIND", "127.0.0.1"), port=int(os.environ.get("PROBE_PORT", "8088")), debug=False)
