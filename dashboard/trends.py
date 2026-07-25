"""Protocol trend analysis: TCP retransmission/reset + DNS failure trends (task #50).

Pure, dependency-free analysis over samples the monitor already records. Two
signals, one idea: *alert on a sustained rise, never on a single spike.*

- **TCP** — the monitor stores cumulative kernel counters (`tcp_samples`). We
  difference consecutive snapshots into per-interval rates: the retransmission
  ratio (retransmitted / sent segments) and the reset rate (RSTs per second).
  Counter resets (a reboot zeroes /proc counters) show up as a negative delta and
  are dropped rather than producing a nonsense spike.
- **DNS** — the monitor stores per-probe success/failure (`service_samples`,
  kind='dns'). We bucket those into a failure-percentage series.

Each series is smoothed with an EWMA and classified by `assess_series`, which
separates a *sustained* elevation (several consecutive buckets over threshold —
worth alerting) from a transient *spike* (one bucket — noted but not alerted).
This is the parameter-light, training-data-free approach the roadmap's Phase 3
calls for (CUSUM/EWMA family; Münz 2010, Christodoulou 2015); the heavier
CUSUM+PCA detectors layer on top of the same series later.

Nothing here does I/O — callers pass in rows read from the DB.
"""
from __future__ import annotations

# Counter fields that must not go backwards; a negative delta means the kernel
# counters were reset (reboot) and the interval is skipped.
_MONOTONIC = ("in_segs", "out_segs", "retrans_segs", "out_rsts",
              "attempt_fails", "estab_resets", "tcp_syn_retrans", "tcp_lost_retransmit")

# Verdict thresholds. Retransmit ratio: a healthy LAN sits well under 1%; >2%
# sustained is worth attention, >5% is bad. DNS failure: >5% sustained is a
# problem, >20% is severe. These are conservative defaults, overridable per call.
TCP_RETRANS_WARN = 0.02
TCP_RETRANS_CRIT = 0.05
DNS_FAIL_WARN = 5.0
DNS_FAIL_CRIT = 20.0
# How many consecutive over-threshold buckets make an elevation "sustained".
SUSTAIN_BUCKETS = 3


def ewma(values: list[float], alpha: float = 0.3) -> list[float]:
    """Exponentially weighted moving average. `alpha` in (0,1]; higher = more
    responsive, lower = smoother. Returns a list the same length as `values`."""
    out: list[float] = []
    prev: float | None = None
    for v in values:
        prev = v if prev is None else alpha * v + (1 - alpha) * prev
        out.append(prev)
    return out


def _bucketize(points: list[tuple[float, float]], bucket_s: float) -> list[tuple[float, float]]:
    """Average (ts, value) points into fixed-width time buckets, ascending.

    Returns [(bucket_start_ts, mean_value), ...]. Empty input -> []."""
    if bucket_s <= 0:
        bucket_s = 1.0
    buckets: dict[int, list[float]] = {}
    for ts, val in points:
        if val is None:
            continue
        key = int(ts // bucket_s)
        buckets.setdefault(key, []).append(val)
    out = []
    for key in sorted(buckets):
        vals = buckets[key]
        out.append((float(key * bucket_s), sum(vals) / len(vals)))
    return out


def counter_deltas(samples: list[dict]) -> list[dict]:
    """Difference consecutive cumulative-counter snapshots into per-interval rates.

    `samples`: dicts with 'ts' plus the monotonic counter fields, any order.
    Returns, per adjacent pair (ascending ts), a dict with:
      ts        - end timestamp of the interval
      dt        - seconds elapsed
      retrans_ratio - retrans_segs delta / out_segs delta (0 if no segments sent)
      reset_rate    - out_rsts delta / dt (RSTs per second)
      syn_retrans_rate - tcp_syn_retrans delta / dt
    Intervals with dt<=0, or any monitored counter decreasing (reboot), are
    skipped so a counter reset never reads as a burst."""
    rows = sorted((s for s in samples if s.get("ts") is not None), key=lambda s: s["ts"])
    out: list[dict] = []
    for prev, cur in zip(rows, rows[1:]):
        dt = float(cur["ts"]) - float(prev["ts"])
        if dt <= 0:
            continue
        d: dict[str, float] = {}
        reset = False
        for field in _MONOTONIC:
            delta = float(cur.get(field, 0) or 0) - float(prev.get(field, 0) or 0)
            if delta < 0:
                reset = True
                break
            d[field] = delta
        if reset:
            continue
        out_segs = d.get("out_segs", 0.0)
        out.append({
            "ts": float(cur["ts"]),
            "dt": dt,
            "retrans_ratio": (d["retrans_segs"] / out_segs) if out_segs > 0 else 0.0,
            "reset_rate": d["out_rsts"] / dt,
            "syn_retrans_rate": d["tcp_syn_retrans"] / dt,
        })
    return out


def assess_series(values: list[float], *, warn: float, crit: float,
                  sustain: int = SUSTAIN_BUCKETS, alpha: float = 0.3) -> dict:
    """Classify a numeric series into a sustained-vs-spike verdict.

    Returns {state, latest, smoothed, sustained_count, warn, crit}, where state is:
      insufficient_data - fewer than 2 points
      stable    - latest smoothed value at/under warn
      spike     - over warn now, but not for `sustain` consecutive buckets
      rising    - over warn for >= `sustain` consecutive buckets
      degraded  - rising AND latest smoothed value over crit
    Smoothing uses EWMA so one noisy bucket cannot by itself trip 'rising'."""
    clean = [float(v) for v in values if v is not None]
    if len(clean) < 2:
        return {"state": "insufficient_data", "latest": clean[-1] if clean else None,
                "smoothed": clean[-1] if clean else None, "sustained_count": 0,
                "warn": warn, "crit": crit}
    smooth = ewma(clean, alpha)
    latest = smooth[-1]
    # Count trailing consecutive smoothed buckets over the warn line.
    sustained = 0
    for v in reversed(smooth):
        if v > warn:
            sustained += 1
        else:
            break
    if sustained >= sustain and latest > crit:
        state = "degraded"
    elif sustained >= sustain:
        state = "rising"
    elif latest > warn:
        state = "spike"
    else:
        state = "stable"
    return {"state": state, "latest": round(latest, 6), "smoothed": round(latest, 6),
            "sustained_count": sustained, "warn": warn, "crit": crit}


def tcp_trend(samples: list[dict], *, bucket_s: float = 300.0,
              warn: float = TCP_RETRANS_WARN, crit: float = TCP_RETRANS_CRIT,
              sustain: int = SUSTAIN_BUCKETS) -> dict:
    """Full TCP retransmission/reset trend from cumulative counter samples.

    Returns bucketed series (ts, retrans_ratio, reset_rate, syn_retrans_rate) and
    a `verdict` from the retransmission ratio (the headline signal)."""
    deltas = counter_deltas(samples)
    ratio_pts = _bucketize([(d["ts"], d["retrans_ratio"]) for d in deltas], bucket_s)
    reset_pts = _bucketize([(d["ts"], d["reset_rate"]) for d in deltas], bucket_s)
    syn_pts = _bucketize([(d["ts"], d["syn_retrans_rate"]) for d in deltas], bucket_s)
    ratios = [v for _, v in ratio_pts]
    return {
        "bucket_seconds": bucket_s,
        "series": {
            "ts": [t for t, _ in ratio_pts],
            "retrans_ratio": [round(v, 6) for v in ratios],
            "reset_rate": [round(v, 4) for _, v in reset_pts],
            "syn_retrans_rate": [round(v, 4) for _, v in syn_pts],
        },
        "verdict": assess_series(ratios, warn=warn, crit=crit, sustain=sustain),
    }


def dns_trend(rows: list[dict], *, bucket_s: float = 300.0,
              warn: float = DNS_FAIL_WARN, crit: float = DNS_FAIL_CRIT,
              sustain: int = SUSTAIN_BUCKETS) -> dict:
    """DNS failure-rate trend from service_samples rows (kind='dns').

    `rows`: dicts with 'ts' and 'ok' (1/0). Returns a bucketed failure-% series
    and a `verdict`."""
    # Failure fraction per sample (1.0 = failed), averaged within each bucket,
    # then scaled to a percentage.
    pts = [(float(r["ts"]), 0.0 if r.get("ok") else 1.0)
           for r in rows if r.get("ts") is not None]
    frac = _bucketize(pts, bucket_s)
    fail_pct = [(t, v * 100.0) for t, v in frac]
    pcts = [v for _, v in fail_pct]
    return {
        "bucket_seconds": bucket_s,
        "series": {
            "ts": [t for t, _ in fail_pct],
            "fail_pct": [round(v, 2) for v in pcts],
        },
        "verdict": assess_series(pcts, warn=warn, crit=crit, sustain=sustain),
    }
