from __future__ import annotations

import csv
import os
import re
import shutil
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
MAX_OUTPUT = 120_000
NAME_RE = re.compile(r"^[A-Za-z0-9._:-]+$")

app = Flask(__name__)
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


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


if __name__ == "__main__":
    app.run(host=os.environ.get("PROBE_BIND", "127.0.0.1"), port=int(os.environ.get("PROBE_PORT", "8088")), debug=False)
