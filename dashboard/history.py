"""Web-writable history and asset inventory for the dashboard.

The outage monitor owns ``monitor.db`` (read-only to the web process). This is a
*separate* SQLite database the dashboard itself writes to, in the one state
directory the hardened unit allows it to write. It remembers:

- **hosts** - every address the probe has seen or scanned (discovery, SNMP,
  trace, reachability, LLDP mgmt IPs): vendor/name/MAC, first/last seen and
  which subsystems observed it. This is the "see everything you collect" store.
- **scans** - a durable log of every operator-initiated action and its result,
  so scan/performance history survives page reloads and service restarts.
- **jobs** - a persistent copy of the in-memory job registry (survives restart).
- **lldp inventory** - periodic neighbour snapshots plus a change log, giving
  the continuous LLDP/CDP inventory the roadmap asks for.

Everything is best-effort: a failure to record history never breaks a request.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

DB_FILE = Path(os.environ.get("PROBE_WEB_DB", "/var/lib/network-probe/probe-web.db"))
_lock = threading.Lock()
_initialised = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS hosts (
    address     TEXT PRIMARY KEY,
    mac         TEXT,
    vendor      TEXT,
    name        TEXT,
    first_seen  REAL,
    last_seen   REAL,
    sources     TEXT,          -- JSON list: discovery/snmp/trace/lldp/scan
    last_kind   TEXT,
    notes       TEXT
);
CREATE TABLE IF NOT EXISTS scans (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL,
    kind    TEXT,              -- reachability/trace/snmp/discovery/traffic/...
    target  TEXT,
    ok      INTEGER,
    summary TEXT,
    job_id  TEXT
);
CREATE INDEX IF NOT EXISTS idx_scans_ts ON scans(ts);
CREATE INDEX IF NOT EXISTS idx_scans_target ON scans(target);
CREATE TABLE IF NOT EXISTS jobs (
    id      TEXT PRIMARY KEY,
    kind    TEXT,
    state   TEXT,
    target  TEXT,
    started REAL,
    ended   REAL,
    code    INTEGER,
    output  TEXT
);
CREATE TABLE IF NOT EXISTS lldp_state (
    local_port TEXT PRIMARY KEY,
    system     TEXT,
    port_id    TEXT,
    port_descr TEXT,
    mgmt_ip    TEXT,
    vlan       TEXT,
    descr      TEXT,
    updated    REAL
);
CREATE TABLE IF NOT EXISTS lldp_changes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL,
    local_port TEXT,
    field      TEXT,
    old_value  TEXT,
    new_value  TEXT
);
"""


def _connect() -> sqlite3.Connection:
    global _initialised
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_FILE), timeout=5)
    db.row_factory = sqlite3.Row
    if not _initialised:
        db.executescript(SCHEMA)
        db.commit()
        _initialised = True
    return db


def available() -> bool:
    try:
        with _lock, _connect() as db:
            db.execute("SELECT 1")
        return True
    except sqlite3.Error:
        return False


# --- Hosts -----------------------------------------------------------------

def record_host(address: str, *, mac: str = "", vendor: str = "", name: str = "",
                source: str = "", kind: str = "") -> None:
    """Upsert a seen/scanned host, unioning its observation sources."""
    if not address:
        return
    now = time.time()
    try:
        with _lock, _connect() as db:
            row = db.execute("SELECT sources FROM hosts WHERE address = ?", (address,)).fetchone()
            if row is None:
                sources = [source] if source else []
                db.execute(
                    "INSERT INTO hosts(address, mac, vendor, name, first_seen, last_seen, sources, last_kind) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (address, mac, vendor, name, now, now, json.dumps(sources), kind),
                )
            else:
                sources = []
                try:
                    sources = json.loads(row["sources"] or "[]")
                except ValueError:
                    sources = []
                if source and source not in sources:
                    sources.append(source)
                # Only overwrite identity fields when we have a fresh non-empty value.
                sets, args = ["last_seen = ?", "sources = ?", "last_kind = ?"], [now, json.dumps(sources), kind]
                for col, val in (("mac", mac), ("vendor", vendor), ("name", name)):
                    if val:
                        sets.append(f"{col} = ?")
                        args.append(val)
                args.append(address)
                db.execute(f"UPDATE hosts SET {', '.join(sets)} WHERE address = ?", args)
            db.commit()
    except sqlite3.Error:
        pass


def get_hosts(limit: int = 500) -> list[dict]:
    try:
        with _lock, _connect() as db:
            rows = db.execute(
                "SELECT * FROM hosts ORDER BY last_seen DESC LIMIT ?", (limit,)
            ).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["sources"] = json.loads(item.get("sources") or "[]")
        except ValueError:
            item["sources"] = []
        out.append(item)
    return out


def get_host(address: str) -> dict | None:
    try:
        with _lock, _connect() as db:
            row = db.execute("SELECT * FROM hosts WHERE address = ?", (address,)).fetchone()
            scans = db.execute(
                "SELECT ts, kind, ok, summary FROM scans WHERE target = ? ORDER BY ts DESC LIMIT 50",
                (address,),
            ).fetchall()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    item = dict(row)
    try:
        item["sources"] = json.loads(item.get("sources") or "[]")
    except ValueError:
        item["sources"] = []
    item["scans"] = [dict(s) for s in scans]
    return item


# --- Scan log --------------------------------------------------------------

def record_scan(kind: str, target: str, *, ok: bool | None = None,
                summary: str = "", job_id: str = "") -> None:
    try:
        with _lock, _connect() as db:
            db.execute(
                "INSERT INTO scans(ts, kind, target, ok, summary, job_id) VALUES(?,?,?,?,?,?)",
                (time.time(), kind, target, None if ok is None else int(ok), summary[:1000], job_id),
            )
            db.commit()
    except sqlite3.Error:
        pass


def update_scan_result(job_id: str, *, ok: bool | None, summary: str) -> None:
    if not job_id:
        return
    try:
        with _lock, _connect() as db:
            db.execute(
                "UPDATE scans SET ok = ?, summary = ? WHERE job_id = ?",
                (None if ok is None else int(ok), summary[:1000], job_id),
            )
            db.commit()
    except sqlite3.Error:
        pass


def get_scans(limit: int = 200, target: str = "") -> list[dict]:
    try:
        with _lock, _connect() as db:
            if target:
                rows = db.execute(
                    "SELECT * FROM scans WHERE target = ? ORDER BY ts DESC LIMIT ?", (target, limit)
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM scans ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


# --- Persistent job log ----------------------------------------------------

def upsert_job(job: dict) -> None:
    try:
        with _lock, _connect() as db:
            db.execute(
                "INSERT INTO jobs(id, kind, state, target, started, ended, code, output) "
                "VALUES(:id,:kind,:state,:target,:started,:ended,:code,:output) "
                "ON CONFLICT(id) DO UPDATE SET state=excluded.state, ended=excluded.ended, "
                "code=excluded.code, output=excluded.output",
                {
                    "id": job.get("id"), "kind": job.get("kind"), "state": job.get("state"),
                    "target": job.get("target", ""), "started": job.get("started"),
                    "ended": job.get("ended"), "code": job.get("code"),
                    "output": (job.get("output") or "")[:20000],
                },
            )
            db.commit()
    except sqlite3.Error:
        pass


def get_jobs(limit: int = 100) -> list[dict]:
    try:
        with _lock, _connect() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


# --- LLDP continuous inventory --------------------------------------------

def record_lldp(neighbors: list[dict]) -> list[dict]:
    """Diff current LLDP neighbours against the stored state, log field changes
    and return them (so callers can surface topology drift)."""
    changes: list[dict] = []
    now = time.time()
    try:
        with _lock, _connect() as db:
            for n in neighbors:
                port = n.get("local_port", "")
                if not port:
                    continue
                prev = db.execute("SELECT * FROM lldp_state WHERE local_port = ?", (port,)).fetchone()
                fields = ("system", "port_id", "port_descr", "mgmt_ip", "vlan", "descr")
                if prev is not None:
                    for f in fields:
                        old, new = (prev[f] or ""), (n.get(f) or "")
                        if old != new and (old or new):
                            changes.append({"local_port": port, "field": f, "old": old, "new": new})
                            db.execute(
                                "INSERT INTO lldp_changes(ts, local_port, field, old_value, new_value) VALUES(?,?,?,?,?)",
                                (now, port, f, old, new),
                            )
                db.execute(
                    "INSERT INTO lldp_state(local_port, system, port_id, port_descr, mgmt_ip, vlan, descr, updated) "
                    "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(local_port) DO UPDATE SET "
                    "system=excluded.system, port_id=excluded.port_id, port_descr=excluded.port_descr, "
                    "mgmt_ip=excluded.mgmt_ip, vlan=excluded.vlan, descr=excluded.descr, updated=excluded.updated",
                    (port, n.get("system", ""), n.get("port_id", ""), n.get("port_descr", ""),
                     n.get("mgmt_ip", ""), n.get("vlan", ""), n.get("descr", ""), now),
                )
            db.commit()
    except sqlite3.Error:
        return []
    return changes


def lldp_last_update() -> float | None:
    """Timestamp of the most recent neighbour snapshot, or None."""
    try:
        with _lock, _connect() as db:
            row = db.execute("SELECT MAX(updated) AS t FROM lldp_state").fetchone()
        return row["t"] if row and row["t"] else None
    except sqlite3.Error:
        return None


def get_lldp_state(limit: int = 100) -> list[dict]:
    """Current known neighbours (last snapshot per local port)."""
    try:
        with _lock, _connect() as db:
            rows = db.execute("SELECT * FROM lldp_state ORDER BY local_port LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def get_lldp_changes(limit: int = 50) -> list[dict]:
    try:
        with _lock, _connect() as db:
            rows = db.execute(
                "SELECT ts, local_port, field, old_value, new_value FROM lldp_changes ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
