"""Session / acceptance report assembly + rendering (roadmap P1, task #48).

Pure, dependency-free (stdlib only). `build_report()` turns already-fetched
monitor rows + the config-in-effect into one report dict; `to_json/to_csv/to_html`
render it; `compute_digest()` gives a SHA-256 over the report's canonical JSON so
the artefact is tamper-evident for an acceptance hand-off.

Nothing here opens a database, a socket, or a file — app.py does the read-only
DB work and passes plain dicts in, which keeps the whole module unit-testable
without any live monitor. All three renderings carry the *same* digest (computed
over the data, with the digest field itself blanked), so a reviewer can re-derive
it from any one artefact and detect tampering.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from datetime import datetime, timezone

SCHEMA_VERSION = 1
# Availability at or above this is a clean acceptance; below it flags attention.
PASS_AVAILABILITY_PCT = 99.0


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(timespec="seconds")


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


def _summarise_target(rows: list[dict]) -> dict:
    total = len(rows)
    up = sum(1 for r in rows if r["ok"])
    down = total - up
    rtts = sorted(r["rtt_ms"] for r in rows if r["ok"] and r["rtt_ms"] is not None)
    return {
        "samples": total,
        "up": up,
        "down": down,
        "availability_pct": round(100.0 * up / total, 3) if total else None,
        "loss_pct": round(100.0 * down / total, 3) if total else None,
        "rtt_median_ms": _percentile(rtts, 50),
        "rtt_p95_ms": _percentile(rtts, 95),
    }


def build_report(*, now: float | None = None,
                 window_start: float, window_end: float,
                 host: str = "", version: str = "dev", role: str = "standalone",
                 ping_rows: list[dict] | None = None,
                 service_rows: list[dict] | None = None,
                 event_rows: list[dict] | None = None,
                 trend_verdicts: dict | None = None,
                 wifi_rows: list[dict] | None = None,
                 config: dict | None = None) -> dict:
    """Assemble the session report dict from pre-fetched rows.

    ping_rows:    {ts, target, ok, rtt_ms}
    service_rows: {ts, name, kind, ok, duration_ms}
    event_rows:   {id, started, ended, kind, failed_targets}  (failed_targets = JSON str or list)
    trend_verdicts: {"tcp": {...}, "dns": {...}} from trends.*_trend()["verdict"] (optional)
    wifi_rows:    {ts, connected, signal_dbm} (optional)
    config:       redacted settings subset to record as "in effect" (optional)
    """
    now = time.time() if now is None else now
    ping_rows = ping_rows or []
    service_rows = service_rows or []
    event_rows = event_rows or []

    # Per-target availability.
    by_target: dict[str, list[dict]] = {}
    for r in ping_rows:
        by_target.setdefault(r["target"], []).append(r)
    targets = []
    for name in sorted(by_target):
        t = _summarise_target(by_target[name])
        t["target"] = name
        targets.append(t)

    # Per-service reliability.
    by_service: dict[tuple, list[dict]] = {}
    for r in service_rows:
        by_service.setdefault((r["name"], r.get("kind", "")), []).append(r)
    services = []
    for (name, kind) in sorted(by_service):
        rows = by_service[(name, kind)]
        checks = len(rows)
        ok = sum(1 for r in rows if r["ok"])
        durs = [r["duration_ms"] for r in rows if r.get("duration_ms") is not None]
        services.append({
            "name": name, "kind": kind, "checks": checks, "ok": ok,
            "fail": checks - ok,
            "failure_pct": round(100.0 * (checks - ok) / checks, 3) if checks else None,
            "avg_duration_ms": round(sum(durs) / len(durs), 2) if durs else None,
        })

    # Outage events (with RCA-ish failed-target context).
    events = []
    for r in event_rows:
        ft = r.get("failed_targets")
        if isinstance(ft, str):
            try:
                ft = json.loads(ft)
            except (ValueError, TypeError):
                ft = [ft] if ft else []
        ended = r.get("ended")
        events.append({
            "id": r.get("id"),
            "kind": r.get("kind"),
            "started": r.get("started"),
            "started_iso": _iso(r.get("started")),
            "ended": ended,
            "ended_iso": _iso(ended),
            "ongoing": ended is None,
            "duration_s": round(ended - r["started"], 1) if ended and r.get("started") else None,
            "failed_targets": ft or [],
        })
    events.sort(key=lambda e: e.get("started") or 0)

    # Wi-Fi link summary (optional).
    wifi_summary = None
    if wifi_rows:
        sig = sorted(r["signal_dbm"] for r in wifi_rows if r.get("signal_dbm") is not None)
        conn = sum(1 for r in wifi_rows if r.get("connected"))
        wifi_summary = {
            "samples": len(wifi_rows),
            "connected_pct": round(100.0 * conn / len(wifi_rows), 1) if wifi_rows else None,
            "signal_min_dbm": sig[0] if sig else None,
            "signal_median_dbm": _percentile(sig, 50) if sig else None,
            "signal_max_dbm": sig[-1] if sig else None,
        }

    # Roll-up + acceptance verdict.
    total_samples = sum(t["samples"] for t in targets)
    total_up = sum(t["up"] for t in targets)
    overall = round(100.0 * total_up / total_samples, 3) if total_samples else None
    worst = min((t["availability_pct"] for t in targets
                 if t["availability_pct"] is not None), default=None)
    open_events = sum(1 for e in events if e["ongoing"])
    trouble = [k for k, v in (trend_verdicts or {}).items()
               if isinstance(v, dict) and v.get("state") in ("rising", "degraded")]
    verdict = "pass"
    reasons = []
    if overall is not None and overall < PASS_AVAILABILITY_PCT:
        verdict = "attention"
        reasons.append(f"overall availability {overall}% below {PASS_AVAILABILITY_PCT}%")
    if open_events:
        verdict = "attention"
        reasons.append(f"{open_events} outage event(s) still open")
    if trouble:
        verdict = "attention"
        reasons.append("sustained trend degradation: " + ", ".join(sorted(trouble)))
    if total_samples == 0:
        verdict = "insufficient_data"
        reasons.append("no reachability samples in the selected window")

    report = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "report": "session-acceptance",
            "generated_at": round(now, 3),
            "generated_iso": _iso(now),
            "host": host,
            "version": version,
            "role": role,
            "window": {
                "start": round(window_start, 3),
                "end": round(window_end, 3),
                "start_iso": _iso(window_start),
                "end_iso": _iso(window_end),
                "duration_s": round(window_end - window_start, 1),
            },
            "digest": None,  # filled by finalize()
        },
        "summary": {
            "targets_monitored": len(targets),
            "services_monitored": len(services),
            "reachability_samples": total_samples,
            "overall_availability_pct": overall,
            "worst_target_availability_pct": worst,
            "events_total": len(events),
            "events_open": open_events,
            "verdict": verdict,
            "reasons": reasons,
        },
        "targets": targets,
        "services": services,
        "events": events,
        "trends": trend_verdicts or {},
        "wifi": wifi_summary,
        "config_in_effect": config or {},
    }
    return report


# --- integrity -------------------------------------------------------------

def _canonical(report: dict) -> bytes:
    """Canonical JSON bytes with the digest field blanked, for hashing."""
    clone = json.loads(json.dumps(report))  # deep copy
    if isinstance(clone.get("meta"), dict):
        clone["meta"]["digest"] = None
    return json.dumps(clone, sort_keys=True, separators=(",", ":")).encode()


def compute_digest(report: dict) -> str:
    """SHA-256 (hex) over the report's canonical JSON, digest field blanked."""
    return hashlib.sha256(_canonical(report)).hexdigest()


def finalize(report: dict) -> dict:
    """Stamp meta.digest in place and return the report (idempotent)."""
    report["meta"]["digest"] = compute_digest(report)
    return report


def verify(report: dict) -> bool:
    """True iff the embedded digest matches a recomputation (tamper check)."""
    return bool(report.get("meta", {}).get("digest")) and \
        report["meta"]["digest"] == compute_digest(report)


# --- renderers -------------------------------------------------------------

def to_json(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True)


def to_csv(report: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    m, s = report["meta"], report["summary"]
    w.writerow(["# Fieldline Network Probe — Session Acceptance Report"])
    for k in ("generated_iso", "host", "version", "role", "digest"):
        w.writerow([f"# {k}", m.get(k)])
    w.writerow(["# window", m["window"]["start_iso"], m["window"]["end_iso"],
                f'{m["window"]["duration_s"]}s'])
    w.writerow(["# verdict", s["verdict"], "; ".join(s["reasons"])])
    w.writerow([])
    w.writerow(["[targets]"])
    w.writerow(["target", "samples", "up", "down", "availability_pct",
                "loss_pct", "rtt_median_ms", "rtt_p95_ms"])
    for t in report["targets"]:
        w.writerow([t["target"], t["samples"], t["up"], t["down"],
                    t["availability_pct"], t["loss_pct"],
                    t["rtt_median_ms"], t["rtt_p95_ms"]])
    w.writerow([])
    w.writerow(["[services]"])
    w.writerow(["name", "kind", "checks", "ok", "fail", "failure_pct", "avg_duration_ms"])
    for sv in report["services"]:
        w.writerow([sv["name"], sv["kind"], sv["checks"], sv["ok"], sv["fail"],
                    sv["failure_pct"], sv["avg_duration_ms"]])
    w.writerow([])
    w.writerow(["[events]"])
    w.writerow(["id", "kind", "started_iso", "ended_iso", "duration_s",
                "ongoing", "failed_targets"])
    for e in report["events"]:
        w.writerow([e["id"], e["kind"], e["started_iso"], e["ended_iso"],
                    e["duration_s"], e["ongoing"], "|".join(map(str, e["failed_targets"]))])
    w.writerow([])
    w.writerow(["[trends]"])
    w.writerow(["signal", "state", "latest"])
    for name, v in (report.get("trends") or {}).items():
        if isinstance(v, dict):
            w.writerow([name, v.get("state"), v.get("latest")])
    return out.getvalue()


def _esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def to_html(report: dict) -> str:
    m, s = report["meta"], report["summary"]
    vclass = {"pass": "ok", "attention": "bad", "insufficient_data": "warn"}.get(s["verdict"], "")

    def rows(items, cols):
        if not items:
            return '<tr><td colspan="%d" class="muted">none</td></tr>' % len(cols)
        out = []
        for it in items:
            out.append("<tr>" + "".join(f"<td>{_esc(it.get(c))}</td>" for c in cols) + "</tr>")
        return "".join(out)

    targets_tbl = rows(report["targets"],
                       ["target", "samples", "up", "down", "availability_pct",
                        "loss_pct", "rtt_median_ms", "rtt_p95_ms"])
    services_tbl = rows(report["services"],
                        ["name", "kind", "checks", "ok", "fail", "failure_pct", "avg_duration_ms"])
    ev = [{**e, "failed_targets": ", ".join(map(str, e["failed_targets"]))} for e in report["events"]]
    events_tbl = rows(ev, ["id", "kind", "started_iso", "ended_iso", "duration_s",
                           "ongoing", "failed_targets"])
    trend_items = [{"signal": k, "state": v.get("state"), "latest": v.get("latest")}
                   for k, v in (report.get("trends") or {}).items() if isinstance(v, dict)]
    trends_tbl = rows(trend_items, ["signal", "state", "latest"])
    reasons = ("<ul>" + "".join(f"<li>{_esc(r)}</li>" for r in s["reasons"]) + "</ul>") \
        if s["reasons"] else '<p class="muted">no exceptions</p>'
    wifi = report.get("wifi")
    wifi_html = ""
    if wifi:
        wifi_html = ("<h2>Wi-Fi link</h2><table><tr>"
                     f"<td>samples</td><td>{_esc(wifi['samples'])}</td></tr><tr>"
                     f"<td>connected</td><td>{_esc(wifi['connected_pct'])}%</td></tr><tr>"
                     f"<td>signal min/median/max dBm</td><td>{_esc(wifi['signal_min_dbm'])} / "
                     f"{_esc(wifi['signal_median_dbm'])} / {_esc(wifi['signal_max_dbm'])}</td></tr></table>")
    config_json = _esc(json.dumps(report.get("config_in_effect") or {}, indent=2, sort_keys=True))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Session Acceptance Report — {_esc(m['host'])}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ font: 14px/1.5 system-ui, sans-serif; margin: 0; padding: 2rem;
       background: #f7f8fa; color: #1a1d21; }}
@media (prefers-color-scheme: dark) {{ body {{ background:#14171a; color:#e6e8eb; }}
  table {{ background:#1c2024 !important; }} th {{ background:#22272b !important; }}
  .card {{ background:#1c2024 !important; }} pre {{ background:#0f1214 !important; }} }}
h1 {{ font-size: 1.5rem; margin: 0 0 .25rem; }}
.sub {{ color:#6b7280; margin:0 0 1.5rem; }}
.card {{ background:#fff; border-radius:10px; padding:1rem 1.25rem; margin-bottom:1.25rem;
        box-shadow:0 1px 3px rgba(0,0,0,.08); }}
.verdict {{ display:inline-block; padding:.2rem .7rem; border-radius:999px; font-weight:600; }}
.ok {{ background:#16a34a22; color:#16a34a; }}
.bad {{ background:#dc262622; color:#dc2626; }}
.warn {{ background:#d9770622; color:#d97706; }}
table {{ border-collapse:collapse; width:100%; background:#fff; border-radius:8px; overflow:hidden;
        margin:.5rem 0 0; }}
th, td {{ text-align:left; padding:.45rem .6rem; border-bottom:1px solid #e5e7eb33; font-variant-numeric:tabular-nums; }}
th {{ background:#f1f3f5; font-weight:600; }}
.muted {{ color:#9ca3af; }}
.digest {{ font-family:ui-monospace, monospace; font-size:.8rem; word-break:break-all;
          background:#00000010; padding:.5rem .6rem; border-radius:6px; }}
pre {{ background:#f1f3f5; padding:.75rem; border-radius:6px; overflow-x:auto; font-size:.8rem; }}
.tablewrap {{ overflow-x:auto; }}
</style></head>
<body>
<h1>Session Acceptance Report</h1>
<p class="sub">{_esc(m['host'])} · role {_esc(m['role'])} · build {_esc(m['version'])}<br>
window {_esc(m['window']['start_iso'])} → {_esc(m['window']['end_iso'])}
({_esc(m['window']['duration_s'])} s) · generated {_esc(m['generated_iso'])}</p>

<div class="card">
  <p>Verdict: <span class="verdict {vclass}">{_esc(s['verdict']).upper()}</span></p>
  <table>
    <tr><td>Targets monitored</td><td>{_esc(s['targets_monitored'])}</td>
        <td>Services monitored</td><td>{_esc(s['services_monitored'])}</td></tr>
    <tr><td>Overall availability</td><td>{_esc(s['overall_availability_pct'])}%</td>
        <td>Worst target</td><td>{_esc(s['worst_target_availability_pct'])}%</td></tr>
    <tr><td>Reachability samples</td><td>{_esc(s['reachability_samples'])}</td>
        <td>Outage events (open)</td><td>{_esc(s['events_total'])} ({_esc(s['events_open'])})</td></tr>
  </table>
  {reasons}
</div>

<div class="card"><h2>Targets</h2><div class="tablewrap"><table>
<tr><th>Target</th><th>Samples</th><th>Up</th><th>Down</th><th>Avail %</th><th>Loss %</th><th>RTT p50</th><th>RTT p95</th></tr>
{targets_tbl}</table></div></div>

<div class="card"><h2>Services</h2><div class="tablewrap"><table>
<tr><th>Name</th><th>Kind</th><th>Checks</th><th>OK</th><th>Fail</th><th>Fail %</th><th>Avg ms</th></tr>
{services_tbl}</table></div></div>

<div class="card"><h2>Outage events</h2><div class="tablewrap"><table>
<tr><th>ID</th><th>Kind</th><th>Started</th><th>Ended</th><th>Duration s</th><th>Ongoing</th><th>Failed targets</th></tr>
{events_tbl}</table></div></div>

<div class="card"><h2>Protocol trends</h2><div class="tablewrap"><table>
<tr><th>Signal</th><th>State</th><th>Latest</th></tr>
{trends_tbl}</table></div></div>

<div class="card">{wifi_html}<h2>Config in effect</h2><pre>{config_json}</pre></div>

<div class="card"><h2>Integrity</h2>
<p>SHA-256 digest of this report's data (recompute over the canonical JSON to verify):</p>
<p class="digest">{_esc(m['digest'])}</p></div>
</body></html>"""


def render(report: dict, fmt: str) -> tuple[str, str, str]:
    """Return (text, content_type, filename) for fmt in json|csv|html.

    The report must already be finalize()d so meta.digest is populated.
    """
    host = (report["meta"].get("host") or "probe").replace(" ", "_")
    stamp = (report["meta"].get("generated_iso") or "").replace(":", "").replace("-", "")[:15]
    base = f"session-report-{host}-{stamp}" if stamp else f"session-report-{host}"
    if fmt == "json":
        return to_json(report), "application/json", base + ".json"
    if fmt == "csv":
        return to_csv(report), "text/csv", base + ".csv"
    if fmt == "html":
        return to_html(report), "text/html; charset=utf-8", base + ".html"
    raise ValueError(f"unknown report format: {fmt!r}")
