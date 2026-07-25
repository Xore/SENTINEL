"""Guarded scheduler for the outage monitor's active checks (roadmap P1, #46).

The monitor's service/port checks used to run in a tight "probe every configured
endpoint, then sleep a fixed interval" loop. That has three problems for a probe
that may sit on a live plant network:

  * no jitter        -> every endpoint is hit on the same beat, forever, which
                        both wastes bandwidth in synchronized bursts and makes the
                        probe trivially fingerprintable;
  * no backoff       -> a dead endpoint is hammered at full rate indefinitely;
  * no OT/IT split   -> a fragile OT device (PLC, PROFINET/S7/OPC UA host) is
                        probed as aggressively as a cloud DNS resolver.

This module is the pure, deterministic brain that fixes all three. It owns no
threads and does no I/O: a loop calls `sync()` with the current job list, `due()`
to learn which jobs may start now (respecting per-queue concurrency and a cooldown
floor), then `record()` after each run to schedule the next attempt with jitter
and, on failure, exponential backoff. Clock and RNG are injectable so the whole
thing is unit-testable without sleeping or flaking.

OT vs IT is decided by `classify_queue()`: an explicit ``queue``/``class`` field
on a check wins; otherwise a check whose group or name looks operational-technology
(plc, profinet, s7, opc ua, modbus, scada, ...) lands in the gentler OT queue.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field

QUEUE_OT = "ot"
QUEUE_IT = "it"

# Substrings that mark a check as operational-technology when no explicit queue
# is set. Deliberately broad; the cost of a false positive is only a gentler beat.
OT_HINTS = ("ot", "plc", "profinet", "s7", "opcua", "opc-ua", "opc_ua",
            "scada", "modbus", "ethernet/ip", "ethernetip", "cip", "hmi")


def classify_queue(item: dict) -> str:
    """Return QUEUE_OT or QUEUE_IT for one check dict.

    An explicit ``queue`` (or ``class``) of "ot"/"it" wins. Otherwise the check's
    group and name are scanned for OT hints; "ot" as a whole word/token counts,
    but arbitrary substrings (e.g. "root") must not, so hint matching is
    token-aware for the short ambiguous ones.
    """
    explicit = str(item.get("queue") or item.get("class") or "").strip().lower()
    if explicit in (QUEUE_OT, QUEUE_IT):
        return explicit
    group = str(item.get("group") or "").strip().lower()
    name = str(item.get("name") or "").strip().lower()
    hay = f"{group} {name}"
    tokens = set(re_split(group)) | set(re_split(name))
    # Short/ambiguous hints (ot, s7, cip, plc, hmi) match only as a whole token so
    # "root"/"boot" don't trip OT; longer, distinctive hints also match as a
    # substring so "line3-plc" or "opcua-health" are caught however they're split.
    for hint in OT_HINTS:
        if hint in tokens or (len(hint) > 3 and hint in hay):
            return QUEUE_OT
    return QUEUE_IT


def re_split(text: str) -> list[str]:
    """Split on any non-alphanumeric run -> lowercase tokens."""
    out, cur = [], []
    for ch in text:
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


@dataclass
class QueuePolicy:
    """Pacing rules for one queue."""
    base_interval: float       # nominal seconds between attempts of one job
    min_interval: float        # cooldown: never re-run a job sooner than this
    max_interval: float        # backoff ceiling
    concurrency: int           # max jobs that may START per due() call (rate cap)
    backoff: float = 2.0       # multiplier per consecutive failure
    jitter: float = 0.15       # +/- fraction added to each scheduled interval


def default_policies() -> dict[str, QueuePolicy]:
    """Env-tunable defaults. IT is brisk; OT is deliberately gentle and low-rate."""
    it_base = float(os.environ.get("PROBE_SCHED_IT_INTERVAL", "60"))
    ot_base = float(os.environ.get("PROBE_SCHED_OT_INTERVAL", "120"))
    return {
        QUEUE_IT: QueuePolicy(
            base_interval=it_base,
            min_interval=float(os.environ.get("PROBE_SCHED_IT_MIN", "10")),
            max_interval=float(os.environ.get("PROBE_SCHED_IT_MAX", str(it_base * 8))),
            concurrency=int(os.environ.get("PROBE_SCHED_IT_CONCURRENCY", "4")),
        ),
        QUEUE_OT: QueuePolicy(
            base_interval=ot_base,
            min_interval=float(os.environ.get("PROBE_SCHED_OT_MIN", "60")),
            max_interval=float(os.environ.get("PROBE_SCHED_OT_MAX", str(ot_base * 8))),
            concurrency=int(os.environ.get("PROBE_SCHED_OT_CONCURRENCY", "1")),
        ),
    }


@dataclass
class _Job:
    key: str
    queue: str
    next_due: float
    fails: int = 0
    last_start: float = field(default=float("-inf"))


class GuardedScheduler:
    """Decides when each keyed job may run; applies jitter, backoff and cooldown.

    Not thread-safe: give each monitor loop its own instance (they run in their
    own threads, so there is no shared state to lock).
    """

    def __init__(self, policies: dict[str, QueuePolicy] | None = None, *,
                 clock=time.monotonic, rng: random.Random | None = None,
                 startup_spread: float | None = None):
        self.policies = policies or default_policies()
        self.clock = clock
        self.rng = rng if rng is not None else random.Random()
        self.startup_spread = (startup_spread if startup_spread is not None
                               else float(os.environ.get("PROBE_SCHED_STARTUP_SPREAD", "15")))
        self.jobs: dict[str, _Job] = {}

    def _policy(self, queue: str) -> QueuePolicy:
        return self.policies.get(queue) or self.policies[QUEUE_IT]

    def _jittered(self, interval: float, policy: QueuePolicy) -> float:
        if policy.jitter <= 0:
            return interval
        span = interval * policy.jitter
        return interval + self.rng.uniform(-span, span)

    def sync(self, items: list[dict], key=lambda i: i.get("name")) -> None:
        """Register newly-seen jobs (due soon, spread by a startup jitter) and
        drop jobs no longer configured. Existing jobs keep their schedule."""
        now = self.clock()
        desired: dict[str, str] = {}
        for item in items:
            k = key(item)
            if not k:
                continue
            desired[k] = classify_queue(item)
        for k in list(self.jobs):
            if k not in desired:
                del self.jobs[k]
        for k, queue in desired.items():
            job = self.jobs.get(k)
            if job is None:
                policy = self._policy(queue)
                # Stagger new jobs so they don't all fire at once, but bound the
                # startup delay so the first sample still lands promptly.
                spread = min(policy.base_interval, self.startup_spread)
                self.jobs[k] = _Job(key=k, queue=queue,
                                    next_due=now + self.rng.uniform(0, spread))
            elif job.queue != queue:
                job.queue = queue  # reclassified via config edit; keep timing

    def due(self, now: float | None = None) -> list[str]:
        """Keys whose next_due has passed, honouring per-queue concurrency and the
        cooldown floor. Marks each returned job as started (so concurrency and
        cooldown are enforced even before record() is called)."""
        if now is None:
            now = self.clock()
        picked: list[str] = []
        for queue, policy in self.policies.items():
            ready = [j for j in self.jobs.values()
                     if j.queue == queue
                     and j.next_due <= now
                     and (now - j.last_start) >= policy.min_interval]
            ready.sort(key=lambda j: j.next_due)
            for job in ready[:max(0, policy.concurrency)]:
                job.last_start = now
                picked.append(job.key)
        return picked

    def record(self, key: str, ok: bool, now: float | None = None) -> None:
        """Record an attempt's outcome and schedule the next one. Failures grow
        the interval geometrically up to the ceiling; a success resets to base.
        The scheduled gap is jittered and never shorter than the cooldown floor."""
        job = self.jobs.get(key)
        if job is None:
            return
        if now is None:
            now = self.clock()
        policy = self._policy(job.queue)
        if ok:
            job.fails = 0
            interval = policy.base_interval
        else:
            job.fails += 1
            interval = min(policy.base_interval * (policy.backoff ** (job.fails - 1)),
                           policy.max_interval)
        interval = max(self._jittered(interval, policy), policy.min_interval)
        job.next_due = now + interval

    def next_wait(self, now: float | None = None, floor: float = 1.0,
                  ceil: float = 30.0) -> float:
        """How long a loop should sleep before its next due() poll: the time until
        the soonest job, clamped to [floor, ceil]. With no jobs, sleeps `ceil`."""
        if now is None:
            now = self.clock()
        if not self.jobs:
            return ceil
        soonest = min(j.next_due for j in self.jobs.values())
        return max(floor, min(ceil, soonest - now))

    # Introspection for tests / diagnostics.
    def snapshot(self) -> dict[str, dict]:
        return {k: {"queue": j.queue, "fails": j.fails,
                    "next_due": j.next_due, "last_start": j.last_start}
                for k, j in self.jobs.items()}
