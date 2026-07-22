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

DB_PATH = Path(os.environ.get("PROBE_MONITOR_DB", "/var/lib/network-probe/monitor.db"))
TARGET_FILE = Path(os.environ.get("PROBE_MONITOR_TARGETS", "/etc/network-probe/monitor-targets.csv"))
SNAPSHOT_IFACE = os.environ.get("PROBE_MONITOR_SNAPSHOT_IFACE", "")  # e.g. enp0s31f6
SNAPSHOT_SECONDS = int(os.environ.get("PROBE_MONITOR_SNAPSHOT_SECONDS", "15"))
FAIL_THRESHOLD = int(os.environ.get("PROBE_MONITOR_FAIL_THRESHOLD", "3"))
RECOVER_THRESHOLD = int(os.environ.get("PROBE_MONITOR_RECOVER_THRESHOLD", "5"))
WIFI_INTERVAL = 5.0

PING_LINE = re.compile(r"icmp_seq=(\d+)(?:.*time=([\d.]+) ms)?")
NO_ANSWER = re.compile(r"no answer yet for icmp_seq=(\d+)")

stop_event = threading.Event()


def load_targets() -> list[dict]:
    """monitor-targets.csv: name,address,interface,group
    interface may be empty (default route). group is one of
    wifi-gateway, eth-gateway, internal, external, ap, custom."""
    rows: list[dict] = []
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
        while not stop_event.is_set():
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
                if stop_event.is_set():
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
            if not stop_event.is_set():
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
        print(f"No targets in {TARGET_FILE}; nothing to monitor.", file=sys.stderr)
        return 2
    db = open_db()
    # Close events left open by a previous run; their true end is unknown.
    db.execute(
        "UPDATE events SET ended = ?, kind = COALESCE(kind, '') || ' [closed on monitor restart]' WHERE ended IS NULL",
        (time.time(),),
    )
    db.commit()
    queue: collections.deque = collections.deque()
    workers = [PingWorker(target, queue) for target in targets]
    target_groups = {t["name"]: t["group"] for t in targets}
    for worker in workers:
        worker.start()
    print(f"Monitoring {len(workers)} targets -> {DB_PATH}")

    wifi_ifaces = [p.name for p in Path("/sys/class/net").iterdir() if (p / "wireless").exists()] \
        if Path("/sys/class/net").exists() else []

    def handle_signal(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    open_event_id: int | None = None
    event_failed: set[str] = set()
    snapshot_results: collections.deque = collections.deque()
    last_wifi = 0.0
    last_flush = 0.0

    while not stop_event.is_set():
        stop_event.wait(1.0)
        now = time.time()

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
        down_now = {worker.target["name"] for worker in workers if worker.down}
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

    for worker in workers:
        worker.terminate()
    db.commit()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
