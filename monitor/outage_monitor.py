"""Continuous outage monitor for the network probe.

Purpose: record, second by second, whether each configured path is alive, so
that intermittent outages ("Wi-Fi associated but traffic drops", "internal
network dead for 1-2 minutes while 1.1.1.1 still answers") get a precise
timeline, a classification, and - when possible - the client that caused them.

Design:
- One long-running `ping -O` process per (target, interface) pair. `-O` prints
  a line for missed replies too, so every second yields a definitive up/down
  sample without spawning processes in a loop.
- Wi-Fi link stats (signal, bitrate, tx retries/failures) sampled every 5 s
  from `iw`, plus /sys/class/net drop/error counters for every interface.
- Samples land in SQLite (WAL mode). Aggregation to 1 s rows per target.
- Outage events: a target is "down" after FAIL_THRESHOLD consecutive misses,
  "up" again after RECOVER_THRESHOLD consecutive replies. Overlapping per-
  target downtimes merge into one event which is classified on close.
- On event start a broadcast/top-talker snapshot runs on the capture
  interface (tshark, 15 s): broadcast storms from a single client keep
  flowing while unicast is dead, so the snapshot frequently names the culprit.

The daemon needs no root; packet snapshots need membership in the
`wireshark` group (dumpcap capabilities).
"""
from __future__ import annotations

import collections
import csv
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probes  # noqa: E402 - local module beside this file

DB_PATH = Path(os.environ.get("PROBE_MONITOR_DB", "/var/lib/network-probe/monitor.db"))
TARGET_FILE = Path(os.environ.get("PROBE_MONITOR_TARGETS", "/etc/network-probe/monitor-targets.csv"))
SERVICE_FILE = Path(os.environ.get("PROBE_MONITOR_SERVICES", "/etc/network-probe/monitor-services.csv"))
PORT_FILE = Path(os.environ.get("PROBE_MONITOR_PORTS", "/etc/network-probe/monitor-ports.csv"))
# Dashboard-editable JSON config in the shared state dir. When it exists it is
# authoritative for targets/services/ports (each defaulting to empty) and the
# /etc CSVs are ignored; when absent, the legacy CSVs are used. See
# dashboard/monitor_config.py. Targets are re-read live (TARGET_RELOAD_INTERVAL)
# so web edits apply without a privileged restart.
CONFIG_JSON = Path(os.environ.get("PROBE_MONITOR_CONFIG", "/var/lib/network-probe/monitor-config.json"))
TARGET_RELOAD_INTERVAL = int(os.environ.get("PROBE_MONITOR_TARGET_RELOAD", "15"))
SERVICE_INTERVAL = int(os.environ.get("PROBE_MONITOR_SERVICE_INTERVAL", "60"))
PORT_INTERVAL = int(os.environ.get("PROBE_MONITOR_PORT_INTERVAL", "60"))
ROUTE_INTERVAL = int(os.environ.get("PROBE_MONITOR_ROUTE_INTERVAL", "300"))
SNAPSHOT_IFACE = os.environ.get("PROBE_MONITOR_SNAPSHOT_IFACE", "")  # e.g. enp0s31f6
SNAPSHOT_SECONDS = int(os.environ.get("PROBE_MONITOR_SNAPSHOT_SECONDS", "15"))
FAIL_THRESHOLD = int(os.environ.get("PROBE_MONITOR_FAIL_THRESHOLD", "3"))
RECOVER_THRESHOLD = int(os.environ.get("PROBE_MONITOR_RECOVER_THRESHOLD", "5"))
WIFI_INTERVAL = 5.0

PING_LINE = re.compile(r"icmp_seq=(\d+)(?:.*time=([\d.]+) ms)?")
NO_ANSWER = re.compile(r"no answer yet for icmp_seq=(\d+)")

stop_event = threading.Event()


def _json_config() -> dict | None:
    """The dashboard-editable JSON config, or None when it does not exist (so
    the caller falls back to the legacy /etc CSVs)."""
    if not CONFIG_JSON.is_file():
        return None
    try:
        data = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_targets() -> list[dict]:
    """Targets to ping. From the JSON config when present, else
    monitor-targets.csv (name,address,interface,group). interface may be empty
    (default route). group is one of wifi-gateway, eth-gateway, internal,
    external, ap, custom."""
    config = _json_config()
    if config is not None:
        rows = []
        for item in config.get("targets", []) or []:
            if not isinstance(item, dict) or item.get("enabled") is False or item.get("started") is False:
                continue  # disabled from the dashboard: skip so its worker stops
            name, address = str(item.get("name", "")).strip(), str(item.get("address", "")).strip()
            if name and address:
                rows.append({"name": name, "address": address,
                             "interface": str(item.get("interface", "")).strip(),
                             "group": str(item.get("group", "")).strip() or "custom"})
        return rows
    rows = []
    if not TARGET_FILE.is_file():
        return rows
    with TARGET_FILE.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(line for line in handle if line.strip() and not line.lstrip().startswith("#")):
            if len(row) != 4:
                continue
            name, address, interface, group = (value.strip() for value in row)
            if name and address:
                rows.append({"name": name, "address": address, "interface": interface, "group": group or "custom"})
    return rows


def open_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS ping_samples (
            ts REAL NOT NULL,
            target TEXT NOT NULL,
            ok INTEGER NOT NULL,
            rtt_ms REAL
        );
        CREATE INDEX IF NOT EXISTS idx_ping_ts ON ping_samples (ts);
        CREATE INDEX IF NOT EXISTS idx_ping_target_ts ON ping_samples (target, ts);
        CREATE TABLE IF NOT EXISTS wifi_samples (
            ts REAL NOT NULL,
            interface TEXT NOT NULL,
            connected INTEGER NOT NULL,
            ssid TEXT,
            bssid TEXT,
            freq_mhz INTEGER,
            signal_dbm INTEGER,
            tx_bitrate_mbps REAL,
            rx_bitrate_mbps REAL,
            tx_retries INTEGER,
            tx_failed INTEGER,
            beacon_loss INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_wifi_ts ON wifi_samples (ts);
        CREATE TABLE IF NOT EXISTS iface_samples (
            ts REAL NOT NULL,
            interface TEXT NOT NULL,
            rx_packets INTEGER, rx_dropped INTEGER, rx_errors INTEGER,
            tx_packets INTEGER, tx_dropped INTEGER, tx_errors INTEGER,
            multicast INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_iface_ts ON iface_samples (ts);
        CREATE TABLE IF NOT EXISTS service_samples (
            ts REAL NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            ok INTEGER NOT NULL,
            duration_ms REAL,
            detail TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_service_ts ON service_samples (ts);
        CREATE INDEX IF NOT EXISTS idx_service_name_ts ON service_samples (name, ts);
        CREATE TABLE IF NOT EXISTS route_state (
            name TEXT PRIMARY KEY,
            hops TEXT,
            updated REAL
        );
        CREATE TABLE IF NOT EXISTS route_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            name TEXT NOT NULL,
            old_hops TEXT,
            new_hops TEXT
        );
        -- Latest per-hop quality (mtr) for each traced target: a JSON list of
        -- hubs [{idx,host,loss,snt,last,avg,best,wrst,stdev}], overwritten each
        -- cycle. Feeds the per-hop cards on the topology map.
        CREATE TABLE IF NOT EXISTS route_metrics (
            name TEXT PRIMARY KEY,
            hubs TEXT,
            updated REAL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started REAL NOT NULL,
            ended REAL,
            kind TEXT,
            failed_targets TEXT,
            snapshot TEXT
        );
        """
    )
    return db


class PingWorker(threading.Thread):
    """Owns one long-running `ping -O` process and reports 1 s samples."""

    def __init__(self, target: dict, queue: collections.deque):
        super().__init__(daemon=True, name=f"ping-{target['name']}")
        self.target = target
        self.queue = queue
        self.consecutive_fail = 0
        self.consecutive_ok = 0
        self.down = False
        self.proc: subprocess.Popen | None = None
        self._stopped = threading.Event()  # per-worker stop (target removed via config)

    def should_stop(self) -> bool:
        return stop_event.is_set() or self._stopped.is_set()

    def build_command(self) -> list[str]:
        command = ["ping", "-n", "-O", "-i", "1", "-W", "1"]
        if self.target["interface"]:
            command += ["-I", self.target["interface"]]
        command += ["--", self.target["address"]]
        return command

    def interface_down(self) -> bool:
        """True when the bound interface exists but has no carrier: the path is
        not in service (e.g. Wi-Fi not connected), so we pause instead of
        recording a permanent outage. Real 'associated but dropping' failures
        keep operstate up and are still recorded."""
        name = self.target["interface"]
        if not name:
            return False
        state_file = Path("/sys/class/net") / name / "operstate"
        try:
            return state_file.read_text().strip() != "up"
        except OSError:
            return True

    def run(self) -> None:
        while not self.should_stop():
            if self.interface_down():
                self.down = False
                self.consecutive_fail = 0
                stop_event.wait(5)
                continue
            try:
                self.proc = subprocess.Popen(
                    self.build_command(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
                )
            except OSError as exc:
                self.record(time.time(), False, None)
                stop_event.wait(5)
                continue
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                if self.should_stop():
                    break
                now = time.time()
                if NO_ANSWER.search(line):
                    self.record(now, False, None)
                    continue
                match = PING_LINE.search(line)
                if match and match.group(2) is not None:
                    self.record(now, True, float(match.group(2)))
                elif match:
                    self.record(now, False, None)
            self.proc.wait()
            if not self.should_stop():
                # ping exits when the interface disappears or resolution fails;
                # count the gap as loss and retry.
                self.record(time.time(), False, None)
                stop_event.wait(3)

    def record(self, ts: float, ok: bool, rtt: float | None) -> None:
        if ok:
            self.consecutive_ok += 1
            self.consecutive_fail = 0
            if self.down and self.consecutive_ok >= RECOVER_THRESHOLD:
                self.down = False
        else:
            if self.interface_down():
                self.down = False
                self.consecutive_fail = 0
                self.consecutive_ok = 0
                return
            self.consecutive_fail += 1
            self.consecutive_ok = 0
            if not self.down and self.consecutive_fail >= FAIL_THRESHOLD:
                self.down = True
        self.queue.append((ts, self.target["name"], int(ok), rtt))

    def terminate(self) -> None:
        self._stopped.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def wifi_sample(interface: str) -> tuple | None:
    try:
        link = subprocess.run(["iw", "dev", interface, "link"], capture_output=True, text=True, timeout=4).stdout
        station = subprocess.run(["iw", "dev", interface, "station", "dump"], capture_output=True, text=True, timeout=4).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    now = time.time()
    if "Connected to" not in link:
        return (now, interface, 0, None, None, None, None, None, None, None, None, None)

    def find(pattern: str, text: str, cast=str):
        match = re.search(pattern, text)
        return cast(match.group(1)) if match else None

    return (
        now, interface, 1,
        find(r"SSID: (.+)", link),
        find(r"Connected to ([0-9a-f:]+)", link),
        find(r"freq: (\d+)", link, int),
        find(r"signal: (-?\d+)", station, int),
        find(r"tx bitrate:\s+([\d.]+)", station, float),
        find(r"rx bitrate:\s+([\d.]+)", station, float),
        find(r"tx retries:\s+(\d+)", station, int),
        find(r"tx failed:\s+(\d+)", station, int),
        find(r"beacon loss:\s+(\d+)", station, int),
    )


def iface_counters() -> list[tuple]:
    rows = []
    now = time.time()
    root = Path("/sys/class/net")
    if not root.exists():
        return rows
    for item in sorted(root.iterdir()):
        if item.name == "lo":
            continue
        def read(name: str) -> int:
            try:
                return int((item / "statistics" / name).read_text())
            except (OSError, ValueError):
                return 0
        rows.append((now, item.name, read("rx_packets"), read("rx_dropped"), read("rx_errors"),
                     read("tx_packets"), read("tx_dropped"), read("tx_errors"), read("multicast")))
    return rows


def broadcast_snapshot(interface: str, seconds: int) -> str:
    """Capture broadcast/multicast senders during an outage; returns a report."""
    if not interface or not shutil.which("tshark"):
        return "snapshot disabled (no interface configured or tshark missing)"
    command = [
        "tshark", "-i", interface, "-a", f"duration:{seconds}", "-l", "-n",
        "-Y", "eth.dst.ig == 1", "-T", "fields", "-e", "eth.src", "-e", "_ws.col.protocol",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=seconds + 30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"snapshot failed: {exc}"
    if result.returncode not in (0,) and not result.stdout:
        return f"snapshot failed: {result.stderr[-500:]}"
    counter: collections.Counter = collections.Counter()
    proto_counter: collections.Counter = collections.Counter()
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if parts and parts[0]:
            counter[parts[0]] += 1
            if len(parts) > 1:
                proto_counter[(parts[0], parts[1])] += 1
    total = sum(counter.values())
    lines = [f"broadcast/multicast frames in {seconds}s on {interface}: {total} ({total / seconds:.0f}/s)"]
    for mac, count in counter.most_common(10):
        protos = ", ".join(f"{proto} x{n}" for (m, proto), n in proto_counter.most_common() if m == mac)[:120]
        lines.append(f"  {mac}  {count} frames ({count / seconds:.0f}/s)  {protos}")
    return "\n".join(lines)


def load_services() -> list[dict]:
    """monitor-services.csv: name,kind,target
    kind dns  -> target "hostname@resolver-ip" (resolver optional)
    kind http -> target URL (http/https; https also times the TLS handshake)
    kind tcp  -> target "host:port"
    kind ntp  -> target "chrony" (reads chronyc tracking offset)"""
    config = _json_config()
    if config is not None:
        rows = []
        for item in config.get("services", []) or []:
            if not isinstance(item, dict) or item.get("enabled") is False or item.get("started") is False:
                continue  # disabled from the dashboard
            name, kind, target = (str(item.get(k, "")).strip() for k in ("name", "kind", "target"))
            if name and kind in {"dns", "http", "tcp", "ntp"} and target:
                rows.append({"name": name, "kind": kind, "target": target})
        return rows
    rows: list[dict] = []
    if not SERVICE_FILE.is_file():
        return rows
    with SERVICE_FILE.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(line for line in handle if line.strip() and not line.lstrip().startswith("#")):
            if len(row) != 3:
                continue
            name, kind, target = (value.strip() for value in row)
            if name and kind in {"dns", "http", "tcp", "ntp"} and target:
                rows.append({"name": name, "kind": kind, "target": target})
    return rows


def load_ports() -> list[dict]:
    """monitor-ports.csv: name,host,port,proto,send,expect
    proto (tcp/udp), send and expect are optional; well-known ports supply a
    default probe and expected response when send/expect are blank."""
    config = _json_config()
    if config is not None:
        rows = []
        for item in config.get("ports", []) or []:
            if not isinstance(item, dict) or item.get("enabled") is False or item.get("started") is False:
                continue  # disabled from the dashboard
            name, host = str(item.get("name", "")).strip(), str(item.get("host", "")).strip()
            try:
                port = int(item.get("port"))
            except (TypeError, ValueError):
                continue
            if not (name and host and 0 < port < 65536):
                continue
            send = str(item.get("send", "")).strip()
            expect = str(item.get("expect", "")).strip()
            rows.append({
                "name": name, "host": host, "port": port,
                "proto": (str(item.get("proto", "")).strip() or "tcp"),
                "send": send.encode("utf-8").decode("unicode_escape").encode("latin-1") if send else None,
                "expect": expect or None,
            })
        return rows
    rows: list[dict] = []
    if not PORT_FILE.is_file():
        return rows
    with PORT_FILE.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(line for line in handle if line.strip() and not line.lstrip().startswith("#")):
            if len(row) < 3:
                continue
            row = (row + ["", "", ""])[:6]
            name, host, port_text, proto, send, expect = (value.strip() for value in row)
            if not (name and host and port_text.isdigit()):
                continue
            rows.append({
                "name": name, "host": host, "port": int(port_text),
                "proto": proto or "tcp",
                "send": send.encode("utf-8").decode("unicode_escape").encode("latin-1") if send else None,
                "expect": expect if expect else None,
            })
    return rows


def port_check_loop(results: collections.deque) -> None:
    """Probe configured ports every PORT_INTERVAL seconds and record the
    result (ok, response time, matched/expected detail) into service_samples."""
    while not stop_event.is_set():
        for port in load_ports():
            if stop_event.is_set():
                return
            spec = probes.spec_for(
                port["port"], port["send"], port["expect"],
                udp=(port["proto"] == "udp"), tls=False,
            )
            ok, duration, detail = probes.run_probe(port["host"], port["port"], spec)
            kind = f"port/{spec.label}"
            results.append(("service", (time.time(), port["name"], kind[:40], int(ok), duration, detail)))
        stop_event.wait(PORT_INTERVAL)


def check_dns(target: str) -> tuple[bool, float | None, str]:
    host, _, resolver = target.partition("@")
    command = ["dig", "+tries=1", "+time=2", "+noall", "+answer", "+stats", host]
    if resolver:
        command.append(f"@{resolver}")
    started = time.monotonic()
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, None, str(exc)
    elapsed = (time.monotonic() - started) * 1000
    match = re.search(r"Query time: (\d+) msec", result.stdout)
    answered = bool(re.search(r"\bIN\s+(A|AAAA|CNAME)\b", result.stdout))
    if result.returncode != 0 or not answered:
        return False, None, (result.stdout + result.stderr)[-200:].strip() or "no answer"
    return True, float(match.group(1)) if match else round(elapsed, 1), ""


def check_http(target: str) -> tuple[bool, float | None, str]:
    import http.client
    import ssl
    import urllib.parse

    url = urllib.parse.urlsplit(target)
    if url.scheme not in {"http", "https"} or not url.hostname:
        return False, None, "invalid URL"
    port = url.port or (443 if url.scheme == "https" else 80)
    timings: dict[str, float] = {}
    try:
        started = time.monotonic()
        import socket as socket_module
        raw = socket_module.create_connection((url.hostname, port), timeout=5)
        timings["connect"] = (time.monotonic() - started) * 1000
        if url.scheme == "https":
            tls_started = time.monotonic()
            raw = ssl.create_default_context().wrap_socket(raw, server_hostname=url.hostname)
            timings["tls"] = (time.monotonic() - tls_started) * 1000
        connection = http.client.HTTPConnection(url.hostname, port, timeout=5)
        connection.sock = raw
        request_started = time.monotonic()
        connection.request("GET", url.path or "/", headers={"Host": url.hostname, "User-Agent": "network-probe-monitor"})
        response = connection.getresponse()
        response.read(4096)
        timings["response"] = (time.monotonic() - request_started) * 1000
        total = (time.monotonic() - started) * 1000
        connection.close()
        detail = " ".join(f"{key}={value:.0f}ms" for key, value in timings.items()) + f" status={response.status}"
        return response.status < 500, round(total, 1), detail
    except Exception as exc:  # noqa: BLE001 - any network/TLS failure is a legitimate DOWN sample
        return False, None, f"{type(exc).__name__}: {exc}"[:200]


def check_tcp(target: str) -> tuple[bool, float | None, str]:
    import socket as socket_module

    host, _, port_text = target.rpartition(":")
    if not host or not port_text.isdigit():
        return False, None, "target must be host:port"
    started = time.monotonic()
    try:
        socket_module.create_connection((host, int(port_text)), timeout=5).close()
        return True, round((time.monotonic() - started) * 1000, 1), ""
    except OSError as exc:
        return False, None, str(exc)[:200]


def check_ntp(_target: str) -> tuple[bool, float | None, str]:
    try:
        result = subprocess.run(["chronyc", "-c", "tracking"], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, None, str(exc)
    fields = result.stdout.strip().split(",")
    if result.returncode != 0 or len(fields) < 6:
        return False, None, (result.stdout + result.stderr)[-200:].strip()
    try:
        offset_ms = float(fields[4]) * 1000
        stratum = int(fields[2])
    except ValueError:
        return False, None, result.stdout[:200]
    synced = stratum > 0 and stratum < 16 and abs(offset_ms) < 100
    return synced, round(abs(offset_ms), 3), f"stratum={stratum} offset={offset_ms:.3f}ms"


SERVICE_CHECKS = {"dns": check_dns, "http": check_http, "tcp": check_tcp, "ntp": check_ntp}


def service_check_loop(results: collections.deque) -> None:
    """Runs every SERVICE_INTERVAL seconds; sequential and low-rate on purpose."""
    while not stop_event.is_set():
        for service in load_services():
            if stop_event.is_set():
                return
            ok, duration, detail = SERVICE_CHECKS[service["kind"]](service["target"])
            results.append(("service", (time.time(), service["name"], service["kind"], int(ok), duration, detail)))
        stop_event.wait(SERVICE_INTERVAL)


ROUTE_MTR_CYCLES = 5  # probes per hop -> loss%/jitter (StDev) sample size


def route_probe(address: str, interface: str = "") -> tuple[str, list[dict]]:
    """Trace to `address` with mtr and return (hop_chain, hubs). hop_chain is the
    deduped `>`-joined IP sequence used for route-change detection; hubs is the
    per-hop quality list (idx, host, loss, snt, last, avg, best, wrst, stdev).
    A non-responding hop keeps its slot with host '*' and null timings.
    When `interface` is set the probe is sourced from that adapter (mtr -I),
    matching the ping worker's per-target adapter binding."""
    command = ["mtr", "-n", "-j", "-c", str(ROUTE_MTR_CYCLES), "-m", "12"]
    if interface:
        command += ["-I", interface]
    command += ["--", address]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return "", []
    try:
        raw = json.loads(result.stdout)["report"]["hubs"]
    except (ValueError, KeyError, TypeError):
        return "", []
    hubs = []
    for hub in raw:
        host = str(hub.get("host") or "").strip()
        responded = host not in ("", "???")
        hubs.append({
            "idx": hub.get("count"),
            "host": host if responded else "*",
            "loss": hub.get("Loss%"),
            "snt": hub.get("Snt"),
            "last": hub.get("Last"),
            "avg": hub.get("Avg"),
            "best": hub.get("Best"),
            "wrst": hub.get("Wrst"),
            "stdev": hub.get("StDev"),
        })
    chain = ">".join(dict.fromkeys(h["host"] for h in hubs if h["host"] != "*"))
    return chain, hubs


def route_check_loop(results: collections.deque) -> None:
    """Tracks the hop sequence to external/internal references; a changed
    sequence is recorded as a route event (path failover, new gateway). Targets
    are re-read each cycle so dashboard edits are honoured live."""
    seen: dict[str, str] = {}
    try:  # survive restarts: compare against the last known route
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as ro_db:
            seen = dict(ro_db.execute("SELECT name, hops FROM route_state"))
    except sqlite3.Error:
        pass
    while not stop_event.is_set():
        watch = [t for t in load_targets()
                 if t["group"] in {"external", "internal"} and not t["interface"].startswith("wl")]
        for target in watch:
            if stop_event.is_set():
                return
            hops, hubs = route_probe(target["address"], target.get("interface", ""))
            if not hops:
                continue
            now = time.time()
            # Fresh per-hop quality every cycle (latency/jitter/loss always move).
            results.append(("route-metrics", (now, target["name"], json.dumps(hubs))))
            previous = seen.get(target["name"])
            if previous is not None and previous != hops:
                results.append(("route-change", (now, target["name"], previous, hops)))
            elif previous is None:
                results.append(("route-init", (now, target["name"], None, hops)))
            seen[target["name"]] = hops
        stop_event.wait(ROUTE_INTERVAL)


def classify(failed: set[str], target_groups: dict[str, str]) -> str:
    groups = {target_groups.get(name, "custom") for name in failed}
    has = groups.__contains__
    if has("wifi-gateway") and not has("eth-gateway") and not has("internal"):
        return "wifi-only"
    if has("internal") and has("external"):
        return "total-outage"
    if has("internal") and not has("external"):
        return "internal-only (internet still reachable)"
    if has("external") and not has("internal") and not has("wifi-gateway"):
        return "upstream/internet-only"
    if has("eth-gateway") and has("wifi-gateway"):
        return "gateway unreachable on both paths"
    return "partial: " + ", ".join(sorted(groups))


def main() -> int:
    targets = load_targets()
    if not targets:
        # Not fatal any more: the config may be empty because the operator has
        # not added targets via the dashboard yet. Idle and pick them up live.
        print(f"No targets configured yet; waiting for config at {CONFIG_JSON} "
              f"or {TARGET_FILE}.", file=sys.stderr)
    db = open_db()
    # Close events left open by a previous run; their true end is unknown.
    db.execute(
        "UPDATE events SET ended = ?, kind = COALESCE(kind, '') || ' [closed on monitor restart]' WHERE ended IS NULL",
        (time.time(),),
    )
    db.commit()
    queue: collections.deque = collections.deque()
    workers: dict[str, PingWorker] = {}
    target_groups: dict[str, str] = {}

    def reconcile_targets() -> None:
        """Start workers for newly-added targets and stop removed ones, so a
        dashboard edit to monitor-config.json takes effect without a restart."""
        desired = {t["name"]: t for t in load_targets()}
        for name in list(workers):
            if name not in desired:
                workers.pop(name).terminate()
                target_groups.pop(name, None)
                print(f"target removed: {name}")
        for name, target in desired.items():
            existing = workers.get(name)
            if existing is None:
                worker = PingWorker(target, queue)
                workers[name] = worker
                target_groups[name] = target["group"]
                worker.start()
                print(f"target added: {name} -> {target['address']}")
            elif existing.target != target:
                # address/interface/group changed: replace the worker.
                existing.terminate()
                worker = PingWorker(target, queue)
                workers[name] = worker
                target_groups[name] = target["group"]
                worker.start()
                print(f"target updated: {name} -> {target['address']}")

    reconcile_targets()
    print(f"Monitoring {len(workers)} targets -> {DB_PATH}")

    wifi_ifaces = [p.name for p in Path("/sys/class/net").iterdir() if (p / "wireless").exists()] \
        if Path("/sys/class/net").exists() else []

    aux_results: collections.deque = collections.deque()
    threading.Thread(target=service_check_loop, args=(aux_results,), daemon=True).start()
    threading.Thread(target=port_check_loop, args=(aux_results,), daemon=True).start()
    threading.Thread(target=route_check_loop, args=(aux_results,), daemon=True).start()

    def handle_signal(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    open_event_id: int | None = None
    event_failed: set[str] = set()
    snapshot_results: collections.deque = collections.deque()
    last_wifi = 0.0
    last_flush = 0.0
    last_target_reload = time.time()

    while not stop_event.is_set():
        stop_event.wait(1.0)
        now = time.time()

        # Pick up dashboard edits to the target list without a restart.
        if now - last_target_reload >= TARGET_RELOAD_INTERVAL:
            last_target_reload = now
            reconcile_targets()

        # flush ping samples
        batch = []
        while queue:
            batch.append(queue.popleft())
        if batch:
            db.executemany("INSERT INTO ping_samples (ts, target, ok, rtt_ms) VALUES (?, ?, ?, ?)", batch)

        # wifi + iface counters
        if now - last_wifi >= WIFI_INTERVAL:
            last_wifi = now
            for iface in wifi_ifaces:
                sample = wifi_sample(iface)
                if sample:
                    db.execute(
                        "INSERT INTO wifi_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", sample
                    )
            db.executemany(
                "INSERT INTO iface_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", iface_counters()
            )

        # event state machine
        down_now = {name for name, worker in workers.items() if worker.down}
        if down_now and open_event_id is None:
            cursor = db.execute(
                "INSERT INTO events (started, kind, failed_targets) VALUES (?, ?, ?)",
                (now, "open", json.dumps(sorted(down_now))),
            )
            open_event_id = cursor.lastrowid
            event_failed = set(down_now)
            print(f"OUTAGE start: {sorted(down_now)}")

            def snap(event_id: int) -> None:
                # The main loop's connection writes the report; a second
                # writer connection would starve against its transactions.
                snapshot_results.append((event_id, broadcast_snapshot(SNAPSHOT_IFACE, SNAPSHOT_SECONDS)))

            threading.Thread(target=snap, args=(open_event_id,), daemon=True).start()
        elif down_now and open_event_id is not None:
            if not down_now <= event_failed:
                event_failed |= down_now
                db.execute(
                    "UPDATE events SET failed_targets = ? WHERE id = ?",
                    (json.dumps(sorted(event_failed)), open_event_id),
                )
        elif not down_now and open_event_id is not None:
            kind = classify(event_failed, target_groups)
            db.execute(
                "UPDATE events SET ended = ?, kind = ? WHERE id = ?", (now, kind, open_event_id)
            )
            print(f"OUTAGE end ({kind}): {sorted(event_failed)}")
            open_event_id = None
            event_failed = set()

        while aux_results:
            kind, payload = aux_results.popleft()
            if kind == "service":
                db.execute("INSERT INTO service_samples VALUES (?, ?, ?, ?, ?, ?)", payload)
            elif kind == "route-metrics":
                ts, name, hubs_json = payload
                db.execute(
                    "INSERT INTO route_metrics (name, hubs, updated) VALUES (?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET hubs = excluded.hubs, updated = excluded.updated",
                    (name, hubs_json, ts),
                )
            elif kind in ("route-change", "route-init"):
                ts, name, old_hops, new_hops = payload
                if kind == "route-change":
                    db.execute("INSERT INTO route_events (ts, name, old_hops, new_hops) VALUES (?, ?, ?, ?)",
                               (ts, name, old_hops, new_hops))
                    print(f"ROUTE change for {name}: {old_hops} -> {new_hops}")
                db.execute(
                    "INSERT INTO route_state (name, hops, updated) VALUES (?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET hops = excluded.hops, updated = excluded.updated",
                    (name, new_hops, ts),
                )

        while snapshot_results:
            event_id, report = snapshot_results.popleft()
            db.execute("UPDATE events SET snapshot = ? WHERE id = ?", (report, event_id))

        if now - last_flush >= 5:
            last_flush = now
            db.commit()
            # retention: keep 14 days of raw samples
            horizon = now - 14 * 86400
            db.execute("DELETE FROM ping_samples WHERE ts < ?", (horizon,))
            db.execute("DELETE FROM wifi_samples WHERE ts < ?", (horizon,))
            db.execute("DELETE FROM iface_samples WHERE ts < ?", (horizon,))
            db.execute("DELETE FROM service_samples WHERE ts < ?", (horizon,))

    for worker in workers.values():
        worker.terminate()
    db.commit()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
