"""Sustained-state alerting: notify once per transition, never on a spike (#53).

This is the delivery half of the trend work in task #50. Task #50's
`assess_series` classifies each signal as stable / spike / rising / degraded;
here we turn *crossings* of that classification into notifications:

- a signal that rises into the alerting band (>= `min_state`, default `rising`)
  fires a **firing** notification, once;
- when it falls back below the band it fires a **resolved** notification, once.

Because the classification is already the sustained-vs-spike decision, a single
transient `spike` never alerts (unless the operator lowers `min_state` to
`spike`). The evaluator is edge-triggered off a persisted per-signal state, so a
steady `degraded` reading does not re-page every poll, and a dashboard restart
does not replay old alerts.

Layering:
- `evaluate()` is pure: (signals, previous state) -> (events, new state). No I/O,
  so the transition logic is fully unit-testable.
- `render_subject`/`render_body` are pure formatters.
- `deliver_webhook`/`deliver_email` do the actual network I/O (stdlib only:
  urllib + smtplib), each returning a small result dict and never raising.
- `dispatch()` fans an event out to the enabled channels.
- `load_state`/`save_state` persist the edge state + a bounded history atomically.

Nothing here decides *what* the signals are - app.py gathers them from the
monitor DB (TCP/DNS trends + open outage events) and hands them in.
"""
from __future__ import annotations

import json
import os
import smtplib
import tempfile
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path

STATE_FILE = Path(os.environ.get("PROBE_ALERT_STATE",
                                 "/var/lib/network-probe/alert-state.json"))
HISTORY_LIMIT = 200
WEBHOOK_TIMEOUT = 8.0
SMTP_TIMEOUT = 15.0

# Ordered severity of a trend verdict. A signal is "alerting" once its state is
# at or above the operator's min_state.
ALERT_LEVEL = {
    "stable": 0,
    "insufficient_data": 0,
    "spike": 1,
    "rising": 2,
    "degraded": 3,
}
MIN_STATE_CHOICES = ("spike", "rising", "degraded")


def is_alerting(state: str, min_state: str = "rising") -> bool:
    """True when `state` is at or above the `min_state` alerting threshold."""
    floor = ALERT_LEVEL.get(min_state, ALERT_LEVEL["rising"])
    return ALERT_LEVEL.get(state, 0) >= max(1, floor)


def evaluate(signals: list[dict], prev_signals: dict, *, min_state: str = "rising",
             now: float | None = None) -> tuple[list[dict], dict]:
    """Pure transition evaluation.

    `signals`: current readings, each {id, title, state, summary?, value?}.
    `prev_signals`: last persisted per-id state ({id: {"alerting": bool, ...}}).
    Returns (events, new_signals). `events` holds one dict per *edge* crossed
    this round (kind = "firing" | "resolved"); `new_signals` is the state to
    persist. Signals absent this round are dropped from the new state (so a
    removed target does not leave a stuck alert)."""
    now = time.time() if now is None else now
    events: list[dict] = []
    new: dict = {}
    for s in signals:
        sid = s["id"]
        alerting = is_alerting(s.get("state", "stable"), min_state)
        was = bool(prev_signals.get(sid, {}).get("alerting"))
        entry = {
            "alerting": alerting,
            "state": s.get("state", "stable"),
            "title": s.get("title", sid),
            "summary": s.get("summary", ""),
            "value": s.get("value"),
            "ts": now,
        }
        if alerting and not was:
            events.append({**entry, "id": sid, "kind": "firing"})
        elif was and not alerting:
            events.append({**entry, "id": sid, "kind": "resolved"})
        new[sid] = entry
    return events, new


def render_subject(event: dict) -> str:
    verb = "FIRING" if event.get("kind") == "firing" else "RESOLVED"
    return f"[network-probe] {verb}: {event.get('title', event.get('id'))} — {event.get('state')}"


def render_body(event: dict) -> str:
    lines = [
        render_subject(event),
        "",
        f"signal:   {event.get('id')}",
        f"state:    {event.get('state')}",
        f"status:   {'ALERTING' if event.get('kind') == 'firing' else 'recovered'}",
    ]
    if event.get("value") is not None:
        lines.append(f"value:    {event['value']}")
    if event.get("summary"):
        lines.append(f"detail:   {event['summary']}")
    ts = event.get("ts")
    if ts:
        lines.append(f"time:     {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(ts))}")
    return "\n".join(lines) + "\n"


def deliver_webhook(url: str, event: dict, *, timeout: float = WEBHOOK_TIMEOUT) -> dict:
    """POST the event as JSON to `url`. Returns {ok, status?/error}. Never raises."""
    if not url:
        return {"ok": False, "error": "no webhook url configured"}
    payload = json.dumps({
        "source": "network-probe",
        "kind": event.get("kind"),
        "signal": event.get("id"),
        "title": event.get("title"),
        "state": event.get("state"),
        "summary": event.get("summary"),
        "value": event.get("value"),
        "ts": event.get("ts"),
        "subject": render_subject(event),
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "network-probe-alert/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": 200 <= resp.status < 300, "status": resp.status}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def deliver_email(cfg: dict, event: dict, *, timeout: float = SMTP_TIMEOUT) -> dict:
    """Send the event as an email via the configured SMTP server. Never raises."""
    host = (cfg.get("smtp_host") or "").strip()
    from_addr = (cfg.get("from_addr") or "").strip()
    to_addrs = [a.strip() for a in (cfg.get("to_addrs") or "").split(",") if a.strip()]
    if not host or not from_addr or not to_addrs:
        return {"ok": False, "error": "email host, from_addr and to_addrs are required"}
    msg = EmailMessage()
    msg["Subject"] = render_subject(event)
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(render_body(event))
    port = int(cfg.get("smtp_port") or 587)
    try:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            if cfg.get("use_tls", True):
                smtp.starttls()
            if (cfg.get("username") or "").strip():
                smtp.login(cfg["username"], cfg.get("password") or "")
            smtp.send_message(msg)
        return {"ok": True, "recipients": len(to_addrs)}
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def dispatch(event: dict, alerting_cfg: dict) -> dict:
    """Send one event through every enabled channel; return {channel: result}."""
    results: dict = {}
    webhook = alerting_cfg.get("webhook") or {}
    if webhook.get("enabled") and webhook.get("url"):
        results["webhook"] = deliver_webhook(webhook["url"], event)
    email = alerting_cfg.get("email") or {}
    if email.get("enabled"):
        results["email"] = deliver_email(email, event)
    return results


def load_state(path: Path = STATE_FILE) -> dict:
    """The persisted edge state + history, or a fresh empty structure."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"signals": {}, "history": []}
    if not isinstance(data, dict):
        return {"signals": {}, "history": []}
    data.setdefault("signals", {})
    data.setdefault("history", [])
    return data


def save_state(state: dict, path: Path = STATE_FILE) -> None:
    """Atomically persist the edge state, trimming history to HISTORY_LIMIT."""
    state = dict(state)
    state["history"] = (state.get("history") or [])[-HISTORY_LIMIT:]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".alert-state-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
