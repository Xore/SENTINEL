"""Tests for the guarded check scheduler (monitor/scheduler.py, task #46).

The scheduler is a pure, deterministic brain: injectable clock and RNG, no
threads, no I/O. These tests drive it with a fake clock and jitter disabled so
backoff/cooldown/concurrency are checked as exact numbers, plus a couple of
classification and startup-spread cases.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "monitor"))
import scheduler  # noqa: E402


class Clock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def policies(jitter: float = 0.0):
    return {
        scheduler.QUEUE_IT: scheduler.QueuePolicy(
            base_interval=60, min_interval=10, max_interval=480,
            concurrency=2, backoff=2.0, jitter=jitter),
        scheduler.QUEUE_OT: scheduler.QueuePolicy(
            base_interval=120, min_interval=60, max_interval=960,
            concurrency=1, backoff=2.0, jitter=jitter),
    }


def new_sched(clock, jitter=0.0, startup_spread=0.0):
    return scheduler.GuardedScheduler(policies(jitter), clock=clock,
                                      startup_spread=startup_spread)


class ClassifyTests(unittest.TestCase):
    def test_explicit_queue_wins(self):
        self.assertEqual(scheduler.classify_queue({"name": "plc1", "queue": "it"}),
                         scheduler.QUEUE_IT)
        self.assertEqual(scheduler.classify_queue({"name": "dns", "class": "ot"}),
                         scheduler.QUEUE_OT)

    def test_ot_hints_in_group_or_name(self):
        for item in ({"name": "line3-plc", "group": "custom"},
                     {"name": "cell", "group": "profinet"},
                     {"name": "opcua-health", "group": "internal"},
                     {"name": "hmi-panel"}):
            self.assertEqual(scheduler.classify_queue(item), scheduler.QUEUE_OT, item)

    def test_ot_as_token_not_substring(self):
        # "ot" as its own token classifies OT ...
        self.assertEqual(scheduler.classify_queue({"name": "ot-gw"}), scheduler.QUEUE_OT)
        # ... but "root"/"boot" must NOT trip it.
        self.assertEqual(scheduler.classify_queue({"name": "root-dns"}), scheduler.QUEUE_IT)
        self.assertEqual(scheduler.classify_queue({"name": "bootstrap"}), scheduler.QUEUE_IT)

    def test_default_it(self):
        self.assertEqual(scheduler.classify_queue({"name": "web", "group": "external"}),
                         scheduler.QUEUE_IT)


class SyncTests(unittest.TestCase):
    def test_add_and_remove_jobs(self):
        clk = Clock(0)
        s = new_sched(clk)
        s.sync([{"name": "a"}, {"name": "b"}])
        self.assertEqual(set(s.jobs), {"a", "b"})
        s.sync([{"name": "b"}, {"name": "c"}])
        self.assertEqual(set(s.jobs), {"b", "c"})  # a dropped, c added

    def test_reclassify_keeps_timing(self):
        clk = Clock(0)
        s = new_sched(clk)
        s.sync([{"name": "x", "group": "external"}])
        s.jobs["x"].next_due = 999
        s.sync([{"name": "x", "group": "profinet"}])  # now OT
        self.assertEqual(s.jobs["x"].queue, scheduler.QUEUE_OT)
        self.assertEqual(s.jobs["x"].next_due, 999)   # timing preserved

    def test_startup_spread_bounds(self):
        clk = Clock(1000)
        s = scheduler.GuardedScheduler(policies(), clock=clk, startup_spread=30)
        s.sync([{"name": f"j{i}"} for i in range(20)])
        for job in s.jobs.values():
            self.assertGreaterEqual(job.next_due, 1000)
            self.assertLessEqual(job.next_due, 1030)


class DueTests(unittest.TestCase):
    def test_concurrency_caps_starts_per_call(self):
        clk = Clock(0)
        s = new_sched(clk)  # startup_spread 0 -> all due at t=0
        s.sync([{"name": f"it{i}", "group": "external"} for i in range(5)])
        first = s.due(0)
        self.assertEqual(len(first), 2)          # IT concurrency = 2
        # the two just-started jobs are within cooldown, so the next call picks
        # two DIFFERENT jobs
        second = s.due(0)
        self.assertEqual(len(second), 2)
        self.assertFalse(set(first) & set(second))

    def test_ot_and_it_are_independent_queues(self):
        clk = Clock(0)
        s = new_sched(clk)
        s.sync([{"name": "it1", "group": "external"},
                {"name": "it2", "group": "external"},
                {"name": "ot1", "group": "profinet"}])
        due = set(s.due(0))
        # up to 2 IT + 1 OT may start together
        self.assertIn("ot1", due)
        self.assertEqual(len(due & {"it1", "it2"}), 2)

    def test_not_due_before_next_due(self):
        clk = Clock(0)
        s = new_sched(clk)
        s.sync([{"name": "a", "group": "external"}])
        s.jobs["a"].next_due = 50
        self.assertEqual(s.due(10), [])
        self.assertEqual(s.due(50), ["a"])


class RecordTests(unittest.TestCase):
    def test_success_schedules_base_interval(self):
        clk = Clock(0)
        s = new_sched(clk)
        s.sync([{"name": "a", "group": "external"}])
        s.record("a", True, now=0)
        self.assertEqual(s.jobs["a"].fails, 0)
        self.assertEqual(s.jobs["a"].next_due, 60)

    def test_failure_backs_off_geometrically_capped(self):
        clk = Clock(0)
        s = new_sched(clk)
        s.sync([{"name": "a", "group": "external"}])
        expected = [60, 120, 240, 480, 480]  # base*2^(n-1), capped at max_interval
        for i, exp in enumerate(expected, start=1):
            s.record("a", False, now=0)
            self.assertEqual(s.jobs["a"].fails, i)
            self.assertEqual(s.jobs["a"].next_due, exp)

    def test_success_after_failures_resets(self):
        clk = Clock(0)
        s = new_sched(clk)
        s.sync([{"name": "a", "group": "external"}])
        s.record("a", False, now=0)
        s.record("a", False, now=0)
        s.record("a", True, now=0)
        self.assertEqual(s.jobs["a"].fails, 0)
        self.assertEqual(s.jobs["a"].next_due, 60)

    def test_cooldown_floor_applies(self):
        clk = Clock(0)
        pol = policies()
        # a queue whose base is BELOW the cooldown floor
        pol[scheduler.QUEUE_IT] = scheduler.QueuePolicy(
            base_interval=5, min_interval=10, max_interval=100,
            concurrency=2, jitter=0.0)
        s = scheduler.GuardedScheduler(pol, clock=clk, startup_spread=0)
        s.sync([{"name": "a", "group": "external"}])
        s.record("a", True, now=0)
        self.assertEqual(s.jobs["a"].next_due, 10)  # floored up to min_interval

    def test_record_unknown_key_is_noop(self):
        s = new_sched(Clock(0))
        s.record("nope", True, now=0)  # must not raise


class NextWaitTests(unittest.TestCase):
    def test_empty_returns_ceiling(self):
        s = new_sched(Clock(0))
        self.assertEqual(s.next_wait(0, floor=1, ceil=30), 30)

    def test_clamped_between_floor_and_ceil(self):
        clk = Clock(0)
        s = new_sched(clk)
        s.sync([{"name": "a", "group": "external"}])
        s.jobs["a"].next_due = 100
        self.assertEqual(s.next_wait(0, floor=1, ceil=30), 30)   # far -> ceil
        s.jobs["a"].next_due = 5
        self.assertEqual(s.next_wait(0, floor=1, ceil=30), 5)    # soon -> exact
        s.jobs["a"].next_due = -100
        self.assertEqual(s.next_wait(0, floor=1, ceil=30), 1)    # overdue -> floor


class JitterTests(unittest.TestCase):
    def test_jitter_stays_within_band_and_above_floor(self):
        import random
        clk = Clock(0)
        pol = policies(jitter=0.15)
        s = scheduler.GuardedScheduler(pol, clock=clk, rng=random.Random(1),
                                       startup_spread=0)
        s.sync([{"name": "a", "group": "external"}])
        for _ in range(200):
            s.record("a", True, now=0)
            gap = s.jobs["a"].next_due  # now=0
            self.assertGreaterEqual(gap, 60 * 0.85 - 1e-9)  # base - jitter band
            self.assertLessEqual(gap, 60 * 1.15 + 1e-9)     # base + jitter band


if __name__ == "__main__":
    unittest.main()
