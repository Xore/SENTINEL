from __future__ import annotations

import csv
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

try:  # package import (waitress-serve dashboard.app:app)
    from dashboard import settings as settings_store
    from dashboard import history
    from dashboard import services
    from dashboard import monitor_config
    from dashboard import ids_adapter
    from dashboard import reconcile
    from dashboard import auth
    from dashboard import classify
    from dashboard import metrics as metrics_render
    from dashboard import config_validation
    from dashboard import dangerous
    from dashboard import trends
    from dashboard import alerts
except ImportError:  # run from inside the dashboard directory
    import settings as settings_store
    import history
    import services
    import monitor_config
    import ids_adapter
    import reconcile
    import auth
    import classify
    import metrics as metrics_render
    import config_validation
    import dangerous
    import trends
    import alerts

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # let us import the monitor/* helpers as a namespace pkg
    sys.path.insert(0, str(ROOT))
CAPTURE_DIR = Path(os.environ.get("PROBE_CAPTURE_DIR", ROOT / "captures")).resolve()
SNAPSHOT_DIR = Path(os.environ.get("PROBE_SNAPSHOT_DIR", ROOT / "snapshots")).resolve()
TARGET_FILE = Path(os.environ.get("PROBE_TARGET_FILE", ROOT / "config" / "targets.csv")).resolve()
MONITOR_DB = Path(os.environ.get("PROBE_MONITOR_DB", "/var/lib/network-probe/monitor.db"))
TRAFFIC_ALLOW_FILE = Path(os.environ.get("PROBE_TRAFFIC_ALLOW", "/etc/network-probe/traffic-gen-allow.csv"))
# Legacy root-owned monitor CSVs. The monitor now prefers the shared JSON config
# (monitor_config), but the Settings editor seeds itself from these on first load
# so an existing CSV install shows its current targets before the operator saves.
MONITOR_TARGETS_CSV = Path(os.environ.get("PROBE_MONITOR_TARGETS", "/etc/network-probe/monitor-targets.csv"))
MONITOR_SERVICES_CSV = Path(os.environ.get("PROBE_MONITOR_SERVICES", "/etc/network-probe/monitor-services.csv"))
MONITOR_PORTS_CSV = Path(os.environ.get("PROBE_MONITOR_PORTS", "/etc/network-probe/monitor-ports.csv"))
# Effective (read-only /etc file + dashboard-added) allow-list, written to the
# writable state dir so the generator subprocess can enforce against it.
EFFECTIVE_ALLOW_FILE = Path(settings_store.SETTINGS_FILE).parent / "traffic-allow-effective.csv"
MAX_OUTPUT = 120_000
MAX_DURATION = float(os.environ.get("PROBE_TRAFFIC_MAX_DURATION", "60"))
NAME_RE = re.compile(r"^[A-Za-z0-9._:-]+$")

app = Flask(__name__)
jobs: dict[str, dict] = {}
job_procs: dict[str, subprocess.Popen] = {}
jobs_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("network-probe")


def supervise(name: str, fn, *, restart: bool = True, min_backoff: float = 1.0,
              max_backoff: float = 30.0) -> threading.Thread:
    """Run ``fn`` on a daemon thread that can never take the process down.

    Any exception escaping ``fn`` is logged with a traceback. For a long-lived
    loop (``restart=True``) the thread is respawned with exponential backoff so
    a background worker crash self-heals instead of silently dying; a one-shot
    worker (``restart=False``) just logs and exits its thread. Either way the
    Flask/waitress process keeps serving."""
    def runner() -> None:
        backoff = min_backoff
        while True:
            started = time.monotonic()
            try:
                fn()
            except Exception:  # noqa: BLE001 - deliberate catch-all supervisor
                log.error("worker %r crashed:\n%s", name, traceback.format_exc())
            else:
                if not restart:
                    return
                log.warning("worker %r returned; restarting", name)
            if not restart:
                return
            # Reset backoff if the worker ran for a healthy while before dying.
            if time.monotonic() - started > max_backoff:
                backoff = min_backoff
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    thread = threading.Thread(target=runner, name=name, daemon=True)
    thread.start()
    return thread

# --- session auth (configurable username/password; sessions die on restart) ----
# Auth is ON by default (store bootstraps to admin/admin). Set PROBE_AUTH_DISABLED=1
# for localhost dev / the test suite. Legacy token Basic auth is gone; any file at
# PROBE_AUTH_TOKEN_FILE is ignored now.
AUTH_DISABLED = os.environ.get("PROBE_AUTH_DISABLED", "").strip() in {"1", "true", "yes"}
SESSION_COOKIE = "np_session"
SESSION_TTL = int(os.environ.get("PROBE_SESSION_TTL", str(12 * 3600)))
# In-memory only -> a dashboard restart invalidates every session by design.
SESSIONS: dict[str, dict] = {}
_sessions_lock = threading.Lock()
# Routes reachable without a session: the SPA shell (so the login UI can render),
# health, the login/logout/status endpoints, static assets, and collector ingest
# (which authenticates with its own per-collector key in _require_ingest).
_OPEN_PATHS = {"/", "/healthz", "/api/login", "/api/logout", "/api/auth/status", "/metrics"}


def _new_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    with _sessions_lock:
        SESSIONS[token] = {"user": username, "created": time.time(), "seen": time.time()}
    return token


def _session_user() -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    now = time.time()
    with _sessions_lock:
        sess = SESSIONS.get(token)
        if not sess:
            return None
        if now - sess["created"] > SESSION_TTL:
            SESSIONS.pop(token, None)
            return None
        sess["seen"] = now
        return sess["user"]


def _drop_session() -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with _sessions_lock:
            SESSIONS.pop(token, None)


@app.before_request
def require_session():
    path = request.path
    if AUTH_DISABLED or path in _OPEN_PATHS or path.startswith("/static/") \
            or path.startswith("/api/ingest/"):
        return None
    if _session_user() is not None:
        return None
    # Unauthenticated: APIs get a clean 401 (the SPA shows a login modal); any
    # non-API path falls through to the shell, which renders the same modal.
    if path.startswith("/api/"):
        return jsonify(error="authentication required", login_required=True), 401
    return None


def run(command: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        output = (result.stdout + result.stderr)[-MAX_OUTPUT:]
        return result.returncode, output
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def _iface_bus(item: Path) -> tuple[str, str]:
    """Return (kind, bus): kind in wired/wireless/loopback/virtual, bus in
    usb/pci/... Used to label and auto-surface hot-plugged USB adapters."""
    name = item.name
    if name == "lo":
        return "loopback", ""
    kind = "wireless" if (item / "wireless").exists() or (item / "phy80211").exists() else "wired"
    bus = ""
    try:
        # .../devices/.../usb.../net/<if> or .../pci.../net/<if>
        real = os.path.realpath(item / "device" / "subsystem")
        bus = os.path.basename(real)
    except OSError:
        pass
    if not bus and not (item / "device").exists():
        kind = "virtual" if kind == "wired" else kind
    return kind, bus


def interfaces() -> list[dict]:
    found = []
    net_root = Path("/sys/class/net")
    if not net_root.exists():
        return found
    overrides = settings_store.load().get("interface_overrides", {})
    for item in sorted(net_root.iterdir()):
        name = item.name
        _, address_text = run(["ip", "-brief", "address", "show", "dev", name])
        stats = {}
        for key in ("rx_bytes", "rx_packets", "rx_dropped", "rx_errors", "tx_bytes", "tx_packets", "tx_dropped", "tx_errors"):
            try:
                stats[key] = int((item / "statistics" / key).read_text().strip())
            except (OSError, ValueError):
                stats[key] = 0
        capture_safe = not bool(re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}/|\b[0-9a-fA-F:]+/", address_text))
        kind, bus = _iface_bus(item)
        override = overrides.get(name, {}).get("capture_allowed")
        found.append({
            "name": name,
            "state": (item / "operstate").read_text().strip(),
            "mac": (item / "address").read_text().strip(),
            "addresses": address_text.strip(),
            "kind": kind,
            "bus": bus,
            "usb": bus == "usb",
            "capture_safe": capture_safe,
            # Eligible for capture/health/monitor jobs. Safe by default (no IP);
            # an operator override can enable an addressed interface too.
            "capture_allowed": bool(override) if override is not None else capture_safe,
            "capture_override": override,
            **stats,
        })
    return found


VALID_PROTOCOLS = services.VALID_PROTOCOLS


def _valid_target(name: str, address: str, protocol: str, port) -> bool:
    return bool(NAME_RE.fullmatch(name) and NAME_RE.fullmatch(address)
                and protocol in VALID_PROTOCOLS and str(port).isdigit())


def targets() -> list[dict]:
    """Approved scope = the read-only operator CSV plus any endpoints added
    through the dashboard (persisted in the settings store). Deduplicated by
    (address, port)."""
    rows: list[dict] = []
    if TARGET_FILE.is_file():
        with TARGET_FILE.open(newline="", encoding="utf-8") as handle:
            for row in csv.reader(line for line in handle if not line.lstrip().startswith("#")):
                if len(row) != 4:
                    continue
                name, address, protocol, port = (value.strip() for value in row)
                if _valid_target(name, address, protocol, port):
                    rows.append({"name": name, "address": address, "protocol": protocol, "port": int(port), "source": "file"})
    for entry in settings_store.load().get("approved_scope", []):
        name, address = str(entry.get("name", "")), str(entry.get("address", ""))
        protocol, port = str(entry.get("protocol", "tcp")), entry.get("port")
        if _valid_target(name, address, protocol, port):
            rows.append({"name": name, "address": address, "protocol": protocol, "port": int(port), "source": "dashboard"})
    seen, unique = set(), []
    for row in rows:
        key = (row["address"], row["port"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def _run_tracked(job_id: str, command: list[str], timeout: int) -> tuple[int, str]:
    """Like run(), but registers the process so a job can be stopped mid-flight
    (used for long captures that keep running after the operator leaves the
    page). stdout+stderr are merged."""
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except (FileNotFoundError, OSError) as exc:
        return 127, str(exc)
    with jobs_lock:
        job_procs[job_id] = proc
    try:
        output, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        output, _ = proc.communicate()
        code = 124
    finally:
        with jobs_lock:
            job_procs.pop(job_id, None)
    return code, (output or "")[-MAX_OUTPUT:]


def launch_job(kind: str, command: list[str], timeout: int = 120,
               target: str = "", on_done=None) -> str:
    job_id = uuid.uuid4().hex[:12]
    with jobs_lock:
        jobs[job_id] = {"id": job_id, "kind": kind, "target": target,
                        "state": "running", "started": time.time(), "output": ""}
        snapshot = dict(jobs[job_id])
    history.upsert_job(snapshot)
    if target:
        history.record_scan(kind, target, job_id=job_id)
        if valid_ip(target):
            history.record_host(target, source=kind, kind=kind)

    def worker() -> None:
        try:
            code, output = _run_tracked(job_id, command, timeout)
        except Exception:  # the subprocess plumbing itself failed
            log.error("job %s (%s) crashed:\n%s", job_id, kind, traceback.format_exc())
            code, output = 1, "job crashed:\n" + traceback.format_exc()[-4000:]
        with jobs_lock:
            entry = jobs.get(job_id, {"id": job_id, "kind": kind, "target": target})
            stopping = entry.get("state") == "stopping"
            final = "complete" if code == 0 else ("stopped" if stopping else "failed")
            entry.update(state=final, code=code, output=output, ended=time.time())
            jobs[job_id] = entry
            snap = dict(entry)
        try:  # persistence must never leave the job hung or crash the worker
            history.upsert_job(snap)
            if target:
                history.update_scan_result(job_id, ok=(code == 0), summary=output[:1000])
        except Exception:
            log.error("job %s persistence failed:\n%s", job_id, traceback.format_exc())
        if on_done:
            try:
                on_done(snap, output)
            except Exception:  # never let post-processing break a job
                log.error("job %s on_done failed:\n%s", job_id, traceback.format_exc())

    # restart=False: a job runs once; supervise() is the last-resort net that
    # guarantees a crash is logged and can never reach the serving process.
    supervise(f"job:{kind}:{job_id}", worker, restart=False)
    return job_id


def _record_discovery(_snapshot: dict, output: str) -> None:
    """Fold discovered hosts into the persistent inventory."""
    try:
        data = json.loads(output)
    except ValueError:
        return
    for host in data.get("hosts", []):
        history.record_host(str(host.get("ip", "")), mac=str(host.get("mac", "")),
                            vendor=str(host.get("vendor", "")), name=str(host.get("name", "")),
                            source="discovery", kind="discovery")


def _record_snmp(ip: str):
    def cb(_snapshot: dict, output: str) -> None:
        try:
            data = json.loads(output)
        except ValueError:
            return
        sysinfo = data.get("system", {}) if isinstance(data, dict) else {}
        history.record_host(ip, name=str(sysinfo.get("sysName", "") or sysinfo.get("name", "")),
                            source="snmp", kind="snmp")
    return cb


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
        "tools": {name: (bool(_lldpctl_path()) if name == "lldpctl" else bool(shutil.which(name)))
                  for name in ("dumpcap", "tshark", "nmap", "tracepath", "iw", "snmpget", "lldpctl", "suricata", "ntopng")},
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
    return jsonify(job_id=launch_job("reachability", command, 20, target=target["address"])), 202


@app.post("/api/trace/<name>")
def trace_target(name: str):
    target = next((item for item in targets() if item["name"] == name), None)
    if not target:
        return jsonify(error="Target is not in the approved target file"), 404
    return jsonify(job_id=launch_job("route", ["tracepath", "-n", target["address"]], 45, target=target["address"])), 202


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
    if not selected or not selected["capture_allowed"]:
        return jsonify(error="Interface is not enabled for capture. Enable it in Settings → Interfaces (interfaces with an IP are off by default)."), 400
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
    if not selected or not selected["capture_allowed"]:
        return jsonify(error="Interface is not enabled for capture. Enable it in Settings → Interfaces."), 400
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


def _traffic_allow_entries() -> list[dict]:
    """Effective allow-list: read-only /etc file (source=file) merged with the
    dashboard-added entries in the settings store (source=dashboard)."""
    entries: list[dict] = []
    if TRAFFIC_ALLOW_FILE.is_file():
        for line in TRAFFIC_ALLOW_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [value.strip() for value in line.split(",")]
            if len(parts) == 3 and parts[1].isdigit() and parts[2] in {"tcp", "udp"}:
                entries.append({"host": parts[0], "port": int(parts[1]), "proto": parts[2], "source": "file"})
    for e in settings_store.load().get("traffic_allow", []):
        try:
            host, port, proto = str(e.get("host", "")), int(e.get("port")), str(e.get("proto", "tcp"))
        except (TypeError, ValueError):
            continue
        if NAME_RE.fullmatch(host) and proto in {"tcp", "udp"}:
            entries.append({"host": host, "port": port, "proto": proto, "source": "dashboard"})
    seen, unique = set(), []
    for e in entries:
        key = (e["host"], e["port"], e["proto"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def _write_effective_allow() -> Path:
    """Materialise the merged allow-list for the generator subprocess."""
    lines = ["# generated - read-only /etc list + dashboard-added entries"]
    for e in _traffic_allow_entries():
        lines.append(f"{e['host']},{e['port']},{e['proto']}")
    EFFECTIVE_ALLOW_FILE.parent.mkdir(parents=True, exist_ok=True)
    EFFECTIVE_ALLOW_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return EFFECTIVE_ALLOW_FILE


@app.get("/api/traffic/allow")
def traffic_allow():
    """List allow-listed traffic-generator destinations for the UI."""
    return jsonify(_traffic_allow_entries())


@app.post("/api/traffic/allow/add")
def traffic_allow_add():
    """Add a dashboard-managed traffic-generator destination (persistent)."""
    payload = request.get_json(silent=True) or {}
    host = str(payload.get("host", "")).strip()
    proto = str(payload.get("proto", "tcp")).strip()
    try:
        port = int(payload.get("port"))
    except (TypeError, ValueError):
        return jsonify(error="port is required and numeric"), 400
    if not NAME_RE.fullmatch(host) or proto not in {"tcp", "udp"} or not (0 < port < 65536):
        return jsonify(error="invalid host/port/proto (proto must be tcp or udp)"), 400
    current = settings_store.load()
    allow = current.setdefault("traffic_allow", [])
    if any(a.get("host") == host and int(a.get("port", -1)) == port and a.get("proto") == proto for a in allow):
        return jsonify(status="exists"), 200
    allow.append({"host": host, "port": port, "proto": proto})
    settings_store.save(current)
    return jsonify(status="added", count=len(allow)), 201


@app.post("/api/traffic/allow/remove")
def traffic_allow_remove():
    payload = request.get_json(silent=True) or {}
    host, port, proto = str(payload.get("host", "")), payload.get("port"), str(payload.get("proto", "tcp"))
    current = settings_store.load()
    allow = current.get("traffic_allow", [])
    kept = [a for a in allow if not (a.get("host") == host and str(a.get("port")) == str(port) and a.get("proto") == proto)]
    if len(kept) == len(allow):
        return jsonify(error="not a dashboard-added destination"), 404
    current["traffic_allow"] = kept
    settings_store.save(current)
    return jsonify(status="removed", count=len(kept))


@app.post("/api/traffic/generate")
def traffic_generate():
    payload = request.get_json(silent=True) or {}
    host = str(payload.get("host", ""))
    proto = str(payload.get("proto", "tcp"))
    try:
        port = int(payload.get("port"))
        count = int(payload.get("count", 1))
        rate = float(payload.get("rate", 1))
    except (TypeError, ValueError):
        return jsonify(error="host, port, count and rate are required and numeric"), 400
    if not NAME_RE.fullmatch(host) or proto not in {"tcp", "udp"}:
        return jsonify(error="invalid host or protocol"), 400
    # Sending payloads is an active action: enforce the effective allow-list
    # (dashboard-added entries included) up front, then hand the generator the
    # same list to re-check.
    if not any(e["host"] == host and e["port"] == port and e["proto"] == proto for e in _traffic_allow_entries()):
        return jsonify(error=f"{host}:{port}/{proto} is not in the traffic allow-list. Add it under Actions → Traffic first."), 403

    generator = ROOT / "monitor" / "traffic_gen.py"
    command = [os.environ.get("PROBE_PYTHON", sys.executable), str(generator),
               "--host", host, "--port", str(port), "--proto", proto,
               "--count", str(count), "--rate", str(rate),
               "--allow", str(_write_effective_allow())]
    mode = payload.get("mode")
    if mode == "hex":
        command += ["--hex", str(payload.get("data", ""))]
    elif mode == "size":
        command += ["--size", str(int(payload.get("size", 0)))]
        if payload.get("random"):
            command.append("--random")
    elif payload.get("data"):
        command += ["--data", str(payload.get("data"))]
    if payload.get("expect"):
        command += ["--expect", str(payload.get("expect"))]

    job_id = launch_job("traffic-gen", command, timeout=int(MAX_DURATION) + 30, target=host)
    return jsonify(job_id=job_id), 202


@app.get("/api/wifi")
def wifi():
    devices = []
    for iface in interfaces():
        code, info = run(["iw", "dev", iface["name"], "info"], 3)
        if code == 0:
            _, station = run(["iw", "dev", iface["name"], "link"], 3)
            devices.append({"interface": iface["name"], "info": info, "link": station})
    return jsonify(devices)


def _wireless_interfaces() -> list[str]:
    names = []
    for iface in interfaces():
        code, _ = run(["iw", "dev", iface["name"], "info"], 3)
        if code == 0:
            names.append(iface["name"])
    return names


@app.post("/api/wifi/survey")
def wifi_survey():
    payload = request.get_json(silent=True) or {}
    iface = str(payload.get("interface", ""))
    wireless = _wireless_interfaces()
    if iface not in wireless:
        iface = wireless[0] if wireless else ""
    if not iface:
        return jsonify(error="no wireless interface detected"), 400
    command = [os.environ.get("PROBE_PYTHON", sys.executable), str(ROOT / "monitor" / "wifi_survey.py"),
               "--iface", iface]
    if payload.get("rescan"):
        command.append("--rescan")
    return jsonify(job_id=launch_job("wifi-survey", command, 45)), 202


@app.get("/api/wifi/ap-monitor")
def wifi_ap_monitor():
    """Access-point watch: the persistent AP inventory (present + gone) and the
    appear/disappear event log the background poller maintains."""
    cfg = monitor_config.load().get("ap_monitor", {})
    return jsonify(
        config=cfg,
        last_update=history.ap_last_update(),
        access_points=history.get_ap_state(),
        events=history.get_ap_events(),
        wireless=_wireless_interfaces(),
    )


@app.post("/api/wifi/ap-monitor/scan")
def wifi_ap_monitor_scan():
    """Force one AP scan now (same unprivileged nmcli path as the poller)."""
    result = _poll_ap_once()
    if result is None:
        return jsonify(error="no wireless interface, or the scan failed (the radio may be blocked)"), 400
    result["last_update"] = history.ap_last_update()
    result["access_points"] = history.get_ap_state()
    result["events"] = history.get_ap_events()
    return jsonify(result)


# --- Wi-Fi coverage heatmap / walk-around site survey ----------------------

def _scan_readings(rescan: bool = True) -> tuple[list[dict], str]:
    """Run one Wi-Fi scan and return normalised per-BSSID readings for the
    heatmap: bssid, ssid, signal_dbm (real from iw, or approximated from an
    nmcli %), channel, band, freq. Second tuple item is an error/'' string."""
    wireless = _wireless_interfaces()
    if not wireless:
        return [], "no wireless interface detected"
    command = [os.environ.get("PROBE_PYTHON", sys.executable), str(ROOT / "monitor" / "wifi_survey.py"),
               "--iface", wireless[0]]
    if rescan:
        command.append("--rescan")
    code, output = run(command, 40)
    if code != 0 or not output.strip():
        return [], "scan failed (the radio may be blocked)"
    try:
        data = json.loads(output)
    except ValueError:
        return [], "scan produced no parseable output"
    readings = []
    for ap in data.get("aps") or []:
        dbm = ap.get("signal_dbm")
        if dbm is None and ap.get("signal_pct") is not None:
            dbm = ap["signal_pct"] / 2.0 - 100.0  # 100%->-50, 50%->-75 (approx)
        readings.append({
            "bssid": ap.get("bssid"), "ssid": ap.get("ssid"),
            "signal_dbm": round(dbm, 1) if dbm is not None else None,
            "signal_pct": ap.get("signal_pct"),
            "channel": ap.get("channel"), "band": ap.get("band"),
            "freq_mhz": ap.get("freq_mhz"), "in_use": ap.get("in_use", False),
        })
    return readings, ("" if readings else (data.get("note") or "no APs visible"))


@app.get("/api/wifi/spectrum")
def wifi_spectrum():
    """Channel-occupancy / interference model from one passive scan. Not a true
    RF spectrum (no SDR) - it spreads each AP's received power across the
    channels its carrier overlaps and recommends the cleanest channel per band.
    See monitor/wifi_survey.py:spectrum()."""
    readings, note = _scan_readings(rescan=request.args.get("rescan") == "1")
    from monitor.wifi_survey import spectrum as _spectrum  # pure, no side effects
    return jsonify(spectrum=_spectrum(readings), ap_count=len(readings),
                   note=note, ts=time.time())


@app.get("/api/wifi/heatmap/live")
def heatmap_live():
    """A fresh scan without storing it - drives the live signal meter you watch
    while walking. Uses the NM scan cache (no forced rescan) so it stays snappy."""
    readings, note = _scan_readings(rescan=request.args.get("rescan") == "1")
    return jsonify(readings=readings, note=note, ts=time.time())


@app.get("/api/wifi/heatmap/surveys")
def heatmap_surveys():
    return jsonify(surveys=history.list_heatmap_surveys())


@app.post("/api/wifi/heatmap/surveys")
def heatmap_create():
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip() or "Survey"
    survey = history.create_heatmap_survey(name[:80])
    if survey is None:
        return jsonify(error="could not create survey"), 500
    return jsonify(survey), 201


@app.get("/api/wifi/heatmap/surveys/<int:survey_id>")
def heatmap_get(survey_id: int):
    survey = history.get_heatmap_survey(survey_id)
    if survey is None:
        return jsonify(error="survey not found"), 404
    return jsonify(survey)


@app.delete("/api/wifi/heatmap/surveys/<int:survey_id>")
def heatmap_delete(survey_id: int):
    return jsonify(ok=history.delete_heatmap_survey(survey_id))


@app.post("/api/wifi/heatmap/surveys/<int:survey_id>/rename")
def heatmap_rename(survey_id: int):
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
    if not name:
        return jsonify(error="name required"), 400
    if not history.rename_heatmap_survey(survey_id, name[:80]):
        return jsonify(error="survey not found"), 404
    return jsonify(ok=True, name=name[:80])


@app.post("/api/wifi/heatmap/surveys/<int:survey_id>/sample")
def heatmap_sample(survey_id: int):
    """Capture the RF at the operator's current position (x,y as 0..1 fractions
    on the canvas). Scans, stores the readings against this survey, returns them."""
    payload = request.get_json(silent=True) or {}
    try:
        x, y = float(payload.get("x")), float(payload.get("y"))
    except (TypeError, ValueError):
        return jsonify(error="x and y (0..1) are required"), 400
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return jsonify(error="x and y must be between 0 and 1"), 400
    readings, note = _scan_readings(rescan=payload.get("rescan", True))
    if not readings:
        return jsonify(error=note or "scan returned no APs"), 400
    point = history.add_heatmap_point(survey_id, x, y, readings)
    if point is None:
        return jsonify(error="survey not found"), 404
    return jsonify(point=point, note=note), 201


@app.delete("/api/wifi/heatmap/surveys/<int:survey_id>/points/<int:point_id>")
def heatmap_point_delete(survey_id: int, point_id: int):
    return jsonify(ok=history.delete_heatmap_point(survey_id, point_id))


@app.put("/api/wifi/heatmap/surveys/<int:survey_id>/ap-positions")
def heatmap_ap_positions(survey_id: int):
    payload = request.get_json(silent=True) or {}
    positions = payload.get("positions")
    if not isinstance(positions, dict):
        return jsonify(error="positions must be an object keyed by BSSID"), 400
    clean = {}
    for bssid, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        try:
            px, py = float(pos.get("x")), float(pos.get("y"))
        except (TypeError, ValueError):
            continue
        clean[str(bssid).lower()] = {"x": max(0.0, min(1.0, px)), "y": max(0.0, min(1.0, py)),
                                     "ssid": str(pos.get("ssid", ""))[:64]}
    if not history.set_heatmap_ap_positions(survey_id, clean):
        return jsonify(error="survey not found"), 404
    return jsonify(ok=True, positions=clean)


@app.post("/api/discovery")
def discovery():
    payload = request.get_json(silent=True) or {}
    iface = str(payload.get("interface", ""))
    selected = next((item for item in interfaces() if item["name"] == iface), None)
    if not selected:
        return jsonify(error="select an existing interface"), 400
    command = [os.environ.get("PROBE_PYTHON", sys.executable), str(ROOT / "monitor" / "discovery.py"),
               "--iface", iface]
    subnet = str(payload.get("subnet", "")).strip()
    if subnet:
        if not re.fullmatch(r"[0-9./]+", subnet):
            return jsonify(error="invalid subnet"), 400
        command += ["--subnet", subnet]
    return jsonify(job_id=launch_job("lan-discovery", command, 180, on_done=_record_discovery)), 202


IDS_LOG = Path(os.environ.get("PROBE_IDS_LOG", "/var/log/suricata/eve.json"))


def _ids_summary(limit: int) -> tuple[int, dict]:
    """Run the read-only EVE reader and return (http_status, payload)."""
    command = [os.environ.get("PROBE_PYTHON", sys.executable), str(ROOT / "monitor" / "ids_reader.py"),
               "--log", str(IDS_LOG), "--limit", str(limit)]
    code, output = run(command, 20)
    try:
        return 200, json.loads(output)
    except ValueError:
        return 500, {"status": "error", "note": (output or "ids_reader produced no output")[:2000]}


@app.get("/api/ids/status")
def ids_status():
    """Engine health only (installed / active / log freshness) - cheap poll."""
    _, payload = _ids_summary(1)
    payload.pop("alerts", None)
    return jsonify(payload)


@app.get("/api/ids/alerts")
def ids_alerts():
    try:
        limit = max(1, min(int(request.args.get("limit", 100)), 500))
    except ValueError:
        return jsonify(error="limit must be a number"), 400
    # Server-side filters (also filterable in the UI without a re-fetch).
    sev = request.args.get("severity", "").strip().lower()
    text = request.args.get("q", "").strip().lower()
    src = request.args.get("src", "").strip()
    dst = request.args.get("dst", "").strip()
    # Fetch a wider window when filtering so matches are not truncated first.
    _, payload = _ids_summary(limit if not (sev or text or src or dst) else 500)
    alerts = payload.get("alerts")
    if isinstance(alerts, list) and (sev or text or src or dst):
        def keep(a: dict) -> bool:
            if sev and str(a.get("severity_label", "")).lower() != sev:
                return False
            if src and src not in str(a.get("src", "")):
                return False
            if dst and dst not in str(a.get("dst", "")):
                return False
            if text and text not in (str(a.get("signature", "")) + " " + str(a.get("category", ""))).lower():
                return False
            return True
        payload["alerts"] = [a for a in alerts if keep(a)][:limit]
        payload["filtered"] = True
    return jsonify(payload)


def _ids_adapters() -> list[dict]:
    """Real NICs on this probe that Suricata could capture on (loopback aside),
    each with live up/down and wired/wireless for the picker."""
    out = []
    for i in interfaces():
        name = i["name"]
        if name == "lo":
            continue
        out.append({
            "name": name,
            "up": str(i.get("state", "")).lower() == "up",
            "wired": name.startswith(("en", "eth")),
        })
    return out


@app.get("/api/ids/adapter")
def get_ids_adapter():
    """Desired capture-adapter config (dashboard-editable) plus the live state
    the root daemon publishes, so the UI can show configured-vs-active."""
    cfg = ids_adapter.load()
    cfg["config_file"] = str(ids_adapter.CONFIG_FILE)
    cfg["adapters"] = _ids_adapters()
    # Live state from the read-only reader (active/resolved NICs, note).
    _, summary = _ids_summary(1)
    engine = summary.get("engine", {}) if isinstance(summary, dict) else {}
    cfg["live"] = engine.get("adapter", {})
    cfg["service_active"] = bool(engine.get("service_active"))
    return jsonify(cfg)


@app.put("/api/ids/adapter")
def put_ids_adapter():
    """Write desired capture-adapter state. The root daemon re-reads this within
    one recheck cycle, rewrites suricata.yaml, validates it, and rolls back on
    failure - the web process never touches Suricata directly."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="expected a JSON object"), 400
    valid_names = {a["name"] for a in _ids_adapters()}
    cfg, errors = ids_adapter.validate(payload, valid_names)
    if errors:
        return jsonify(error="validation failed", details=errors), 400
    try:
        ids_adapter.save(cfg)
    except OSError as exc:
        return jsonify(error=f"could not save IDS adapter config: {exc}"), 500
    cfg["config_file"] = str(ids_adapter.CONFIG_FILE)
    cfg["adapters"] = _ids_adapters()
    return jsonify(cfg)


def valid_ip(value: str) -> str:
    """Return a normalised IP string, or '' if not a plain IPv4/IPv6 address."""
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return ""


# --- network settings (via the privileged reconciler) --------------------------
# The IPv4 config of a NIC is a privileged, lock-yourself-out-able change, so the
# web process never runs nmcli. It writes desired state through dashboard.reconcile
# for the root reconciler (scripts/reconciler.py + scripts/reconcile.d/network) to
# enact, ALWAYS with confirm=True so an unconfirmed change auto-rolls-back.
NETWORK_RESOURCE = "network"


def _network_ifaces() -> list[dict]:
    """NICs the operator may reconfigure, with their current addresses so the UI
    can pre-fill (loopback aside)."""
    out = []
    for i in interfaces():
        if i["name"] == "lo":
            continue
        out.append({
            "name": i["name"],
            "up": str(i.get("state", "")).lower() == "up",
            "wired": i["name"].startswith(("en", "eth")),
            "addresses": i.get("addresses", ""),
        })
    return out


def _validate_network(payload: dict, valid_names: set[str]) -> tuple[dict, list[str]]:
    """Turn a request body into a clean nmcli payload. Rejects addresses that are
    not real IPs and interfaces that are not on this host."""
    errors: list[str] = []
    iface = str(payload.get("interface", "")).strip()
    if iface not in valid_names:
        errors.append(f"unknown interface '{iface}'")
    method = str(payload.get("method", "auto")).strip().lower()
    if method not in {"auto", "manual"}:
        errors.append("method must be 'auto' or 'manual'")
        method = "auto"

    clean: dict = {"interface": iface, "method": method}
    if method == "manual":
        addr = valid_ip(str(payload.get("address", "")))
        if not addr:
            errors.append("manual mode needs a valid IPv4/IPv6 address")
        try:
            prefix = int(payload.get("prefix", 24))
            if not 1 <= prefix <= 128:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("prefix must be 1..128")
            prefix = 24
        clean["address"] = addr
        clean["prefix"] = prefix
        gw = str(payload.get("gateway", "")).strip()
        if gw:
            gwn = valid_ip(gw)
            if not gwn:
                errors.append("gateway is not a valid IP")
            else:
                clean["gateway"] = gwn

    dns = payload.get("dns", [])
    if isinstance(dns, str):
        dns = [x for x in re.split(r"[,\s]+", dns) if x]
    clean_dns = []
    for d in dns if isinstance(dns, list) else []:
        dn = valid_ip(str(d))
        if dn:
            clean_dns.append(dn)
        elif str(d).strip():
            errors.append(f"DNS '{d}' is not a valid IP")
    if clean_dns:
        clean["dns"] = clean_dns
    return clean, errors


@app.get("/api/network")
def get_network():
    """Current desired network state + the reconciler's result + the NIC list.
    `awaiting_confirm`/`seconds_left` drive the 'Keep this change' countdown."""
    snap = reconcile.snapshot(NETWORK_RESOURCE)
    snap["interfaces"] = _network_ifaces()
    snap["desired_dir"] = str(reconcile.DESIRED_DIR)
    return jsonify(snap)


@app.post("/api/network")
def post_network():
    """Request an IPv4 change. Always armed with auto-rollback: if the operator
    does not confirm before the grace deadline, the reconciler reverts it."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="expected a JSON object"), 400
    clean, errors = _validate_network(payload, {i["name"] for i in _network_ifaces()})
    if errors:
        return jsonify(error="validation failed", details=errors), 400
    try:
        grace = int(payload.get("grace_seconds", reconcile.DEFAULT_GRACE))
    except (TypeError, ValueError):
        grace = reconcile.DEFAULT_GRACE
    try:
        reconcile.submit(NETWORK_RESOURCE, clean, confirm=True, grace_seconds=grace)
    except (OSError, ValueError) as exc:
        return jsonify(error=f"could not queue network change: {exc}"), 500
    return jsonify(reconcile.snapshot(NETWORK_RESOURCE))


@app.post("/api/network/confirm")
def confirm_network():
    """Keep the currently-applied change (cancel the pending auto-rollback)."""
    try:
        reconcile.confirm(NETWORK_RESOURCE)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except OSError as exc:
        return jsonify(error=f"could not confirm: {exc}"), 500
    return jsonify(reconcile.snapshot(NETWORK_RESOURCE))


# --- login / logout / account --------------------------------------------------
@app.get("/api/auth/status")
def auth_status():
    """Whether auth is on, and (if logged in) who as + whether a password change
    is still pending. Drives the SPA's login modal."""
    if AUTH_DISABLED:
        return jsonify(auth_enabled=False, authenticated=True, username=None,
                       must_change=False)
    user = _session_user()
    body = {"auth_enabled": True, "authenticated": user is not None, "username": user}
    if user is not None:
        body["must_change"] = auth.status().get("must_change", False)
    return jsonify(body)


@app.post("/api/login")
def login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if AUTH_DISABLED:
        return jsonify(ok=True, auth_enabled=False)
    if not auth.verify(username, password):
        return jsonify(error="invalid username or password"), 401
    token = _new_session(username)
    resp = jsonify(ok=True, username=username, must_change=auth.status().get("must_change", False))
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax",
                    max_age=SESSION_TTL, path="/")
    return resp


@app.post("/api/logout")
def logout():
    _drop_session()
    resp = jsonify(ok=True)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.post("/api/auth/password")
def change_password():
    """Change username and/or password. Requires the current password. Clears the
    must_change flag and invalidates all OTHER sessions (keeps the caller's)."""
    if AUTH_DISABLED:
        return jsonify(error="auth is disabled on this instance"), 400
    if _session_user() is None:
        return jsonify(error="authentication required"), 401
    payload = request.get_json(silent=True) or {}
    current = str(payload.get("current_password", ""))
    new_password = str(payload.get("new_password", ""))
    new_username = str(payload.get("username", "")).strip() or auth.status()["username"]
    if not auth.verify(auth.status()["username"], current):
        return jsonify(error="current password is incorrect"), 403
    try:
        auth.set_credentials(new_username, new_password, must_change=False)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except OSError as exc:
        return jsonify(error=f"could not save credentials: {exc}"), 500
    # Re-issue a session for the caller, drop every other one (password changed).
    keep = _new_session(new_username)
    with _sessions_lock:
        for tok in [t for t in SESSIONS if t != keep]:
            SESSIONS.pop(tok, None)
    resp = jsonify(ok=True, username=new_username)
    resp.set_cookie(SESSION_COOKIE, keep, httponly=True, samesite="Lax",
                    max_age=SESSION_TTL, path="/")
    return resp


@app.get("/api/settings")
def get_settings():
    """Redacted settings for the UI (secrets returned only as *_set booleans)."""
    return jsonify(settings_store.redacted())


@app.put("/api/settings")
def put_settings():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="expected a JSON object"), 400
    # Only known top-level sections are accepted.
    allowed = {"snmp", "interface_overrides", "approved_scope", "metrics",
               "dangerous_actions"}
    update = {k: v for k, v in payload.items() if k in allowed}
    if not update:
        return jsonify(error="no editable settings in request"), 400
    # Validate BEFORE persisting so a bad value is rejected with a clear reason
    # instead of being silently stored and breaking a loop later (#49).
    errors = config_validation.validate_settings(update)
    if errors:
        return jsonify(error="invalid settings", details=errors), 400
    try:
        result = settings_store.apply_update(update)
    except OSError as exc:
        return jsonify(error=f"could not save settings: {exc}"), 500
    history.record_audit("settings.update", user=_session_user() or "-",
                         target=",".join(sorted(update)),
                         detail=config_validation.summarize_settings(update))
    return jsonify(result)


@app.get("/api/audit")
def get_audit():
    """Recent config-change audit entries (newest first). Read-only trail of who
    changed what and when; secret values are never recorded (#49)."""
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        return jsonify(error="limit must be a number"), 400
    return jsonify({"entries": history.list_audit(limit)})


@app.get("/api/dangerous")
def get_dangerous():
    """Roadmap P5 register of excluded-by-default capabilities and the current
    gate state, for the Dangerous Actions tab. Reading is always allowed; the
    items stay locked until the master switch and per-item acknowledgement are
    both on - and even then the destructive technique is not executed (#55)."""
    cfg = settings_store.load()
    return jsonify({
        "enabled": dangerous.is_enabled(cfg),
        "actions": dangerous.list_actions(cfg),
    })


@app.post("/api/dangerous/<action_id>/run")
def run_dangerous(action_id: str):
    """Attempt a dangerous action. Always audited; never executes a destructive
    technique - returns the gate decision (this build refuses by design). The
    endpoint exists so the refusal is explicit and logged rather than silent."""
    cfg = settings_store.load()
    result = dangerous.run_action(cfg, action_id)
    history.record_audit(
        "dangerous.run", user=_session_user() or "-", target=action_id,
        detail=f"allowed={result['allowed']} executed={result['executed']} "
               f"reason={result['reason']}")
    status = 200 if result["allowed"] else 403
    return jsonify(result), status


def _csv_dicts(path: Path, columns: list[str]) -> list[dict]:
    """Best-effort read of a legacy monitor CSV into name-keyed dicts. Used only
    to seed the Settings editor before the operator saves the JSON config."""
    rows: list[dict] = []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            for raw in csv.reader(handle):
                if not raw or raw[0].lstrip().startswith("#"):
                    continue
                values = (raw + [""] * len(columns))[:len(columns)]
                rows.append({col: values[i].strip() for i, col in enumerate(columns)})
    except OSError:
        pass
    return rows


def _monitor_config_effective() -> dict:
    """Current monitor config for the editor. Once the JSON exists it is
    authoritative; before that we surface whatever the monitor is still reading
    from the /etc CSVs so the editor is pre-populated, not blank."""
    cfg = monitor_config.load()
    if monitor_config.CONFIG_FILE.is_file():
        cfg["source"] = "json"
        return cfg
    cfg["source"] = "csv"
    targets = _csv_dicts(MONITOR_TARGETS_CSV, ["name", "address", "interface", "group"])
    services = _csv_dicts(MONITOR_SERVICES_CSV, ["name", "kind", "target"])
    ports = _csv_dicts(MONITOR_PORTS_CSV, ["name", "host", "port", "proto", "send", "expect"])
    cfg["targets"] = monitor_config.clean_targets(targets)[0]
    cfg["services"] = monitor_config.clean_services(services)[0]
    cfg["ports"] = monitor_config.clean_ports(ports)[0]
    return cfg


@app.get("/api/monitor/config")
def get_monitor_config():
    """What the outage monitor probes (targets/services/ports/AP-watch)."""
    cfg = _monitor_config_effective()
    cfg["groups"] = sorted(monitor_config.GROUPS)
    cfg["service_kinds"] = sorted(monitor_config.SERVICE_KINDS)
    # Real adapters on this probe, so each target can pick which one to source
    # its probe from (empty = let the OS route it). Loopback is not useful here.
    cfg["adapters"] = [
        {"name": i["name"], "state": i.get("state")}
        for i in interfaces() if i["name"] != "lo"
    ]
    cfg["config_file"] = str(monitor_config.CONFIG_FILE)
    return jsonify(cfg)


@app.put("/api/monitor/config")
def put_monitor_config():
    """Replace the monitor's probe list. Validated, then written to the shared
    JSON the monitor hot-reloads - no privileged restart needed."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="expected a JSON object"), 400
    current = monitor_config.load()
    errors: list[str] = []
    out = {"targets": current["targets"], "services": current["services"],
           "ports": current["ports"], "ap_monitor": current["ap_monitor"]}
    if "targets" in payload:
        out["targets"], errs = monitor_config.clean_targets(payload["targets"])
        errors += errs
    if "services" in payload:
        out["services"], errs = monitor_config.clean_services(payload["services"])
        errors += errs
    if "ports" in payload:
        out["ports"], errs = monitor_config.clean_ports(payload["ports"])
        errors += errs
    if isinstance(payload.get("ap_monitor"), dict):
        ap = payload["ap_monitor"]
        out["ap_monitor"] = {
            "enabled": bool(ap.get("enabled", out["ap_monitor"]["enabled"])),
            "interval": monitor_config._clamp_int(ap.get("interval", out["ap_monitor"]["interval"]), 20, 3600, 60),
        }
    if errors:
        return jsonify(error="validation failed", details=errors), 400
    try:
        monitor_config.save(out)
    except OSError as exc:
        return jsonify(error=f"could not save monitor config: {exc}"), 500
    saved = monitor_config.load()  # re-clamps ap_monitor.interval
    saved["source"] = "json"
    return jsonify(saved)


@app.post("/api/interfaces/<name>/capture")
def set_capture(name: str):
    """Enable/disable an interface for capture/monitor jobs (persistent)."""
    if not any(item["name"] == name for item in interfaces()):
        return jsonify(error="unknown interface"), 404
    payload = request.get_json(silent=True) or {}
    allowed = bool(payload.get("capture_allowed"))
    current = settings_store.load()
    overrides = current.setdefault("interface_overrides", {})
    overrides.setdefault(name, {})["capture_allowed"] = allowed
    settings_store.save(current)
    return jsonify(name=name, capture_allowed=allowed)


@app.post("/api/scope/add")
def scope_add():
    """Promote a host (e.g. from Discovery) into the approved-scope list."""
    payload = request.get_json(silent=True) or {}
    address = valid_ip(str(payload.get("address", ""))) or str(payload.get("address", "")).strip()
    protocol = str(payload.get("protocol", "tcp"))
    name = str(payload.get("name", "")).strip() or f"host-{address}"
    name = re.sub(r"[^A-Za-z0-9._:-]", "-", name)[:48]
    try:
        port = int(payload.get("port"))
    except (TypeError, ValueError):
        return jsonify(error="port is required and numeric"), 400
    if not _valid_target(name, address, protocol, port) or not (0 < port < 65536):
        return jsonify(error="invalid endpoint (name/address/protocol/port)"), 400
    current = settings_store.load()
    scope = current.setdefault("approved_scope", [])
    if any(e.get("address") == address and int(e.get("port", -1)) == port for e in scope):
        return jsonify(status="exists", name=name), 200
    scope.append({"name": name, "address": address, "protocol": protocol, "port": port})
    settings_store.save(current)
    return jsonify(status="added", name=name, count=len(scope)), 201


@app.post("/api/scope/remove")
def scope_remove():
    """Remove a dashboard-added endpoint (file-provided ones are read-only)."""
    payload = request.get_json(silent=True) or {}
    address, port = str(payload.get("address", "")).strip(), payload.get("port")
    current = settings_store.load()
    scope = current.get("approved_scope", [])
    kept = [e for e in scope if not (e.get("address") == address and str(e.get("port")) == str(port))]
    if len(kept) == len(scope):
        return jsonify(error="not a dashboard-added endpoint"), 404
    current["approved_scope"] = kept
    settings_store.save(current)
    return jsonify(status="removed", count=len(kept))


@app.post("/api/trace-ip")
def trace_ip():
    """Traceroute (tracepath) to any valid IP - used by click-to-trace on
    Discovery/IDS/monitor events. Read-only and bounded."""
    payload = request.get_json(silent=True) or {}
    ip = valid_ip(str(payload.get("ip", "")))
    if not ip:
        return jsonify(error="a valid IP address is required"), 400
    return jsonify(job_id=launch_job("trace-ip", ["tracepath", "-n", ip], 45)), 202


@app.post("/api/snmp")
def snmp_probe():
    """Single-target, read-only SNMP identity read using stored credentials.
    Deliberately not a sweep: one host, a small OID set, short timeout."""
    payload = request.get_json(silent=True) or {}
    ip = valid_ip(str(payload.get("ip", "")))
    if not ip:
        return jsonify(error="a valid IP address is required"), 400
    command = [os.environ.get("PROBE_PYTHON", sys.executable), str(ROOT / "monitor" / "snmp_probe.py"),
               "--host", ip, "--settings", str(settings_store.SETTINGS_FILE)]
    if payload.get("walk_interfaces"):
        command.append("--interfaces")
    return jsonify(job_id=launch_job("snmp-probe", command, 40, target=ip, on_done=_record_snmp(ip))), 202


def _lldpctl_path() -> str | None:
    """Resolve lldpctl by absolute path.

    lldpctl lives in /usr/sbin, which the service's default PATH may omit, and
    the binary is group-execute-only (adm), so shutil.which()/PATH lookup can
    miss it even when installed. Probe known locations directly.
    """
    for candidate in ("/usr/sbin/lldpctl", "/usr/bin/lldpctl", "/sbin/lldpctl"):
        if os.path.exists(candidate):
            return candidate
    return shutil.which("lldpctl")


@app.get("/api/lldp")
def lldp_neighbors():
    """Discovered LLDP/CDP neighbours from a locally running lldpd."""
    lldpctl = _lldpctl_path()
    if not lldpctl:
        return jsonify(status="unavailable", neighbors=[],
                       note="lldpd is not installed. Run scripts/install-neighbors.sh --apply on the probe.")
    code, output = run([lldpctl, "-f", "json"], 8)
    if code != 0 or not output.strip():
        return jsonify(status="no_data", neighbors=[],
                       note="lldpd is installed but returned no neighbours yet (frames are sent ~every 30s).")
    try:
        data = json.loads(output)
    except ValueError:
        return jsonify(status="error", neighbors=[], note="could not parse lldpctl output")
    neighbors = _parse_lldp(data)
    history.record_lldp(neighbors)
    for n in neighbors:
        if n.get("mgmt_ip") and valid_ip(n["mgmt_ip"]):
            history.record_host(n["mgmt_ip"], name=n.get("system", ""), source="lldp", kind="lldp")
    return jsonify(status="ok", neighbors=neighbors, changes=history.get_lldp_changes(20))


def _parse_lldp(data: dict) -> list[dict]:
    """Flatten lldpctl JSON into rows: local port, remote system, port, mgmt IP."""
    rows = []
    interfaces_node = (data.get("lldp") or {}).get("interface") or data.get("interface") or []
    if isinstance(interfaces_node, dict):
        interfaces_node = [{"name": k, **v} if isinstance(v, dict) else {"name": k} for k, v in interfaces_node.items()]
    for iface in interfaces_node:
        local = iface.get("name", "")
        chassis = iface.get("chassis", {})
        # chassis may be {"SYSNAME": {...}} or a flat dict.
        sysname, mgmt = "", ""
        if isinstance(chassis, dict) and chassis:
            first = next(iter(chassis.values())) if not chassis.get("id") else chassis
            sysname = next(iter(chassis)) if not chassis.get("id") else (first.get("name", "") if isinstance(first, dict) else "")
            node = first if isinstance(first, dict) else chassis
            mgmt = _lldp_first(node.get("mgmt-ip"))
            descr = _lldp_first(node.get("descr"))
        else:
            descr = ""
        port = iface.get("port", {})
        port_id = _lldp_first(port.get("id")) if isinstance(port, dict) else ""
        port_descr = _lldp_first(port.get("descr")) if isinstance(port, dict) else ""
        vlan = iface.get("vlan", {})
        vlan_id = _lldp_first(vlan.get("vlan-id") if isinstance(vlan, dict) else vlan) if vlan else ""
        rows.append({
            "local_port": local, "system": sysname, "mgmt_ip": mgmt,
            "port_id": port_id, "port_descr": port_descr, "descr": descr, "vlan": vlan_id,
        })
    return rows


def _lldp_first(node):
    """lldpctl JSON wraps scalars as {'value': x} or lists; pull a plain string."""
    if node is None:
        return ""
    if isinstance(node, dict):
        return str(node.get("value", node.get("name", "")))
    if isinstance(node, list):
        return ", ".join(_lldp_first(n) for n in node)
    return str(node)


# --- Custom-target actions (operator-entered, not from the allow-list) -----

def _custom_services() -> list[dict]:
    """Operator-defined named services from the settings store, validated."""
    out: list[dict] = []
    for entry in settings_store.load().get("custom_services", []):
        name = str(entry.get("name", "")).strip()
        proto = str(entry.get("proto", "tcp")).strip()
        try:
            port = int(entry.get("port"))
        except (TypeError, ValueError):
            continue
        if NAME_RE.fullmatch(name) and proto in {"tcp", "udp"} and 0 < port < 65536:
            out.append({"name": name, "port": port, "proto": proto, "category": "custom"})
    return out


@app.get("/api/services/catalog")
def services_catalog():
    """Known IT/OT services plus operator-defined custom ones so the UI can
    offer 'pick a service' dropdowns."""
    custom = _custom_services()
    protocols = sorted(services.VALID_PROTOCOLS | {s["name"] for s in custom})
    return jsonify({"services": services.KNOWN_SERVICES + custom,
                    "custom": custom, "protocols": protocols})


@app.post("/api/services/custom/add")
def services_custom_add():
    """Save a named custom service (name + port + proto) for the catalogue."""
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    proto = str(payload.get("proto", "tcp")).strip()
    try:
        port = int(payload.get("port"))
    except (TypeError, ValueError):
        return jsonify(error="a numeric port is required"), 400
    if not NAME_RE.fullmatch(name):
        return jsonify(error="name must be letters/digits/._:- (no spaces)"), 400
    if proto not in {"tcp", "udp"} or not (0 < port < 65536):
        return jsonify(error="proto must be tcp/udp and port 1-65535"), 400
    if name in services.BY_NAME:
        return jsonify(error=f"'{name}' is already a built-in service name"), 400
    current = settings_store.load()
    custom = current.setdefault("custom_services", [])
    if any(str(c.get("name", "")).lower() == name.lower() for c in custom):
        return jsonify(status="exists", name=name), 200
    custom.append({"name": name, "port": port, "proto": proto})
    settings_store.save(current)
    return jsonify(status="added", name=name, count=len(custom)), 201


@app.post("/api/services/custom/remove")
def services_custom_remove():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    current = settings_store.load()
    custom = current.get("custom_services", [])
    kept = [c for c in custom if str(c.get("name", "")).lower() != name.lower()]
    if len(kept) == len(custom):
        return jsonify(error="not a custom service"), 404
    current["custom_services"] = kept
    settings_store.save(current)
    return jsonify(status="removed", count=len(kept))


@app.post("/api/actions/reachability")
def actions_reachability():
    """Bounded TCP-connect check to an operator-entered IP and port. Connect
    only (nmap -sT): no version detection, scripts, or UDP raw scan."""
    payload = request.get_json(silent=True) or {}
    ip = valid_ip(str(payload.get("ip", "")))
    if not ip:
        return jsonify(error="a valid IP address is required"), 400
    try:
        port = int(payload.get("port"))
    except (TypeError, ValueError):
        return jsonify(error="a numeric port is required"), 400
    if not 0 < port < 65536:
        return jsonify(error="port out of range"), 400
    command = ["nmap", "-n", "-Pn", "-sT", "-T2", "--max-retries", "1",
               "--host-timeout", "10s", "-p", str(port), "--", ip]
    return jsonify(job_id=launch_job("reachability", command, 20, target=ip)), 202


@app.post("/api/actions/service-health")
def actions_service_health():
    """Read-only DNS/clock/TCP/TLS/HTTP profile for one host+port. Safe active:
    one resolver query, a local clock read, one TCP connect, and a TLS handshake
    plus a single HTTP GET only when the port is a standard web/TLS port."""
    payload = request.get_json(silent=True) or {}
    host = str(payload.get("host", "")).strip()
    if not (host and NAME_RE.fullmatch(host)):
        return jsonify(error="a valid host (IP or name) is required"), 400
    try:
        port = int(payload.get("port", 443))
    except (TypeError, ValueError):
        return jsonify(error="a numeric port is required"), 400
    if not 0 < port < 65536:
        return jsonify(error="port out of range"), 400
    name = str(payload.get("name", "")).strip()
    if name and not NAME_RE.fullmatch(name):
        return jsonify(error="invalid name"), 400
    command = [os.environ.get("PROBE_PYTHON", sys.executable),
               str(ROOT / "monitor" / "service_check.py"),
               "--host", host, "--port", str(port)]
    if name:
        command += ["--name", name]
    target = valid_ip(host) or host
    return jsonify(job_id=launch_job("service-health", command, 45, target=target)), 202


@app.post("/api/actions/path-health")
def actions_path_health():
    """Read-only route/MTU/latency/loss profile for one host. Safe active: a
    tracepath (standard probe traffic), an unprivileged ICMP echo run, and - only
    when a port is given - one bounded TCP connect. No OT payloads, no sweep."""
    payload = request.get_json(silent=True) or {}
    host = str(payload.get("host", "")).strip()
    if not (host and NAME_RE.fullmatch(host)):
        return jsonify(error="a valid host (IP or name) is required"), 400
    port = 0
    if payload.get("port") not in (None, "", 0, "0"):
        try:
            port = int(payload.get("port"))
        except (TypeError, ValueError):
            return jsonify(error="port must be numeric"), 400
        if not 0 < port < 65536:
            return jsonify(error="port out of range"), 400
    command = [os.environ.get("PROBE_PYTHON", sys.executable),
               str(ROOT / "monitor" / "path_check.py"), "--host", host]
    if port:
        command += ["--port", str(port)]
    target = valid_ip(host) or host
    return jsonify(job_id=launch_job("path-health", command, 60, target=target)), 202


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Linear-interpolated percentile of an already-sorted list; None if empty."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return round(sorted_values[0], 2)
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return round(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac, 2)


@app.get("/api/health/baseline")
def health_baseline():
    """Latency/loss baseline for one monitored target: 7-day median/p95 vs the
    last hour, read-only from the monitor DB's ping_samples. No probing - it only
    summarises what the outage monitor already recorded."""
    target = str(request.args.get("target", "")).strip()
    if not target:
        return jsonify(error="a target is required"), 400
    db = monitor_db()
    if db is None:
        return jsonify(error="monitor database not found; is the outage monitor running?"), 503
    try:
        rows = db.execute(
            "SELECT ts, ok, rtt_ms FROM ping_samples "
            "WHERE target = ? AND ts >= ? ORDER BY ts",
            (target, time.time() - 7 * 86400)).fetchall()
    except sqlite3.Error as exc:
        return jsonify(error=f"baseline unavailable: {exc}"), 503
    finally:
        db.close()
    if not rows:
        return jsonify(target=target, samples=0,
                       note="no ping history for this target yet"), 200

    def summarise(sample):
        oks = [r for r in sample if r["ok"]]
        rtts = sorted(r["rtt_ms"] for r in oks if r["rtt_ms"] is not None)
        loss = round(100.0 * (len(sample) - len(oks)) / len(sample), 1) if sample else None
        return {
            "samples": len(sample),
            "loss_pct": loss,
            "rtt_median_ms": _percentile(rtts, 50),
            "rtt_p95_ms": _percentile(rtts, 95),
        }

    now = time.time()
    week = summarise(rows)
    hour = summarise([r for r in rows if r["ts"] >= now - 3600])
    verdict, notes = "ok", []
    b_rtt, c_rtt = week["rtt_p95_ms"], hour["rtt_median_ms"]
    if b_rtt and c_rtt and c_rtt > max(b_rtt * 1.5, b_rtt + 20):
        verdict = "elevated"
        notes.append(f"latency {c_rtt:.0f} ms now vs {b_rtt:.0f} ms 7-day p95")
    if hour["samples"] and hour["loss_pct"] and hour["loss_pct"] > max(week["loss_pct"] or 0, 2) + 1:
        verdict = "elevated"
        notes.append(f"loss {hour['loss_pct']}% now vs {week['loss_pct']}% 7-day baseline")
    return jsonify(target=target, window_days=7, baseline=week, current_hour=hour,
                   verdict=verdict, notes=notes), 200


# --- Persistent inventory and scan history ---------------------------------

@app.get("/api/hosts")
def hosts_list():
    """Everything the probe has observed or scanned, one row per address."""
    return jsonify(history.get_hosts(500))


@app.get("/api/hosts/<path:address>")
def host_detail(address: str):
    item = history.get_host(address.strip())
    if item is None:
        return jsonify(error="host not seen yet"), 404
    return jsonify(item)


@app.get("/api/scans")
def scans_list():
    target = str(request.args.get("target", "")).strip()
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 1000))
    except ValueError:
        return jsonify(error="limit must be a number"), 400
    return jsonify(history.get_scans(limit, target))


def _reverse_dns(ip: str) -> str:
    """Best-effort PTR lookup, bounded so a slow resolver can't hang a request."""
    old = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(2.0)
        return socket.gethostbyaddr(ip)[0]
    except (OSError, socket.herror, socket.gaierror):
        return ""
    finally:
        socket.setdefaulttimeout(old)


def _ip_monitor(ip: str) -> dict | None:
    """Outage-monitor ping stats for this IP over 24h, if it's a monitored target."""
    db = monitor_db()
    if db is None:
        return None
    try:
        day_ago = time.time() - 86400
        row = db.execute(
            "SELECT COUNT(*) total, SUM(ok) ok, AVG(CASE WHEN ok=1 THEN rtt_ms END) rtt, "
            "MAX(ts) last_ts, (SELECT ok FROM ping_samples p2 WHERE p2.target=? ORDER BY ts DESC LIMIT 1) last_ok "
            "FROM ping_samples WHERE target=? AND ts>=?", (ip, ip, day_ago)).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        db.close()
    if not row or not row["total"]:
        return None
    return {"total": row["total"], "loss_pct_24h": round(100.0 * (row["total"] - row["ok"]) / row["total"], 2),
            "rtt_avg_ms": round(row["rtt"], 2) if row["rtt"] is not None else None,
            "last_seen": row["last_ts"], "up": bool(row["last_ok"])}


@app.get("/api/ip/<ip>")
def ip_dossier(ip: str):
    """Everything the probe knows about one IP, aggregated: inventory record and
    scan history, reverse-DNS, whether it's one of our own interfaces, approved
    scope / traffic-allow membership, LLDP neighbour match, outage-monitor ping
    stats, and every Suricata alert with this IP as source or destination.
    Read-only - it aggregates, it does not probe (trace/SNMP stay explicit)."""
    ip = valid_ip(ip)
    if not ip:
        return jsonify(error="a valid IP address is required"), 400

    host = history.get_host(ip)  # includes recent scans
    local_ifaces = [i["name"] for i in interfaces()
                    if re.search(rf"(^|[\s/]){re.escape(ip)}(/|$|\s)", i.get("addresses", ""))]
    scope = [t for t in targets() if t["address"] == ip]
    allow = [e for e in _traffic_allow_entries() if e["host"] == ip]
    lldp = [n for n in history.get_lldp_state(200) if n.get("mgmt_ip") == ip]

    # IDS alerts involving this IP (either direction), most recent first.
    _, ids = _ids_summary(500)
    alerts = ids.get("alerts", []) if isinstance(ids, dict) else []
    as_src = [a for a in alerts if a.get("src") == ip]
    as_dst = [a for a in alerts if a.get("dst") == ip]
    involved = [a for a in alerts if a.get("src") == ip or a.get("dst") == ip][:40]

    return jsonify({
        "ip": ip,
        "reverse_dns": _reverse_dns(ip),
        "is_local": bool(local_ifaces),
        "local_interfaces": local_ifaces,
        "host": host,
        "scope": scope,
        "traffic_allow": allow,
        "lldp": lldp,
        "monitor": _ip_monitor(ip),
        "ids": {"as_src": len(as_src), "as_dst": len(as_dst), "alerts": involved},
    })


# --- Staleness / freshness and anomaly aggregation -------------------------

def _freshness_sources() -> list[dict]:
    now = time.time()
    out = []

    def add(name: str, mtime: float | None, threshold: int, note: str = "") -> None:
        if mtime is None:
            out.append({"source": name, "present": False, "age_seconds": None,
                        "stale": None, "threshold": threshold, "note": note})
        else:
            age = int(now - mtime)
            out.append({"source": name, "present": True, "age_seconds": age,
                        "stale": age > threshold, "threshold": threshold, "note": note})

    # IDS eve.json
    add("ids_eve", IDS_LOG.stat().st_mtime if IDS_LOG.exists() else None, 1800,
        "Suricata alert log; updates only when it logs an event")
    # Outage monitor DB (last ping sample)
    monitor_mtime = None
    db = monitor_db()
    if db is not None:
        try:
            row = db.execute("SELECT MAX(ts) AS t FROM ping_samples").fetchone()
            monitor_mtime = row["t"] if row and row["t"] else None
        except sqlite3.Error:
            monitor_mtime = None
        db.close()
    add("outage_monitor", monitor_mtime, 300, "Continuous ping monitor sample")
    # LLDP inventory (last recorded neighbour update)
    add("lldp_inventory", history.lldp_last_update(), 900, "Neighbour snapshot (frames ~every 30s)")
    # Newest capture
    cap_mtime = None
    if CAPTURE_DIR.exists():
        caps = sorted(CAPTURE_DIR.glob("*.pcapng"), key=lambda p: p.stat().st_mtime, reverse=True)
        cap_mtime = caps[0].stat().st_mtime if caps else None
    add("captures", cap_mtime, 86400, "Most recent PCAPNG file (informational)")
    return out


@app.get("/api/health/freshness")
def health_freshness():
    sources = _freshness_sources()
    return jsonify({"time": time.time(), "sources": sources,
                    "stale": [s["source"] for s in sources if s.get("stale")]})


@app.get("/api/anomalies")
def anomalies():
    """Current things worth attention, aggregated from every subsystem. Read
    only - it summarises, it does not act."""
    items: list[dict] = []
    now = time.time()

    # Stale data feeds
    for s in _freshness_sources():
        if s.get("stale"):
            items.append({"level": "warning", "kind": "stale-data",
                          "message": f"{s['source']} has not updated in {s['age_seconds']}s",
                          "detail": s.get("note", "")})

    # Interface drops/errors
    for iface in interfaces():
        bad = iface.get("rx_dropped", 0) + iface.get("rx_errors", 0) + iface.get("tx_errors", 0)
        if bad > 0:
            items.append({"level": "warning" if bad > 100 else "info", "kind": "iface-errors",
                          "message": f"{iface['name']}: {bad} drops/errors on NIC counters",
                          "target": iface["name"]})

    # Outage monitor: open events + high loss targets
    db = monitor_db()
    if db is not None:
        try:
            open_evt = db.execute("SELECT id, started FROM events WHERE ended IS NULL ORDER BY started DESC LIMIT 1").fetchone()
            if open_evt:
                mins = int((now - open_evt["started"]) / 60)
                items.append({"level": "critical", "kind": "open-outage",
                              "message": f"Outage event #{open_evt['id']} open for {mins} min"})
            day_ago = now - 86400
            loss = db.execute(
                "SELECT target, COUNT(*) t, SUM(ok) ok FROM ping_samples WHERE ts >= ? GROUP BY target", (day_ago,)
            ).fetchall()
            for row in loss:
                if row["t"] and (row["t"] - row["ok"]) / row["t"] > 0.1:
                    pct = round(100.0 * (row["t"] - row["ok"]) / row["t"], 1)
                    items.append({"level": "warning", "kind": "packet-loss",
                                  "message": f"{row['target']}: {pct}% loss over 24h", "target": row["target"]})
        except sqlite3.Error:
            pass
        db.close()

    # IDS: recent high-severity counts
    _, ids = _ids_summary(1)
    by_sev = ids.get("by_severity", {}) if isinstance(ids, dict) else {}
    for sev in ("critical", "major"):
        if by_sev.get(sev):
            items.append({"level": "critical" if sev == "critical" else "warning", "kind": "ids-alerts",
                          "message": f"{by_sev[sev]} {sev} Suricata alert(s) in the recent window"})

    # Topology drift + new hosts
    changes = history.get_lldp_changes(50)
    recent_changes = [c for c in changes if now - c["ts"] < 86400]
    if recent_changes:
        items.append({"level": "info", "kind": "topology-change",
                      "message": f"{len(recent_changes)} LLDP neighbour change(s) in 24h",
                      "detail": ", ".join(f"{c['local_port']}:{c['field']}" for c in recent_changes[:5])})
    new_hosts = [h for h in history.get_hosts(500) if now - (h.get("first_seen") or 0) < 3600]
    if new_hosts:
        items.append({"level": "info", "kind": "new-hosts",
                      "message": f"{len(new_hosts)} host(s) first seen in the last hour",
                      "detail": ", ".join(h["address"] for h in new_hosts[:8])})

    order = {"critical": 0, "warning": 1, "info": 2}
    items.sort(key=lambda x: order.get(x["level"], 3))
    return jsonify({"time": now, "count": len(items), "anomalies": items})


# --- Job control -----------------------------------------------------------

@app.post("/api/jobs/<job_id>/stop")
def stop_job(job_id: str):
    """Stop a running job (e.g. a long capture). The ring capture keeps the
    files already written."""
    with jobs_lock:
        proc = job_procs.get(job_id)
        if job_id in jobs and jobs[job_id]["state"] == "running":
            jobs[job_id]["state"] = "stopping"
    if not proc:
        return jsonify(error="job is not running"), 404
    proc.terminate()
    return jsonify(status="stopping", id=job_id)


@app.get("/api/jobs/history")
def jobs_history():
    try:
        limit = max(1, min(int(request.args.get("limit", 100)), 500))
    except ValueError:
        return jsonify(error="limit must be a number"), 400
    return jsonify(history.get_jobs(limit))


@app.get("/api/jobs/<job_id>")
def job_detail(job_id: str):
    """One job's full record (live in-memory copy first, else the persisted
    one). Lets the Activity view re-open any past action's result - the
    'look up results after leaving the page' store."""
    with jobs_lock:
        live = dict(jobs[job_id]) if job_id in jobs else None
    if live is not None:
        return jsonify(live)
    for row in history.get_jobs(500):
        if row.get("id") == job_id:
            return jsonify(row)
    return jsonify(error="job not found"), 404


# --- IDS alert drill-down --------------------------------------------------

@app.get("/api/ids/alert")
def ids_alert_detail():
    """Every EVE event for one flow_id - the full context around an alert."""
    flow = str(request.args.get("flow", "")).strip()
    if not re.fullmatch(r"[0-9]+", flow):
        return jsonify(error="a numeric flow id is required"), 400
    command = [os.environ.get("PROBE_PYTHON", sys.executable), str(ROOT / "monitor" / "ids_reader.py"),
               "--log", str(IDS_LOG), "--flow", flow]
    code, output = run(command, 20)
    try:
        return jsonify(json.loads(output))
    except ValueError:
        return jsonify(status="error", note=(output or "no output")[:2000]), 500


def monitor_db() -> sqlite3.Connection | None:
    if not MONITOR_DB.is_file():
        return None
    db = sqlite3.connect(f"file:{MONITOR_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _collect_metrics_snapshot(window_s: int = 300) -> dict:
    """Gather a read-only observability snapshot for the /metrics endpoint.

    Pulls recent per-target reachability, latest service checks, latest interface
    counters and event counts from the monitor DB (read-only), plus collector
    counts from the history DB. Never launches a scan or touches a device; if the
    monitor DB is absent it still returns a valid snapshot with monitor_up=0.
    """
    now = time.time()
    since = now - window_s
    snap: dict = {
        "info": {"version": os.environ.get("PROBE_VERSION", "dev"),
                 "role": (settings_store.load().get("multinode") or {}).get("role", "standalone")},
        "scrape": {"monitor_up": 0},
        "targets": [], "services": [], "interfaces": [],
        "events": {"open": 0, "total_24h": 0},
    }

    db = monitor_db()
    if db is not None:
        snap["scrape"]["monitor_up"] = 1
        try:
            for row in db.execute(
                """
                SELECT target, COUNT(*) AS total, SUM(ok) AS ok,
                       AVG(CASE WHEN ok = 1 THEN rtt_ms END) AS rtt_avg,
                       MAX(ts) AS last_ts,
                       (SELECT ok FROM ping_samples p2 WHERE p2.target = p1.target
                        ORDER BY ts DESC LIMIT 1) AS last_ok
                FROM ping_samples p1 WHERE ts >= ? GROUP BY target
                """,
                (since,),
            ).fetchall():
                total = row["total"] or 0
                snap["targets"].append({
                    "name": row["target"],
                    "up": int(row["last_ok"] or 0),
                    "rtt_ms": round(row["rtt_avg"], 3) if row["rtt_avg"] is not None else None,
                    "loss_pct": round((total - (row["ok"] or 0)) / total, 4) if total else None,
                })

            # Latest sample per service name.
            for row in db.execute(
                """
                SELECT s.name, s.kind, s.ok, s.duration_ms
                FROM service_samples s
                JOIN (SELECT name, MAX(ts) AS mts FROM service_samples GROUP BY name) m
                  ON s.name = m.name AND s.ts = m.mts
                """
            ).fetchall():
                snap["services"].append({
                    "name": row["name"], "kind": row["kind"],
                    "up": int(row["ok"] or 0), "duration_ms": row["duration_ms"],
                })

            # Latest counter sample per interface.
            for row in db.execute(
                """
                SELECT i.interface, i.rx_dropped, i.tx_dropped, i.rx_errors,
                       i.tx_errors, i.multicast
                FROM iface_samples i
                JOIN (SELECT interface, MAX(ts) AS mts FROM iface_samples GROUP BY interface) m
                  ON i.interface = m.interface AND i.ts = m.mts
                """
            ).fetchall():
                snap["interfaces"].append({
                    "interface": row["interface"],
                    "rx_dropped": row["rx_dropped"], "tx_dropped": row["tx_dropped"],
                    "rx_errors": row["rx_errors"], "tx_errors": row["tx_errors"],
                    "multicast": row["multicast"],
                })

            snap["events"]["open"] = db.execute(
                "SELECT COUNT(*) FROM events WHERE ended IS NULL").fetchone()[0]
            snap["events"]["total_24h"] = db.execute(
                "SELECT COUNT(*) FROM events WHERE started >= ?", (now - 86400,)).fetchone()[0]
        except sqlite3.Error as exc:
            log.warning("metrics snapshot query failed: %s", exc)
        finally:
            db.close()

    try:
        collectors = history.list_collectors()
        if collectors:
            snap["collectors"] = {
                "count": len(collectors),
                "enabled": sum(1 for c in collectors if c.get("enabled")),
            }
    except Exception:  # history DB optional / best-effort
        pass

    return snap


def _metrics_authorized() -> bool:
    """Bearer-token gate for /metrics. No configured token -> open once enabled."""
    token = (settings_store.load().get("metrics") or {}).get("token") or ""
    if not token:
        return True
    header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not header.startswith(prefix):
        return False
    return secrets.compare_digest(header[len(prefix):].strip(), token)


@app.get("/metrics")
def prometheus_metrics():
    """Prometheus/OpenMetrics scrape endpoint (roadmap P4, task #52).

    Disabled by default; enable under Settings (metrics.enabled). Optionally
    gated by a bearer token so it can be exposed on a scrape network. It is in
    the auth allowlist because Prometheus scrapes without a browser session; the
    per-request gate here (enable flag + optional token) is its access control.
    """
    cfg = settings_store.load().get("metrics") or {}
    if not cfg.get("enabled"):
        return jsonify(error="metrics endpoint disabled"), 404
    if not _metrics_authorized():
        resp = jsonify(error="metrics token required")
        resp.headers["WWW-Authenticate"] = "Bearer"
        return resp, 401
    body = metrics_render.render(_collect_metrics_snapshot())
    return app.response_class(body, mimetype="text/plain; version=0.0.4; charset=utf-8")


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


def _chan_from_freq(freq):
    """2.4/5/6 GHz channel number from centre frequency in MHz (best-effort)."""
    if not freq:
        return None
    f = int(freq)
    if 2412 <= f <= 2484:
        return 14 if f == 2484 else (f - 2407) // 5
    if 5160 <= f <= 5885:
        return (f - 5000) // 5
    if 5955 <= f <= 7115:  # 6 GHz
        return (f - 5950) // 5
    return None


def _band_from_freq(freq):
    if not freq:
        return None
    f = int(freq)
    if f < 2500:
        return "2.4 GHz"
    if f < 5925:
        return "5 GHz"
    return "6 GHz"


# Signal considered "weak" once it drops below this (dBm); crossing it fires a warning.
WIFI_WEAK_DBM = -75

@app.get("/api/wifi/handovers")
def wifi_handovers():
    """Colorized roam/handover event log derived from consecutive wifi_samples.

    Levels map to the requested colours: info=BLUE (handover / (re)association),
    warning=YELLOW (weak signal, tx failures, beacon loss), error=RED (association
    lost / roam failed). Events are edge-triggered from transitions between adjacent
    samples so a steady link produces no noise."""
    db = monitor_db()
    if db is None:
        return jsonify(error="monitor database not found; is the outage monitor running?"), 503
    try:
        minutes = max(5, min(int(request.args.get("minutes", 720)), 14 * 1440))
        limit = max(1, min(int(request.args.get("limit", 200)), 1000))
    except ValueError:
        return jsonify(error="minutes/limit must be numbers"), 400
    since = time.time() - minutes * 60
    rows = db.execute(
        """
        SELECT ts, interface, connected, ssid, bssid, freq_mhz, signal_dbm,
               tx_retries, tx_failed, beacon_loss
        FROM wifi_samples WHERE ts >= ? ORDER BY interface, ts
        """,
        (since,),
    ).fetchall()
    db.close()

    events: list[dict] = []

    def emit(ts, iface, level, kind, summary, cur, extra=None):
        ev = {
            "ts": round(ts, 1),
            "interface": iface,
            "level": level,                       # error | warning | info
            "color": {"error": "red", "warning": "yellow", "info": "blue"}[level],
            "kind": kind,
            "summary": summary,
            "ssid": cur["ssid"],
            "bssid": cur["bssid"],
            "signal_dbm": cur["signal_dbm"],
            "band": _band_from_freq(cur["freq_mhz"]),
            "channel": _chan_from_freq(cur["freq_mhz"]),
        }
        if extra:
            ev.update(extra)
        events.append(ev)

    prev_by_iface: dict[str, sqlite3.Row] = {}
    weak_by_iface: dict[str, bool] = {}
    for cur in rows:
        iface = cur["interface"]
        prev = prev_by_iface.get(iface)
        prev_by_iface[iface] = cur

        if prev is None:
            weak_by_iface[iface] = bool(cur["connected"] and cur["signal_dbm"] is not None
                                        and cur["signal_dbm"] < WIFI_WEAK_DBM)
            continue

        # (Re)association / loss transitions.
        if prev["connected"] and not cur["connected"]:
            emit(cur["ts"], iface, "error", "assoc-lost",
                 f"Disconnected from {prev['ssid'] or 'network'}", prev,
                 {"from_bssid": prev["bssid"]})
            weak_by_iface[iface] = False
            continue
        if not prev["connected"] and cur["connected"]:
            emit(cur["ts"], iface, "info", "associated",
                 f"Associated with {cur['ssid'] or 'network'}", cur)
            weak_by_iface[iface] = bool(cur["signal_dbm"] is not None and cur["signal_dbm"] < WIFI_WEAK_DBM)
            continue
        if not cur["connected"]:
            continue

        # Both connected: look for a roam (BSSID change) or SSID change.
        if prev["bssid"] and cur["bssid"] and prev["bssid"] != cur["bssid"]:
            same_net = (prev["ssid"] == cur["ssid"])
            band_note = ""
            if _band_from_freq(prev["freq_mhz"]) != _band_from_freq(cur["freq_mhz"]):
                band_note = f" ({_band_from_freq(prev['freq_mhz'])} → {_band_from_freq(cur['freq_mhz'])})"
            emit(cur["ts"], iface, "info", "handover",
                 f"Roamed to {cur['bssid']}{band_note}" if same_net
                 else f"Switched network to {cur['ssid'] or '?'}{band_note}", cur,
                 {"from_bssid": prev["bssid"], "from_signal_dbm": prev["signal_dbm"]})
        elif prev["ssid"] != cur["ssid"]:
            emit(cur["ts"], iface, "info", "network-change",
                 f"Network changed to {cur['ssid'] or '?'}", cur)

        # Counter-based warnings (cumulative counters; a positive delta = new events
        # this window). Reset the baseline across a roam so we don't count the wrap.
        roamed = prev["bssid"] != cur["bssid"]
        if not roamed:
            for col, kind, label in (
                ("tx_failed", "tx-failures", "TX failures"),
                ("beacon_loss", "beacon-loss", "Beacon loss"),
            ):
                pv, cv = prev[col], cur[col]
                if pv is not None and cv is not None and cv > pv:
                    emit(cur["ts"], iface, "warning", kind,
                         f"{label}: +{cv - pv}", cur, {"delta": cv - pv})

        # Weak-signal edge trigger (only when crossing the threshold).
        now_weak = cur["signal_dbm"] is not None and cur["signal_dbm"] < WIFI_WEAK_DBM
        if now_weak and not weak_by_iface.get(iface):
            emit(cur["ts"], iface, "warning", "weak-signal",
                 f"Weak signal {cur['signal_dbm']} dBm", cur)
        weak_by_iface[iface] = now_weak

    events.sort(key=lambda e: e["ts"], reverse=True)
    counts = {"error": 0, "warning": 0, "info": 0}
    for ev in events:
        counts[ev["level"]] += 1

    current = {}
    for iface, last in prev_by_iface.items():
        current[iface] = {
            "connected": bool(last["connected"]),
            "ssid": last["ssid"],
            "bssid": last["bssid"],
            "signal_dbm": last["signal_dbm"],
            "band": _band_from_freq(last["freq_mhz"]),
            "channel": _chan_from_freq(last["freq_mhz"]),
            "ts": round(last["ts"], 1),
        }
    return jsonify({"events": events[:limit], "counts": counts, "current": current,
                    "window_minutes": minutes, "total": len(events)})


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


def _trend_window(default_minutes: int = 360) -> tuple[float, float]:
    """(since_ts, bucket_seconds) from the request's ?minutes, clamped like the
    other monitor endpoints. Buckets aim for ~600 points over the window."""
    minutes = max(30, min(int(request.args.get("minutes", default_minutes)), 14 * 1440))
    bucket = max(60.0, minutes * 60 / 600)
    return time.time() - minutes * 60, bucket


@app.get("/api/monitor/tcp")
def monitor_tcp():
    """TCP retransmission-ratio / reset-rate trend from cumulative kernel
    counters (task #50). Sustained rise vs single spike, never raw counters."""
    try:
        since, bucket = _trend_window()
    except ValueError:
        return jsonify(error="minutes must be a number"), 400
    db = monitor_db()
    if db is None:
        return jsonify(error="monitor database not found; is the outage monitor running?"), 503
    rows = db.execute(
        "SELECT ts, in_segs, out_segs, retrans_segs, out_rsts, attempt_fails, "
        "estab_resets, tcp_syn_retrans, tcp_lost_retransmit "
        "FROM tcp_samples WHERE ts >= ? ORDER BY ts",
        (since,),
    ).fetchall()
    db.close()
    samples = [dict(row) for row in rows]
    result = trends.tcp_trend(samples, bucket_s=bucket)
    result["samples"] = len(samples)
    return jsonify(result)


@app.get("/api/monitor/dns")
def monitor_dns():
    """DNS failure-rate trend from service_samples (kind='dns'), task #50."""
    try:
        since, bucket = _trend_window()
    except ValueError:
        return jsonify(error="minutes must be a number"), 400
    db = monitor_db()
    if db is None:
        return jsonify(error="monitor database not found; is the outage monitor running?"), 503
    rows = db.execute(
        "SELECT ts, ok FROM service_samples WHERE kind = 'dns' AND ts >= ? ORDER BY ts",
        (since,),
    ).fetchall()
    db.close()
    samples = [dict(row) for row in rows]
    result = trends.dns_trend(samples, bucket_s=bucket)
    result["samples"] = len(samples)
    return jsonify(result)


# --- Sustained-state alerting (task #53) -------------------------------------
# Watches the task #50 trend verdicts + open outage events and notifies once per
# transition. The evaluator is pure (dashboard/alerts.py); everything below
# gathers signals from the read-only monitor DB and dispatches to the operator's
# configured webhook/email channels.
_alert_lock = threading.Lock()


def _gather_alert_signals(alerting_cfg: dict) -> list[dict]:
    """Build the current signal list from the monitor DB. Only signals the
    operator enabled are included; a missing DB yields no signals (never an
    alert). Read-only: never launches a probe."""
    want = alerting_cfg.get("signals") or {}
    window = max(5, min(int(alerting_cfg.get("window_minutes", 60)), 14 * 1440))
    since = time.time() - window * 60
    bucket = max(60.0, window * 60 / 600)
    db = monitor_db()
    if db is None:
        return []
    signals: list[dict] = []
    try:
        if want.get("tcp_retransmit", True):
            rows = db.execute(
                "SELECT ts, in_segs, out_segs, retrans_segs, out_rsts, attempt_fails, "
                "estab_resets, tcp_syn_retrans, tcp_lost_retransmit "
                "FROM tcp_samples WHERE ts >= ? ORDER BY ts", (since,),
            ).fetchall()
            v = trends.tcp_trend([dict(r) for r in rows], bucket_s=bucket)["verdict"]
            signals.append({"id": "tcp_retransmit", "title": "TCP retransmission",
                            "state": v["state"],
                            "value": f"{(v.get('latest') or 0) * 100:.2f}%",
                            "summary": "retransmitted/sent segment ratio"})
        if want.get("dns_failure", True):
            rows = db.execute(
                "SELECT ts, ok FROM service_samples WHERE kind = 'dns' AND ts >= ? ORDER BY ts",
                (since,),
            ).fetchall()
            v = trends.dns_trend([dict(r) for r in rows], bucket_s=bucket)["verdict"]
            signals.append({"id": "dns_failure", "title": "DNS failures",
                            "state": v["state"],
                            "value": f"{v.get('latest') or 0:.1f}%",
                            "summary": "DNS probe failure rate"})
        if want.get("outage", True):
            row = db.execute(
                "SELECT id, started, failed_targets FROM events "
                "WHERE ended IS NULL ORDER BY started DESC LIMIT 1"
            ).fetchone()
            if row is not None:
                signals.append({"id": "outage", "title": "Outage event",
                                "state": "degraded", "value": "open",
                                "summary": f"targets down: {row['failed_targets'] or '?'}"})
            else:
                signals.append({"id": "outage", "title": "Outage event",
                                "state": "stable", "value": "clear",
                                "summary": "no open outage"})
    finally:
        db.close()
    return signals


def _alert_evaluate_once() -> dict:
    """One evaluation cycle: gather signals, cross them against persisted edge
    state, dispatch any transitions, persist. Serialized so the poller and a
    manual trigger never race. Returns a small summary."""
    cfg = settings_store.load().get("alerting", {})
    if not cfg.get("enabled"):
        return {"enabled": False, "events": 0}
    with _alert_lock:
        signals = _gather_alert_signals(cfg)
        state = alerts.load_state()
        events, new_signals = alerts.evaluate(
            signals, state.get("signals", {}), min_state=cfg.get("min_state", "rising"))
        for event in events:
            event["delivery"] = alerts.dispatch(event, cfg)
            state.setdefault("history", []).append(event)
        state["signals"] = new_signals
        state["last_run"] = time.time()
        alerts.save_state(state)
    return {"enabled": True, "signals": len(signals), "events": len(events)}


def _alert_poller() -> None:
    while True:
        cfg = settings_store.load().get("alerting", {})
        interval = max(10, int(cfg.get("poll_seconds", 60)))
        if cfg.get("enabled"):
            try:
                _alert_evaluate_once()
            except Exception:  # an eval failure must never kill the loop
                pass
        time.sleep(interval)


@app.get("/api/alerts")
def alerts_status():
    """Current signal states, recent alert history and the (redacted) config."""
    cfg = settings_store.redacted().get("alerting", {})
    state = alerts.load_state()
    history = list(reversed(state.get("history", [])))[:50]
    # Live signal snapshot (does not mutate edge state) when enabled.
    live: list[dict] = []
    if settings_store.load().get("alerting", {}).get("enabled"):
        try:
            live = _gather_alert_signals(settings_store.load().get("alerting", {}))
        except Exception:
            live = []
    return jsonify({"config": cfg, "signals": live,
                    "persisted": state.get("signals", {}),
                    "history": history, "last_run": state.get("last_run")})


@app.post("/api/alerts/test")
def alerts_test():
    """Send a synthetic 'firing' notification through the enabled channels so the
    operator can verify webhook/email wiring. Does not touch edge state."""
    cfg = settings_store.load().get("alerting", {})
    if not (cfg.get("webhook", {}).get("enabled") or cfg.get("email", {}).get("enabled")):
        return jsonify(error="enable a webhook or email channel first"), 400
    event = {"id": "test", "title": "Test alert", "kind": "firing",
             "state": "degraded", "value": "test",
             "summary": "manual test from the dashboard", "ts": time.time()}
    return jsonify({"delivery": alerts.dispatch(event, cfg)})


@app.post("/api/alerts/evaluate")
def alerts_evaluate_now():
    """Run one evaluation cycle immediately (for operators who don't want to wait
    for the poll interval)."""
    return jsonify(_alert_evaluate_once())


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


# Private/link-local ranges that count as "inside" the network for topology.
# Deliberately an explicit RFC1918 + link-local list, NOT ipaddress.is_private,
# because is_private also matches CGNAT 100.64.0.0/10 - which is the carrier
# side of the WAN and must read as external so the map trims there.
_INTERNAL_NETS = [
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
]


def _is_internal_ip(text: str) -> bool:
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return False
    return any(addr in net for net in _INTERNAL_NETS)


def _trim_to_wan(hops: list[str]) -> tuple[list[str], str | None]:
    """Keep the internal (RFC1918/link-local) prefix of a hop chain and stop at
    the WAN edge. Returns (internal_hops, wan_gateway) where wan_gateway is the
    last internal hop before the path leaves for the public/CGNAT internet, or
    None if the whole known chain stayed internal (target is on-net)."""
    internal: list[str] = []
    wan_gateway: str | None = None
    for hop in hops:
        if hop == "[LOCALHOST]" or _is_internal_ip(hop):
            internal.append(hop)
            continue
        # First non-internal hop: the previous hop was the gateway to the WAN.
        wan_gateway = internal[-1] if internal and internal[-1] != "[LOCALHOST]" else None
        break
    return internal, wan_gateway


@app.get("/api/monitor/topology")
def monitor_topology():
    """Merge the collected traceroute hop-chains into one internal topology
    graph, trimmed at the WAN gateway (the last private hop before traffic
    leaves for the public internet). Node labels are enriched from the monitor
    target names, LLDP neighbours and this probe's own interfaces."""
    db = monitor_db()
    if db is None:
        return jsonify(error="monitor database not found; is the outage monitor running?"), 503
    state = db.execute("SELECT name, hops, updated FROM route_state ORDER BY name").fetchall()
    try:  # route_metrics is newer; tolerate a monitor that predates it
        metrics_rows = db.execute("SELECT name, hubs, updated FROM route_metrics").fetchall()
    except sqlite3.Error:
        metrics_rows = []
    db.close()

    # --- enrichment lookups -------------------------------------------------
    target_names: dict[str, str] = {}
    try:
        for tgt in _monitor_config_effective().get("targets", []):
            if tgt.get("address"):
                target_names[tgt["address"]] = tgt.get("name") or tgt["address"]
    except Exception:  # config is best-effort enrichment, never fatal
        pass

    lldp_by_ip: dict[str, str] = {}
    try:
        for n in history.get_lldp_state():
            ip = (n.get("mgmt_ip") or "").strip()
            sysname = (n.get("system") or "").strip()
            if ip and sysname:
                lldp_by_ip[ip] = sysname
    except Exception:
        pass

    own_ips: set[str] = set()
    try:
        # `addresses` is the raw `ip -brief address` line (name, state, CIDRs);
        # only the CIDR tokens are addresses - the rest is not.
        for iface in interfaces():
            for token in (iface.get("addresses") or "").split():
                if "/" in token:
                    own_ips.add(token.split("/")[0])
    except Exception:
        pass

    def label_for(ip: str) -> tuple[str, str]:
        """Return (label, kind) for an internal hop IP."""
        if ip in own_ips:
            return "this probe", "self"
        if ip in target_names:
            return target_names[ip], "target"
        if ip in lldp_by_ip:
            return lldp_by_ip[ip], "neighbour"
        return ip, "hop"

    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str]] = set()
    wan_gateways: set[str] = set()

    root_id = "probe"
    nodes[root_id] = {"id": root_id, "label": "this probe", "ip": None,
                      "kind": "self", "depth": 0, "targets": [], "exits": []}

    for row in state:
        name = row["name"]
        chain = [h for h in (row["hops"] or "").split(">") if h]
        internal, wan_gateway = _trim_to_wan(chain)
        # Drop the leading localhost marker; the probe root stands in for it.
        internal = [h for h in internal if h != "[LOCALHOST]"]
        if not internal:
            continue
        prev = root_id
        for depth, ip in enumerate(internal, start=1):
            label, kind = label_for(ip)
            node = nodes.get(ip)
            if node is None:
                node = nodes[ip] = {"id": ip, "label": label, "ip": ip,
                                    "kind": kind, "depth": depth, "targets": [], "exits": []}
            else:
                node["depth"] = min(node["depth"], depth)
                # A hop that is also a probe target keeps the richer kind.
                if kind in ("self", "target", "neighbour") and node["kind"] == "hop":
                    node["kind"], node["label"] = kind, label
            edges.add((prev, ip))
            prev = ip
        # The final internal hop is where this target's traceroute ended. If the
        # path never left the private network (wan_gateway is None) the target is
        # genuinely reached on-net; otherwise the last hop is the WAN edge and the
        # target lives beyond it - the path merely *exits* there.
        last_ip = internal[-1]
        bucket = "exits" if wan_gateway else "targets"
        if name not in nodes[last_ip][bucket]:
            nodes[last_ip][bucket].append(name)
        if wan_gateway:
            wan_gateways.add(wan_gateway)

    for gw in wan_gateways:
        if gw in nodes:
            nodes[gw]["kind"] = "wan-gateway"

    # --- per-hop quality lanes ---------------------------------------------
    # One card-lane per traced target, from this probe out to the WAN gateway,
    # each hop carrying its mtr latency/jitter/loss. Trimmed like the map.
    paths = []
    for mrow in metrics_rows:
        try:
            hubs = json.loads(mrow["hubs"] or "[]")
        except ValueError:
            continue
        lane_hops = []
        wan_reached = False
        for hub in hubs:
            host = hub.get("host") or "*"
            if host == "*":
                # Unknown hop: keep it only while we are still inside the LAN;
                # a public non-responder past the edge is dropped by the trim below.
                lane_hops.append({**hub, "label": "* (no reply)", "kind": "hop", "internal": None})
                continue
            if not _is_internal_ip(host):
                wan_reached = True
                break  # left the private network - stop at the WAN edge
            label, kind = label_for(host)
            lane_hops.append({**hub, "label": label, "kind": kind, "internal": True})
        # Strip trailing unknown hops (they sit beyond the last known LAN device).
        while lane_hops and lane_hops[-1]["internal"] is None:
            lane_hops.pop()
        if not lane_hops:
            continue
        # Mark the WAN-edge card and whether the destination is truly on-net.
        if wan_reached:
            for hop in reversed(lane_hops):
                if hop["internal"]:
                    hop["kind"] = "wan-gateway"
                    break
        paths.append({
            "name": mrow["name"],
            "reached": "wan" if wan_reached else "on-net",
            "updated": mrow["updated"],
            "hops": lane_hops,
        })
    paths.sort(key=lambda p: p["name"])

    return jsonify({
        "nodes": list(nodes.values()),
        "edges": [{"from": a, "to": b} for a, b in sorted(edges)],
        "wan_gateways": sorted(wan_gateways),
        "paths": paths,
        "updated": max((row["updated"] for row in state), default=None),
    })


# --- Multi-collector: enrollment, ingest, scoped registry -------------------
COLLECTOR_DIST = Path(os.environ.get("PROBE_COLLECTOR_DIST", ROOT / "collector" / "dist")).resolve()


def _multinode_cfg() -> dict:
    return settings_store.load().get("multinode", {}) or {}


def _collector_release() -> dict:
    """The collector binaries this aggregator can hand out, from the build
    manifest in collector/dist/. Returns {version, files:{'os/arch': filename}}.
    Empty version means no release is available to push."""
    manifest = COLLECTOR_DIST / "manifest.json"
    try:
        data = json.loads(manifest.read_text())
        files = data.get("files") if isinstance(data.get("files"), dict) else {}
        return {"version": str(data.get("version") or ""), "files": files}
    except (OSError, ValueError):
        return {"version": "", "files": {}}


def _release_sha256(path: Path) -> str:
    """SHA-256 of a release binary, so the update instruction can pin exactly
    which bytes the collector must install."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sign_update(secret: str, version: str, os_arch: str, sha256hex: str) -> str:
    """HMAC-SHA256 over the canonical update message, keyed by the collector's own
    signing secret. The exact same message is reconstructed and verified agent-side
    (see collector selfUpdate), so an on-path attacker who cannot produce this MAC
    cannot make the agent swap its binary - even over plain HTTP or with TLS
    verification off. Message layout MUST stay byte-identical on both ends."""
    msg = f"{version}\n{os_arch}\n{sha256hex}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _release_file_for(os_name: str, arch: str) -> Path | None:
    """Resolve (and sandbox) the binary path for one os/arch inside the dist dir."""
    rel = _collector_release().get("files", {}).get(f"{os_name}/{arch}")
    if not rel:
        return None
    path = (COLLECTOR_DIST / rel).resolve()
    # Never serve anything outside the dist dir, whatever the manifest claims.
    if COLLECTOR_DIST not in path.parents or not path.is_file():
        return None
    return path


def _require_ingest() -> tuple[str | None, object]:
    """Authenticate a pushing collector. Ingest is allowed only when this node's
    accept-external-collectors toggle is on AND the presented key matches an
    enrolled, non-revoked collector. The key travels in the X-Ingest-Key header
    (or HTTP Basic password). Returns (collector_id, None) on success, else
    (None, error_response)."""
    if not _multinode_cfg().get("accept_external_collectors"):
        return None, (jsonify(error="this node is not accepting external collectors"), 403)
    key = request.headers.get("X-Ingest-Key", "")
    if not key and request.authorization:
        key = request.authorization.password or ""
    collector_id = history.authenticate_collector(key)
    if not collector_id:
        return None, (jsonify(error="invalid or revoked collector key"), 401)
    return collector_id, None


@app.post("/api/ingest/heartbeat")
def ingest_heartbeat():
    collector_id, err = _require_ingest()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    reported_version = str(body.get("version", ""))[:80]
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    history.touch_collector(
        collector_id,
        hostname=str(body.get("hostname", ""))[:200],
        node_ip=str(body.get("node_ip", ""))[:200],
        version=reported_version,
        meta=meta,
        status=body.get("status") if isinstance(body.get("status"), dict) else {})

    resp = {"ok": True, "collector_id": collector_id}
    release = _collector_release()
    resp["latest_version"] = release["version"]
    # If an operator asked this collector to update and it is genuinely behind,
    # tell it where to fetch the new binary. Once it reports the new version the
    # request is auto-cleared so it does not loop.
    if release["version"] and reported_version == release["version"]:
        history.request_collector_update(collector_id, False)
    elif release["version"] and history.collector_update_pending(collector_id):
        # Sign the instruction so the agent can prove it came from us and pins the
        # exact bytes to install. We sign for the agent's OWN os/arch (from its
        # heartbeat) - if we hold no matching binary, or no signing secret, we
        # simply do not offer an update rather than send an unverifiable one.
        os_name = re.sub(r"[^a-z0-9]", "", str(meta.get("os", "")).lower())[:16]
        arch = re.sub(r"[^a-z0-9]", "", str(meta.get("arch", "")).lower())[:16]
        bin_path = _release_file_for(os_name, arch)
        secret = history.get_collector_update_secret(collector_id)
        if bin_path and secret:
            sha256hex = _release_sha256(bin_path)
            os_arch = f"{os_name}/{arch}"
            resp["update"] = {
                "version": release["version"],
                "download": "/api/ingest/binary",  # collector appends ?os=&arch=
                "os": os_name, "arch": arch,
                "sha256": sha256hex,
                "sig": _sign_update(secret, release["version"], os_arch, sha256hex),
            }
    return jsonify(resp)


@app.get("/api/ingest/binary")
def ingest_binary():
    """Serve a collector binary to an authenticated collector for self-update.
    Gated by the same ingest auth as heartbeats/samples."""
    collector_id, err = _require_ingest()
    if err:
        return err
    os_name = re.sub(r"[^a-z0-9]", "", request.args.get("os", "").lower())[:16]
    arch = re.sub(r"[^a-z0-9]", "", request.args.get("arch", "").lower())[:16]
    path = _release_file_for(os_name, arch)
    if not path:
        return jsonify(error=f"no release binary for {os_name}/{arch}"), 404
    return send_from_directory(str(path.parent), path.name, as_attachment=True)


@app.get("/api/ingest/checks")
def ingest_checks():
    """Hand a collector the enabled+started probe plan so it runs the SAME active
    checks a standalone node runs, from the same central monitor config. The
    collector pushes results back via /api/ingest/samples as host_checks /
    service_checks / port_checks. Gated by the same ingest auth."""
    _, err = _require_ingest()
    if err:
        return err
    cfg = _monitor_config_effective()

    def live(items):
        return [i for i in items if i.get("enabled", True) and i.get("started", True)]

    targets = [{"name": t["name"], "address": t["address"], "group": t.get("group", "custom")}
               for t in live(cfg.get("targets", []))]
    services = [{"name": s["name"], "kind": s["kind"], "target": s["target"]}
                for s in live(cfg.get("services", []))]
    ports = [{"name": p["name"], "host": p["host"], "port": p["port"],
              "proto": p.get("proto", "tcp"), "send": p.get("send", ""),
              "expect": p.get("expect", "")}
             for p in live(cfg.get("ports", []))]
    return jsonify(targets=targets, services=services, ports=ports)


@app.post("/api/ingest/samples")
def ingest_samples():
    collector_id, err = _require_ingest()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    stream = str(body.get("stream", "")).strip()[:40]
    rows = body.get("rows")
    if not stream or not isinstance(rows, list):
        return jsonify(error="body must be {stream: str, rows: [ ... ]}"), 400
    rows = [r for r in rows if isinstance(r, dict)][:1000]
    stored = history.ingest_samples(collector_id, stream, rows)
    return jsonify(ok=True, collector_id=collector_id, stream=stream, stored=stored)


@app.get("/api/collectors")
def list_collectors_api():
    """Enrolled collectors + this local node, for the scoped selector. Marks a
    collector stale if it has not sent a heartbeat within ~3 intervals."""
    now = time.time()
    release = _collector_release()
    latest = release["version"]
    collectors = history.list_collectors()
    for c in collectors:
        last = c.get("last_seen")
        c["online"] = bool(last and (now - last) < 180)
        cur = c.get("version") or ""
        # An update is offered only when we actually hold a newer build for it.
        c["latest_version"] = latest
        c["update_available"] = bool(latest and cur and cur != latest)
    local = {"collector_id": "local", "name": "this node", "enabled": True,
             "online": True, "local": True, "version": _collector_release()["version"],
             "role": _multinode_cfg().get("role", "standalone")}
    return jsonify(local=local, collectors=collectors, latest_version=latest,
                   accept_external_collectors=bool(_multinode_cfg().get("accept_external_collectors")))


@app.post("/api/collectors")
def enroll_collector_api():
    """Enroll a new collector and return its key ONCE (never retrievable again)."""
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()[:80]
    result = history.enroll_collector(name)
    if result is None:
        return jsonify(error="could not enroll collector"), 500
    return jsonify(result), 201


@app.post("/api/collectors/<collector_id>/rotate")
def rotate_collector_api(collector_id: str):
    """Issue a fresh key (invalidating the previous one)."""
    result = history.rotate_collector_key(collector_id)
    if result is None:
        return jsonify(error="collector not found"), 404
    return jsonify(result)


@app.post("/api/collectors/<collector_id>/revoke")
def revoke_collector_api(collector_id: str):
    """Invalidate a collector's key without deleting its history."""
    if not history.revoke_collector(collector_id):
        return jsonify(error="collector not found"), 404
    return jsonify(ok=True, collector_id=collector_id, enabled=False)


@app.post("/api/collectors/<collector_id>/update")
def update_collector_api(collector_id: str):
    """Request that a collector self-update to the latest binary we hold. The
    collector picks this up on its next heartbeat and pulls the new binary."""
    release = _collector_release()
    if not release["version"]:
        return jsonify(error="no collector release is available to push"), 409
    if not history.request_collector_update(collector_id, True):
        return jsonify(error="collector not found"), 404
    return jsonify(ok=True, collector_id=collector_id, target_version=release["version"])


@app.delete("/api/collectors/<collector_id>")
def delete_collector_api(collector_id: str):
    if not history.delete_collector(collector_id):
        return jsonify(error="collector not found"), 404
    return jsonify(ok=True, deleted=collector_id)


@app.get("/api/multinode")
def get_multinode():
    cfg = _multinode_cfg()
    return jsonify(role=cfg.get("role", "standalone"),
                   accept_external_collectors=bool(cfg.get("accept_external_collectors")))


@app.post("/api/multinode")
def set_multinode():
    """Update this node's role and the accept-external-collectors master switch."""
    body = request.get_json(silent=True) or {}
    update: dict = {}
    if "role" in body:
        role = str(body["role"]).strip()
        if role not in ("standalone", "collector"):
            return jsonify(error="role must be 'standalone' or 'collector'"), 400
        update["role"] = role
    if "accept_external_collectors" in body:
        update["accept_external_collectors"] = bool(body["accept_external_collectors"])
    if not update:
        return jsonify(error="nothing to update"), 400
    settings_store.apply_update({"multinode": update})
    history.record_audit("multinode.update", user=_session_user() or "-",
                         target="multinode",
                         detail=", ".join(f"{k}={v}" for k, v in sorted(update.items())))
    return jsonify(_multinode_cfg())


# --- Auvik-style network map ------------------------------------------------
# Relative "specificity" of a node kind: a later observation may only *promote*
# a node to a richer role (a plain host that turns out to be the gateway), never
# demote it. See docs/07-network-map-and-monitoring-roadmap.md.
_KIND_RANK = {
    "unknown": 0, "host": 1, "hop": 1, "target": 2, "neighbour": 2,
    "ap": 3, "printer": 3, "phone": 3, "server": 3, "workstation": 3, "iot": 3,
    "router": 4, "switch": 4, "wan-gateway": 5, "firewall": 5, "collector": 5,
    "self": 6, "internet": 6, "subnet": 6,
}


def _map_subnet_of(ip_text: str, own_subnets: list) -> str | None:
    """Which subnet an IP belongs to: an own-interface network if one contains
    it, else a synthetic /24 grouping for any other internal address."""
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return None
    for net in own_subnets:
        if addr in net:
            return str(net)
    if _is_internal_ip(ip_text) and addr.version == 4:
        try:
            return str(ipaddress.ip_network(f"{ip_text}/24", strict=False))
        except ValueError:
            return None
    return None


@app.get("/api/map")
def network_map():
    """Assemble one Auvik-style topology graph from the probe's existing
    passive/safe data: own interfaces, traceroute hop-chains, LLDP neighbours,
    ARP/discovery hosts, Wi-Fi APs and outage-monitor reachability. Read-only and
    cached - it never launches a scan. Every node is tagged with the observing
    collector (`local` on a standalone box) so the multi-collector view can later
    narrow to one. See docs/07-network-map-and-monitoring-roadmap.md."""
    now = time.time()

    nodes: dict[str, dict] = {}
    edges: dict[tuple, dict] = {}
    subnets: dict[str, dict] = {}

    def node(nid: str, **kw) -> dict:
        n = nodes.get(nid)
        if n is None:
            n = nodes[nid] = {
                "id": nid, "label": nid, "kind": "unknown", "status": "unknown",
                "ips": [], "macs": [], "vendor": "", "subnet": None,
                "confidence": "observed", "collector": "local", "detail": {},
            }
        for key, val in kw.items():
            if key in ("ips", "macs"):
                for item in (val or []):
                    item = (item or "").strip()
                    if item and item not in n[key]:
                        n[key].append(item)
            elif key == "kind":
                if val and _KIND_RANK.get(val, 0) > _KIND_RANK.get(n["kind"], 0):
                    n["kind"] = val
            elif key == "label":
                if val and (n["label"] == nid or not n["label"]):
                    n["label"] = val
            elif key == "detail":
                n["detail"].update({k: v for k, v in (val or {}).items() if v not in (None, "")})
            elif val not in (None, ""):
                n[key] = val
        return n

    def edge(a: str, b: str, layer="l3", media="wired", confidence="inferred", **detail) -> None:
        key = (a, b)
        e = edges.get(key)
        if e is None:
            e = edges[key] = {"from": a, "to": b, "layer": layer, "media": media,
                              "confidence": confidence, "detail": {}}
        # A definitive (observed) sighting upgrades an inferred edge.
        if confidence == "observed" and e["confidence"] != "observed":
            e.update({"layer": layer, "media": media, "confidence": "observed"})
        e["detail"].update({k: v for k, v in detail.items() if v not in (None, "")})

    # --- own interfaces -> self node, own IPs / subnets ---------------------
    own_ips: set[str] = set()
    own_subnets: list = []
    iface_detail: list[dict] = []
    try:
        for iface in interfaces():
            mac = (iface.get("mac") or "").lower()
            for token in (iface.get("addresses") or "").split():
                if "/" in token:
                    own_ips.add(token.split("/")[0])
                    try:
                        own_subnets.append(ipaddress.ip_network(token, strict=False))
                    except ValueError:
                        pass
            iface_detail.append({"name": iface.get("name"), "state": iface.get("state"),
                                 "mac": mac, "addresses": iface.get("addresses")})
    except Exception:
        pass
    own_subnets = list({str(n): n for n in own_subnets}.values())
    node("self", label="this probe", kind="self", status="up", ips=sorted(own_ips))

    # --- monitor reachability (last ok + 24h loss per target) ---------------
    monitor_status: dict[str, dict] = {}
    route_rows: list = []
    db = monitor_db()
    if db is not None:
        day_ago = now - 86400
        try:
            for row in db.execute(
                "SELECT target, COUNT(*) total, SUM(ok) ok, "
                "AVG(CASE WHEN ok=1 THEN rtt_ms END) rtt_avg, "
                "(SELECT ok FROM ping_samples p2 WHERE p2.target=p1.target ORDER BY ts DESC LIMIT 1) last_ok "
                "FROM ping_samples p1 WHERE ts>=? GROUP BY target", (day_ago,)):
                monitor_status[row["target"]] = {
                    "up": bool(row["last_ok"]),
                    "loss_pct": round(100.0 * (row["total"] - (row["ok"] or 0)) / row["total"], 2) if row["total"] else None,
                    "rtt_ms": round(row["rtt_avg"], 2) if row["rtt_avg"] is not None else None,
                }
        except sqlite3.Error:
            pass
        try:
            route_rows = db.execute("SELECT name, hops, updated FROM route_state ORDER BY name").fetchall()
        except sqlite3.Error:
            route_rows = []
        db.close()

    def status_for(ip: str, last_seen: float | None = None) -> str:
        st = monitor_status.get(ip)
        if st is not None:
            return "up" if st["up"] else "down"
        if last_seen and (now - last_seen) < 900:
            return "up"
        return "unknown"

    # --- enrichment lookups (reused from the topology endpoint) -------------
    target_names: dict[str, str] = {}
    try:
        for tgt in _monitor_config_effective().get("targets", []):
            if tgt.get("address"):
                target_names[tgt["address"]] = tgt.get("name") or tgt["address"]
    except Exception:
        pass
    lldp_state: list[dict] = []
    try:
        lldp_state = history.get_lldp_state()
    except Exception:
        lldp_state = []
    lldp_by_ip = {(n.get("mgmt_ip") or "").strip(): (n.get("system") or "").strip()
                  for n in lldp_state if (n.get("mgmt_ip") or "").strip() and (n.get("system") or "").strip()}

    def label_for(ip: str) -> tuple[str, str]:
        if ip in own_ips:
            return "this probe", "self"
        if ip in target_names:
            return target_names[ip], "target"
        if ip in lldp_by_ip:
            return lldp_by_ip[ip], "neighbour"
        return ip, "hop"

    # --- subnet clouds ------------------------------------------------------
    def subnet_node(cidr: str) -> str | None:
        if not cidr:
            return None
        if cidr not in subnets:
            subnets[cidr] = {"cidr": cidr, "role": None, "count": 0}
            node("subnet:" + cidr, label=cidr, kind="subnet", status="up")
        return "subnet:" + cidr

    def attach_host(node_id: str, ip: str, media="wired") -> None:
        cidr = _map_subnet_of(ip, own_subnets)
        if not cidr:
            return
        sid = subnet_node(cidr)
        nodes[node_id]["subnet"] = cidr
        edge(sid, node_id, layer="l2", media=media, confidence="inferred")

    for ip in own_ips:
        attach_host("self", ip)

    # --- Layer-3 hierarchy from traceroute hop-chains -----------------------
    wan_gateways: set[str] = set()
    for row in route_rows:
        chain = [h for h in (row["hops"] or "").split(">") if h]
        internal, wan_gateway = _trim_to_wan(chain)
        internal = [h for h in internal if h != "[LOCALHOST]" and h not in own_ips]
        prev = "self"
        for ip in internal:
            label, kind = label_for(ip)
            node(ip, label=label, kind=kind if kind in ("target", "neighbour") else "hop",
                 ips=[ip], status=status_for(ip))
            edge(prev, ip, layer="l3", media="wired", confidence="observed")
            prev = ip
        if wan_gateway:
            wan_gateways.add(wan_gateway)

    primary_gw = None
    if wan_gateways:
        node("internet", label="Internet", kind="internet", status="up")
        for gw in wan_gateways:
            node(gw, kind="wan-gateway")
            edge(gw, "internet", layer="l3", media="wired", confidence="observed")
        primary_gw = sorted(wan_gateways)[0]
    # Hang each subnet under the gateway (or the probe if no gateway is known).
    for cidr in list(subnets):
        parent = primary_gw if (primary_gw and primary_gw in nodes) else "self"
        edge(parent, "subnet:" + cidr, layer="l3", media="wired", confidence="inferred")

    # --- Layer-1 wired neighbours from LLDP ---------------------------------
    for nb in lldp_state:
        ip = (nb.get("mgmt_ip") or "").strip()
        sysname = (nb.get("system") or "").strip()
        port = nb.get("local_port") or ""
        if not (ip or sysname):
            continue
        nid = ip or ("lldp:" + (sysname or port))
        node(nid, label=sysname or ip or port, kind="neighbour",
             ips=[ip] if ip else [], status=status_for(ip) if ip else "up",
             detail={"lldp_port": port, "port_id": nb.get("port_id"), "vlan": nb.get("vlan")})
        if ip:
            attach_host(nid, ip)
        edge("self", nid, layer="l1", media="wired", confidence="observed", via=port)

    # --- ARP / discovery hosts ----------------------------------------------
    try:
        hosts = history.get_hosts(500)
    except Exception:
        hosts = []
    for h in hosts:
        ip = (h.get("address") or "").strip()
        if not ip:
            continue
        mac = (h.get("mac") or "").lower()
        if ip in own_ips:
            node("self", macs=[mac] if mac else [], vendor=h.get("vendor") or "")
            continue
        kind = "neighbour" if h.get("last_kind") == "lldp" else "host"
        node(ip, label=(h.get("name") or ip), kind=kind, ips=[ip], macs=[mac] if mac else [],
             vendor=h.get("vendor") or "", status=status_for(ip, h.get("last_seen")),
             detail={"sources": h.get("sources"), "last_seen": h.get("last_seen"),
                     "discovered": h.get("last_kind")})
        attach_host(ip, ip)

    # --- Wi-Fi APs the probe currently hears (RF neighbours) ----------------
    try:
        aps = history.get_ap_state(400)
    except Exception:
        aps = []
    for ap in aps:
        if not ap.get("present"):
            continue
        bssid = (ap.get("bssid") or "").lower()
        if not bssid:
            continue
        nid = "mac:" + bssid
        node(nid, label=ap.get("ssid") or "(hidden)", kind="ap", macs=[bssid], status="up",
             detail={"band": ap.get("band"), "channel": ap.get("channel"),
                     "signal": ap.get("signal"), "security": ap.get("security"), "bssid": bssid})
        edge("self", nid, layer="l1", media="wireless", confidence="observed", signal=ap.get("signal"))

    # --- remote collector observations (#36): weave each enabled collector's
    # pushed neighbour list in as collector-tagged nodes, rooted at a node for
    # the collector itself, so the scoped view can narrow to one collector.
    # A device already seen locally keeps its `local` tag (local sighting wins);
    # purely-remote devices carry the observing collector's id. ---------------
    try:
        remote_neigh = history.get_collector_neighbours()
    except Exception:
        remote_neigh = []
    collector_names: dict[str, str] = {}
    try:
        for c in history.list_collectors():
            collector_names[c["collector_id"]] = c.get("name") or c["collector_id"]
    except Exception:
        pass
    seen_collectors: set[str] = set()
    for obs in remote_neigh:
        cid = obs["collector_id"]
        cnode = "collector:" + cid
        if cid not in seen_collectors:
            node(cnode, label=collector_names.get(cid, cid), kind="collector",
                 status="up", collector=cid, detail={"collector_id": cid})
            seen_collectors.add(cid)
        ip = obs["ip"]
        existed = ip in nodes
        n = node(ip, label=ip, ips=[ip], macs=[obs["mac"]] if obs["mac"] else [],
                 subnet=_map_subnet_of(ip, own_subnets),
                 status=status_for(ip, obs.get("ts")),
                 detail={"neigh_state": obs["state"], "observed_by": cid})
        if not existed:  # local sighting wins; only tag purely-remote nodes
            n["collector"] = cid
        edge(cnode, ip, layer="l3", media="wired", confidence="inferred", via="collector " + cid)

    # --- enrich monitored nodes + finalise subnet counts --------------------
    for ip, st in monitor_status.items():
        if ip in nodes:
            nodes[ip]["status"] = "up" if st["up"] else "down"
            nodes[ip]["detail"].update({"loss_pct": st["loss_pct"], "rtt_ms": st["rtt_ms"]})

    # --- device classification (#39): infer a kind for still-generic nodes,
    # then let an operator's manual tag override everything. -----------------
    gw_ips = set(wan_gateways)
    for nid, n in nodes.items():
        proposal = classify.classify(
            current_kind=n.get("kind", "unknown"),
            vendor=n.get("vendor", ""),
            hostname=n.get("label", "") if n.get("label") != nid else "",
            services=n.get("detail", {}).get("services"),
            sys_descr=n.get("detail", {}).get("snmp_descr", ""),
            is_gateway=nid in gw_ips,
            is_ap=n.get("kind") == "ap",
        )
        if proposal:
            if _KIND_RANK.get(proposal["kind"], 0) > _KIND_RANK.get(n["kind"], 0):
                n["kind"] = proposal["kind"]
            n["detail"]["class_source"] = proposal["source"]
            n["detail"]["class_reason"] = proposal["reason"]

    tags = settings_store.get_device_tags()
    for nid, tag in tags.items():
        n = nodes.get(nid)
        if n is None:
            continue
        if tag.get("kind"):
            n["kind"] = tag["kind"]
        if tag.get("label"):
            n["label"] = tag["label"]
        n["confidence"] = "confirmed"
        n["tagged"] = True
        if tag.get("notes"):
            n["detail"]["notes"] = tag["notes"]
        if tag.get("tags"):
            n["detail"]["tags"] = tag["tags"]

    # --- collector scope (#36): the full graph unions every collector; a
    # ?collector=<id> narrows it to one node's observations. `self`/`internet`
    # are shared anchors and always survive so a scoped map is never rootless. ---
    all_collectors = sorted({n.get("collector") or "local" for n in nodes.values()})
    scope = (request.args.get("collector") or "").strip()
    if scope and scope not in ("all", ""):
        _ANCHORS = {"self", "internet"}
        keep = {nid for nid, n in nodes.items()
                if nid in _ANCHORS or (n.get("collector") or "local") == scope}
        nodes = {nid: n for nid, n in nodes.items() if nid in keep}
        edges = {k: e for k, e in edges.items() if e["from"] in keep and e["to"] in keep}

    for cidr, meta in subnets.items():
        meta["count"] = sum(1 for n in nodes.values() if n.get("subnet") == cidr)

    return jsonify({
        "updated": now,
        "collector": "local",
        "scope": scope or "all",
        "collectors": all_collectors,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "subnets": [m for m in subnets.values() if m.get("count")],
        "wan_gateways": sorted(wan_gateways),
        "interfaces": iface_detail,
    })


@app.get("/api/map/tags")
def map_tags_list():
    """All operator device tags (manual map classifications), plus the kinds a
    tag may use so the UI can offer a fixed picker."""
    return jsonify(tags=settings_store.get_device_tags(),
                   kinds=sorted(settings_store.TAG_KINDS))


@app.put("/api/map/tags/<path:node_id>")
def map_tag_set(node_id: str):
    """Create or update one node's manual tag. Any subset of kind/label/notes/
    tags may be given; clearing every field removes the tag."""
    payload = request.get_json(silent=True) or {}
    raw_tags = payload.get("tags")
    if isinstance(raw_tags, str):
        raw_tags = [t for t in re.split(r"[,\s]+", raw_tags) if t]
    try:
        entry = settings_store.set_device_tag(
            node_id,
            kind=str(payload.get("kind", "")),
            label=str(payload.get("label", "")),
            notes=str(payload.get("notes", "")),
            tags=raw_tags if isinstance(raw_tags, list) else None,
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    history.record_audit("device_tag.set", user=_session_user() or "-",
                         target=node_id,
                         detail=f"kind={entry.get('kind', '')} label={entry.get('label', '')}")
    return jsonify(node_id=node_id, tag=entry)


@app.delete("/api/map/tags/<path:node_id>")
def map_tag_delete(node_id: str):
    """Remove one node's manual tag (revert to the inferred classification)."""
    ok = settings_store.delete_device_tag(node_id)
    if ok:
        history.record_audit("device_tag.delete", user=_session_user() or "-",
                             target=node_id)
    return jsonify(ok=ok)


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


def _poll_lldp_once() -> None:
    lldpctl = _lldpctl_path()
    if not lldpctl:
        return
    code, output = run([lldpctl, "-f", "json"], 8)
    if code != 0 or not output.strip():
        return
    try:
        data = json.loads(output)
    except ValueError:
        return
    neighbors = _parse_lldp(data)
    if neighbors:
        history.record_lldp(neighbors)
        for n in neighbors:
            if n.get("mgmt_ip") and valid_ip(n["mgmt_ip"]):
                history.record_host(n["mgmt_ip"], name=n.get("system", ""), source="lldp", kind="lldp")


def _poll_ap_once() -> dict | None:
    """Scan the RF neighbourhood and diff it against the stored AP inventory so a
    BSSID that stops beaconing is logged as 'disappeared'. Unprivileged nmcli;
    returns None when there is no radio to scan (kept honest - a blocked radio
    yields an empty scan, which record_ap_scan ignores rather than treating as a
    mass disappearance)."""
    wireless = _wireless_interfaces()
    if not wireless:
        return None
    command = [os.environ.get("PROBE_PYTHON", sys.executable), str(ROOT / "monitor" / "wifi_survey.py"),
               "--iface", wireless[0], "--rescan"]
    code, output = run(command, 40)
    if code != 0 or not output.strip():
        return None
    try:
        data = json.loads(output)
    except ValueError:
        return None
    return history.record_ap_scan(data.get("aps") or [])


def _background_poller() -> None:
    lldp_interval = max(30, int(os.environ.get("PROBE_LLDP_POLL_SECONDS", "120")))
    next_lldp = 0.0
    next_ap = 0.0
    while True:
        now = time.monotonic()
        if now >= next_lldp:
            try:
                _poll_lldp_once()
            except Exception:  # a poll failure must never kill the loop
                pass
            next_lldp = time.monotonic() + lldp_interval
        ap_cfg = monitor_config.load().get("ap_monitor", {})
        ap_interval = max(20, int(ap_cfg.get("interval", 60)))
        if ap_cfg.get("enabled", True) and now >= next_ap:
            try:
                _poll_ap_once()
            except Exception:
                pass
            next_ap = time.monotonic() + ap_interval
        elif not ap_cfg.get("enabled", True):
            next_ap = now + ap_interval  # skip a cycle; re-check config later
        time.sleep(5)


def _start_background_poller() -> None:
    if os.environ.get("PROBE_DISABLE_POLLER"):
        return
    # Supervised: if the outer loop ever throws (config load, parsing, …) it is
    # logged and respawned with backoff rather than dying for the process life.
    supervise("lldp-poller", _background_poller, restart=True)
    supervise("alert-poller", _alert_poller, restart=True)


# Start the continuous-inventory poller when served under waitress (module
# import) as well as the dev server. Guard so it starts once per process.
if not getattr(app, "_poller_started", False):
    app._poller_started = True  # type: ignore[attr-defined]
    _start_background_poller()


if __name__ == "__main__":
    app.run(host=os.environ.get("PROBE_BIND", "127.0.0.1"), port=int(os.environ.get("PROBE_PORT", "8088")), debug=False)
