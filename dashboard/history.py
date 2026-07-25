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

import hashlib
import json
import os
import secrets
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
CREATE TABLE IF NOT EXISTS ap_state (
    bssid       TEXT PRIMARY KEY,
    ssid        TEXT,
    band        TEXT,
    channel     INTEGER,
    security    TEXT,
    signal      TEXT,          -- last seen signal, as text (dBm or %)
    first_seen  REAL,
    last_seen   REAL,
    present     INTEGER        -- 1 = seen in the latest scan, 0 = gone
);
CREATE INDEX IF NOT EXISTS idx_ap_present ON ap_state(present);
CREATE TABLE IF NOT EXISTS ap_events (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     REAL,
    bssid  TEXT,
    ssid   TEXT,
    event  TEXT,               -- appeared | disappeared
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_ap_events_ts ON ap_events(ts);
CREATE TABLE IF NOT EXISTS heatmap_surveys (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT,
    created      REAL,
    updated      REAL,
    ap_positions TEXT,          -- JSON {bssid: {x,y,ssid}} placed on the floor
    floorplan    TEXT           -- optional data: URL background image
);
CREATE TABLE IF NOT EXISTS heatmap_points (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id INTEGER,
    ts        REAL,
    x         REAL,             -- 0..1 fractional position on the canvas
    y         REAL,
    readings  TEXT              -- JSON [{bssid,ssid,signal_dbm,channel,band,freq_mhz}]
);
CREATE INDEX IF NOT EXISTS idx_heatmap_points_survey ON heatmap_points(survey_id);
CREATE TABLE IF NOT EXISTS collectors (
    collector_id TEXT PRIMARY KEY,
    name         TEXT,
    key_hash     TEXT,          -- sha256 hex of the ingest key (plaintext never stored)
    key_prefix   TEXT,          -- first chars of the key, for display/identification
    enabled      INTEGER,       -- 1 = active, 0 = revoked
    created      REAL,
    last_seen    REAL,
    hostname     TEXT,
    node_ip      TEXT,
    version      TEXT,
    status       TEXT,           -- agent self-report: RUNNING | DEGRADED | STARTING
    status_meta  TEXT,           -- JSON {detail, cycles, last_error}
    update_requested INTEGER,    -- 1 = operator asked this collector to self-update
    update_secret TEXT,          -- per-collector HMAC secret: signs update instructions
                                 -- so only THIS backend can authorize a binary swap
    meta         TEXT           -- JSON blob of last-reported telemetry
);
CREATE TABLE IF NOT EXISTS collector_samples (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    collector_id TEXT,
    stream       TEXT,          -- interfaces | neighbours | ping | ...
    ts           REAL,
    payload      TEXT           -- JSON
);
CREATE INDEX IF NOT EXISTS idx_collector_samples ON collector_samples(collector_id, stream, ts);
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL,
    user    TEXT,               -- session user who made the change (or "-")
    action  TEXT,               -- e.g. settings.update, monitor.config, multinode
    target  TEXT,               -- what was changed (section/key/id)
    detail  TEXT                -- short, already-redacted human summary
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


def _connect() -> sqlite3.Connection:
    global _initialised
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_FILE), timeout=5)
    db.row_factory = sqlite3.Row
    if not _initialised:
        db.executescript(SCHEMA)
        # Additive migrations for DBs created before a column existed. CREATE
        # TABLE IF NOT EXISTS won't add columns to a table that already exists,
        # so patch them in idempotently.
        for col, decl in (("status", "TEXT"), ("status_meta", "TEXT"),
                          ("update_requested", "INTEGER"), ("update_secret", "TEXT")):
            try:
                db.execute(f"ALTER TABLE collectors ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass  # column already present
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


# --- Access-point sighting monitor -----------------------------------------

def _ap_signal(ap: dict) -> str:
    if ap.get("signal_dbm") is not None:
        return f"{ap['signal_dbm']} dBm"
    if ap.get("signal_pct") is not None:
        return f"{ap['signal_pct']}%"
    return ""


def record_ap_scan(aps: list[dict]) -> dict:
    """Diff a fresh Wi-Fi scan against the stored AP inventory, log appear/
    disappear events and return them. A BSSID present before but missing from
    this scan flips to 'disappeared'; a new or returning BSSID is 'appeared'.

    The caller MUST only pass a *valid* scan (at least one AP). An empty list -
    e.g. the radio being rfkill-blocked - is ignored here so a blocked radio
    never fabricates a mass-disappearance event.
    """
    result = {"appeared": [], "disappeared": [], "scanned": len(aps)}
    if not aps:
        return result
    now = time.time()
    seen = {}
    for ap in aps:
        bssid = (ap.get("bssid") or "").lower()
        if bssid:
            seen[bssid] = ap
    try:
        with _lock, _connect() as db:
            prev = {r["bssid"]: r for r in db.execute("SELECT * FROM ap_state").fetchall()}
            for bssid, ap in seen.items():
                sig = _ap_signal(ap)
                ssid = ap.get("ssid", "") or "(hidden)"
                row = prev.get(bssid)
                if row is None or not row["present"]:
                    detail = f"{ssid} · {ap.get('band','')} ch{ap.get('channel','?')} · {sig}"
                    db.execute("INSERT INTO ap_events(ts, bssid, ssid, event, detail) VALUES(?,?,?,?,?)",
                               (now, bssid, ssid, "appeared", detail))
                    result["appeared"].append({"bssid": bssid, "ssid": ssid, "detail": detail})
                first = row["first_seen"] if row else now
                db.execute(
                    "INSERT INTO ap_state(bssid, ssid, band, channel, security, signal, first_seen, last_seen, present) "
                    "VALUES(?,?,?,?,?,?,?,?,1) ON CONFLICT(bssid) DO UPDATE SET "
                    "ssid=excluded.ssid, band=excluded.band, channel=excluded.channel, security=excluded.security, "
                    "signal=excluded.signal, last_seen=excluded.last_seen, present=1",
                    (bssid, ssid, ap.get("band", ""), ap.get("channel"), ap.get("security", ""),
                     sig, first, now))
            for bssid, row in prev.items():
                if row["present"] and bssid not in seen:
                    ssid = row["ssid"] or "(hidden)"
                    gone_for = now - (row["last_seen"] or now)
                    detail = f"{ssid} · last seen {int(gone_for)}s ago · {row['band'] or ''} ch{row['channel'] or '?'}"
                    db.execute("INSERT INTO ap_events(ts, bssid, ssid, event, detail) VALUES(?,?,?,?,?)",
                               (now, bssid, ssid, "disappeared", detail))
                    db.execute("UPDATE ap_state SET present=0 WHERE bssid=?", (bssid,))
                    result["disappeared"].append({"bssid": bssid, "ssid": ssid, "detail": detail})
            # keep the event log bounded
            db.execute("DELETE FROM ap_events WHERE id NOT IN "
                       "(SELECT id FROM ap_events ORDER BY ts DESC LIMIT 2000)")
            db.commit()
    except sqlite3.Error:
        pass
    return result


def get_ap_state(limit: int = 400) -> list[dict]:
    try:
        with _lock, _connect() as db:
            rows = db.execute(
                "SELECT * FROM ap_state ORDER BY present DESC, last_seen DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def get_ap_events(limit: int = 100) -> list[dict]:
    try:
        with _lock, _connect() as db:
            rows = db.execute(
                "SELECT ts, bssid, ssid, event, detail FROM ap_events ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def ap_last_update() -> float | None:
    try:
        with _lock, _connect() as db:
            row = db.execute("SELECT MAX(last_seen) AS t FROM ap_state").fetchone()
        return row["t"] if row and row["t"] else None
    except sqlite3.Error:
        return None


# --- Wi-Fi coverage heatmap / site survey ----------------------------------
# A survey is a set of sample points on a floor canvas (positions are stored as
# 0..1 fractions so the canvas can be any size), each holding the per-BSSID RSSI
# read at that spot. AP markers can be dragged to their real-world position.

def create_heatmap_survey(name: str) -> dict | None:
    now = time.time()
    try:
        with _lock, _connect() as db:
            cur = db.execute(
                "INSERT INTO heatmap_surveys(name, created, updated, ap_positions, floorplan) "
                "VALUES(?,?,?,?,?)", (name or "Survey", now, now, "{}", None))
            db.commit()
            sid = cur.lastrowid
        return {"id": sid, "name": name or "Survey", "created": now, "updated": now,
                "ap_positions": {}, "points": []}
    except sqlite3.Error:
        return None


def list_heatmap_surveys() -> list[dict]:
    try:
        with _lock, _connect() as db:
            rows = db.execute(
                """SELECT s.id, s.name, s.created, s.updated,
                          (SELECT COUNT(*) FROM heatmap_points p WHERE p.survey_id = s.id) AS point_count
                   FROM heatmap_surveys s ORDER BY s.updated DESC""").fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def get_heatmap_survey(survey_id: int) -> dict | None:
    try:
        with _lock, _connect() as db:
            row = db.execute("SELECT * FROM heatmap_surveys WHERE id = ?", (survey_id,)).fetchone()
            if row is None:
                return None
            pts = db.execute(
                "SELECT id, ts, x, y, readings FROM heatmap_points WHERE survey_id = ? ORDER BY ts",
                (survey_id,)).fetchall()
        survey = dict(row)
        try:
            survey["ap_positions"] = json.loads(survey.get("ap_positions") or "{}")
        except ValueError:
            survey["ap_positions"] = {}
        survey["points"] = [
            {"id": p["id"], "ts": p["ts"], "x": p["x"], "y": p["y"],
             "readings": json.loads(p["readings"] or "[]")} for p in pts]
        return survey
    except (sqlite3.Error, ValueError):
        return None


def add_heatmap_point(survey_id: int, x: float, y: float, readings: list[dict]) -> dict | None:
    now = time.time()
    try:
        with _lock, _connect() as db:
            if db.execute("SELECT 1 FROM heatmap_surveys WHERE id = ?", (survey_id,)).fetchone() is None:
                return None
            cur = db.execute(
                "INSERT INTO heatmap_points(survey_id, ts, x, y, readings) VALUES(?,?,?,?,?)",
                (survey_id, now, x, y, json.dumps(readings)))
            db.execute("UPDATE heatmap_surveys SET updated = ? WHERE id = ?", (now, survey_id))
            db.commit()
            pid = cur.lastrowid
        return {"id": pid, "ts": now, "x": x, "y": y, "readings": readings}
    except sqlite3.Error:
        return None


def delete_heatmap_point(survey_id: int, point_id: int) -> bool:
    try:
        with _lock, _connect() as db:
            cur = db.execute("DELETE FROM heatmap_points WHERE id = ? AND survey_id = ?",
                             (point_id, survey_id))
            db.execute("UPDATE heatmap_surveys SET updated = ? WHERE id = ?", (time.time(), survey_id))
            db.commit()
            return cur.rowcount > 0
    except sqlite3.Error:
        return False


def set_heatmap_ap_positions(survey_id: int, positions: dict) -> bool:
    try:
        with _lock, _connect() as db:
            cur = db.execute(
                "UPDATE heatmap_surveys SET ap_positions = ?, updated = ? WHERE id = ?",
                (json.dumps(positions), time.time(), survey_id))
            db.commit()
            return cur.rowcount > 0
    except sqlite3.Error:
        return False


def rename_heatmap_survey(survey_id: int, name: str) -> bool:
    try:
        with _lock, _connect() as db:
            cur = db.execute("UPDATE heatmap_surveys SET name = ?, updated = ? WHERE id = ?",
                             (name, time.time(), survey_id))
            db.commit()
            return cur.rowcount > 0
    except sqlite3.Error:
        return False


def delete_heatmap_survey(survey_id: int) -> bool:
    try:
        with _lock, _connect() as db:
            db.execute("DELETE FROM heatmap_points WHERE survey_id = ?", (survey_id,))
            cur = db.execute("DELETE FROM heatmap_surveys WHERE id = ?", (survey_id,))
            db.commit()
            return cur.rowcount > 0
    except sqlite3.Error:
        return False


# --- Multi-collector enrollment + ingest -----------------------------------
# The standalone (aggregator) node enrolls remote collectors. Each collector
# gets its OWN ingest key, shown once at enrollment and stored only as a SHA-256
# hash, so a leaked database never yields a usable key. A key can be revoked
# (enabled=0) without deleting the collector's history. Ingest requires the
# global accept-external-collectors toggle AND a valid, non-revoked key.

def _hash_key(key: str) -> str:
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()


def enroll_collector(name: str) -> dict | None:
    """Create a collector and mint its ingest key. Returns the PLAINTEXT key
    once - it is never retrievable again. Returns None on failure."""
    collector_id = "col-" + secrets.token_hex(4)
    key = secrets.token_urlsafe(24)
    # A distinct secret (NOT the ingest key) signs update instructions. It is
    # shared with this one collector so it can verify a binary swap was authorized
    # by us, not injected by an on-path attacker. Stored as-is because it grants no
    # push access - only the ability to verify our HMAC over an update payload.
    update_secret = secrets.token_hex(32)
    now = time.time()
    try:
        with _lock, _connect() as db:
            db.execute(
                "INSERT INTO collectors(collector_id, name, key_hash, key_prefix, enabled, created, last_seen, update_secret) "
                "VALUES(?,?,?,?,1,?,NULL,?)",
                (collector_id, name or collector_id, _hash_key(key), key[:6], now, update_secret))
            db.commit()
        return {"collector_id": collector_id, "name": name or collector_id, "key": key,
                "update_secret": update_secret, "created": now}
    except sqlite3.Error:
        return None


def rotate_collector_key(collector_id: str) -> dict | None:
    """Issue a fresh key for an existing collector (invalidates the old one)."""
    key = secrets.token_urlsafe(24)
    # Re-keying issues a fresh signing secret too, so a fully re-provisioned
    # collector shares all-new credentials with us.
    update_secret = secrets.token_hex(32)
    try:
        with _lock, _connect() as db:
            cur = db.execute(
                "UPDATE collectors SET key_hash = ?, key_prefix = ?, update_secret = ?, enabled = 1 WHERE collector_id = ?",
                (_hash_key(key), key[:6], update_secret, collector_id))
            db.commit()
            if cur.rowcount == 0:
                return None
        return {"collector_id": collector_id, "key": key, "update_secret": update_secret}
    except sqlite3.Error:
        return None


def get_collector_update_secret(collector_id: str) -> str | None:
    """The HMAC secret shared with one collector, used to sign update instructions
    so it can verify they genuinely came from this backend."""
    try:
        with _lock, _connect() as db:
            row = db.execute(
                "SELECT update_secret FROM collectors WHERE collector_id = ? AND enabled = 1",
                (collector_id,)).fetchone()
        return row["update_secret"] if row and row["update_secret"] else None
    except sqlite3.Error:
        return None


def revoke_collector(collector_id: str) -> bool:
    """Invalidate a collector's key without deleting its history."""
    try:
        with _lock, _connect() as db:
            cur = db.execute("UPDATE collectors SET enabled = 0 WHERE collector_id = ?", (collector_id,))
            db.commit()
            return cur.rowcount > 0
    except sqlite3.Error:
        return False


def delete_collector(collector_id: str) -> bool:
    try:
        with _lock, _connect() as db:
            db.execute("DELETE FROM collector_samples WHERE collector_id = ?", (collector_id,))
            cur = db.execute("DELETE FROM collectors WHERE collector_id = ?", (collector_id,))
            db.commit()
            return cur.rowcount > 0
    except sqlite3.Error:
        return False


def list_collectors() -> list[dict]:
    """Enrolled collectors, without any key material (only the prefix)."""
    try:
        with _lock, _connect() as db:
            rows = db.execute(
                "SELECT collector_id, name, key_prefix, enabled, created, last_seen, "
                "hostname, node_ip, version, status, status_meta, update_requested, meta "
                "FROM collectors ORDER BY created").fetchall()
    except sqlite3.Error:
        return []
    out = []
    for r in rows:
        item = dict(r)
        item["enabled"] = bool(item["enabled"])
        item["update_requested"] = bool(item.get("update_requested"))
        for field in ("meta", "status_meta"):
            try:
                item[field] = json.loads(item.get(field) or "{}")
            except ValueError:
                item[field] = {}
        item["status"] = item.get("status") or "UNKNOWN"
        out.append(item)
    return out


def request_collector_update(collector_id: str, requested: bool = True) -> bool:
    """Flag (or clear) a pending self-update for one collector. The collector
    learns of it in its next heartbeat response and pulls the new binary."""
    try:
        with _lock, _connect() as db:
            cur = db.execute(
                "UPDATE collectors SET update_requested = ? WHERE collector_id = ?",
                (1 if requested else 0, collector_id))
            db.commit()
            return cur.rowcount > 0
    except sqlite3.Error:
        return False


def collector_update_pending(collector_id: str) -> bool:
    try:
        with _lock, _connect() as db:
            row = db.execute(
                "SELECT update_requested FROM collectors WHERE collector_id = ?",
                (collector_id,)).fetchone()
        return bool(row and row["update_requested"])
    except sqlite3.Error:
        return False


def authenticate_collector(key: str) -> str | None:
    """Return the collector_id for a presented key if it is valid and enabled,
    else None. Compares against the stored SHA-256 hash."""
    if not key:
        return None
    digest = _hash_key(key)
    try:
        with _lock, _connect() as db:
            row = db.execute(
                "SELECT collector_id FROM collectors WHERE key_hash = ? AND enabled = 1",
                (digest,)).fetchone()
        return row["collector_id"] if row else None
    except sqlite3.Error:
        return None


def touch_collector(collector_id: str, *, hostname: str = "", node_ip: str = "",
                    version: str = "", meta: dict | None = None,
                    status: dict | None = None) -> None:
    """Record a heartbeat: last_seen + last-reported telemetry + self-reported
    lifecycle status (RUNNING/DEGRADED/STARTING). DOWN is not stored here - it is
    derived from a stale last_seen when the collector list is built."""
    status = status or {}
    status_str = str(status.get("status") or "RUNNING")
    status_meta = {k: status.get(k) for k in ("detail", "cycles", "last_error") if k in status}
    try:
        with _lock, _connect() as db:
            db.execute(
                "UPDATE collectors SET last_seen = ?, hostname = ?, node_ip = ?, version = ?, "
                "meta = ?, status = ?, status_meta = ? WHERE collector_id = ?",
                (time.time(), hostname, node_ip, version, json.dumps(meta or {}),
                 status_str, json.dumps(status_meta), collector_id))
            db.commit()
    except sqlite3.Error:
        pass


def ingest_samples(collector_id: str, stream: str, rows: list[dict], cap: int = 5000) -> int:
    """Store a batch of pushed samples for one stream, keeping the per-collector
    /stream history bounded. Returns the number stored."""
    if not rows:
        return 0
    now = time.time()
    try:
        with _lock, _connect() as db:
            db.executemany(
                "INSERT INTO collector_samples(collector_id, stream, ts, payload) VALUES(?,?,?,?)",
                [(collector_id, stream, (r.get("ts") if isinstance(r, dict) else None) or now,
                  json.dumps(r)) for r in rows])
            db.execute(
                "DELETE FROM collector_samples WHERE collector_id = ? AND stream = ? AND id NOT IN "
                "(SELECT id FROM collector_samples WHERE collector_id = ? AND stream = ? ORDER BY ts DESC LIMIT ?)",
                (collector_id, stream, collector_id, stream, cap))
            db.commit()
        return len(rows)
    except sqlite3.Error:
        return 0


def get_collector_samples(collector_id: str, stream: str, limit: int = 200) -> list[dict]:
    try:
        with _lock, _connect() as db:
            rows = db.execute(
                "SELECT ts, payload FROM collector_samples WHERE collector_id = ? AND stream = ? "
                "ORDER BY ts DESC LIMIT ?", (collector_id, stream, limit)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload"] or "{}")
        except ValueError:
            payload = {}
        payload.setdefault("ts", r["ts"])
        out.append(payload)
    return out


def get_collector_neighbours(max_age: float = 3600.0) -> list[dict]:
    """Latest neighbour (ARP/`ip neigh`) sighting each *enabled* collector pushed,
    deduped to one row per (collector_id, ip). Feeds the network map so a remote
    collector's discovered devices appear as collector-tagged nodes. Rows:
    ``{collector_id, ip, mac, state, ts}``. Revoked/disabled collectors are
    excluded so their stale observations drop off the map."""
    cutoff = time.time() - max_age
    try:
        with _lock, _connect() as db:
            rows = db.execute(
                "SELECT s.collector_id, s.ts, s.payload FROM collector_samples s "
                "JOIN collectors c ON c.collector_id = s.collector_id "
                "WHERE s.stream = 'neighbours' AND c.enabled = 1 AND s.ts >= ? "
                "ORDER BY s.ts ASC", (cutoff,)).fetchall()
    except sqlite3.Error:
        return []
    latest: dict[tuple, dict] = {}
    for r in rows:
        try:
            p = json.loads(r["payload"] or "{}")
        except ValueError:
            continue
        ip = (p.get("ip") or "").strip()
        if not ip:
            continue
        # ORDER BY ts ASC means the last write for a key wins = the newest sighting.
        latest[(r["collector_id"], ip)] = {
            "collector_id": r["collector_id"], "ip": ip,
            "mac": (p.get("mac") or "").strip().lower(),
            "state": p.get("state") or "", "ts": r["ts"],
        }
    return list(latest.values())


# --- Audit trail -----------------------------------------------------------

def record_audit(action: str, *, user: str = "-", target: str = "",
                 detail: str = "") -> None:
    """Append one config-change entry to the audit trail. Best-effort: a logging
    failure must never block the change it describes. `detail` MUST already be
    redacted by the caller — never pass secret values here."""
    if not action:
        return
    try:
        with _lock, _connect() as db:
            db.execute(
                "INSERT INTO audit_log(ts, user, action, target, detail) VALUES(?,?,?,?,?)",
                (time.time(), (user or "-")[:80], action[:60], (target or "")[:200],
                 (detail or "")[:500]),
            )
            db.commit()
    except sqlite3.Error:
        pass


def list_audit(limit: int = 100) -> list[dict]:
    """Most-recent audit entries first (id, ts, user, action, target, detail)."""
    limit = max(1, min(int(limit), 1000))
    try:
        with _lock, _connect() as db:
            rows = db.execute(
                "SELECT id, ts, user, action, target, detail FROM audit_log "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]
