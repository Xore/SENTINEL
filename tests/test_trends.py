"""Tests for TCP retransmission/reset + DNS failure trends (task #50).

Three layers, all stdlib unittest:
  1. monitor.tcp_stat  — the pure /proc parser, fed fixture strings (no /proc on
     Windows, so parsing is split from file reading for exactly this).
  2. dashboard.trends  — the pure analysis (deltas, EWMA, sustained-vs-spike,
     DNS failure %), fed synthetic sample lists.
  3. /api/monitor/{tcp,dns} endpoints on dashboard.app, against a synthetic
     monitor.db. _isolation must import before dashboard.app.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolation  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "monitor"))
sys.path.insert(0, str(ROOT))

import tcp_stat  # noqa: E402
from dashboard import app as appmod  # noqa: E402
from dashboard import trends  # noqa: E402


_SNMP = (
    "Tcp: RtoAlgorithm RtoMin RtoMax MaxConn ActiveOpens PassiveOpens "
    "AttemptFails EstabResets CurrEstab InSegs OutSegs RetransSegs InErrs "
    "OutRsts InCsumErrors\n"
    "Tcp: 1 200 120000 -1 100 50 4 7 3 10000 8000 160 0 12 0\n"
    "Udp: InDatagrams NoPorts\nUdp: 5 1\n"
)
_NETSTAT = (
    "TcpExt: SyncookiesSent TCPSynRetrans TCPLostRetransmit DelayedACKs\n"
    "TcpExt: 0 40 3 99\n"
    "IpExt: InNoRoutes InTruncatedPkts\nIpExt: 0 0\n"
)


class ParserTests(unittest.TestCase):
    def test_parse_section_reads_by_name_not_position(self):
        tcp = tcp_stat._parse_section(_SNMP, "Tcp:")
        self.assertEqual(tcp["RetransSegs"], 160)
        self.assertEqual(tcp["OutRsts"], 12)
        self.assertEqual(tcp["OutSegs"], 8000)
        # a field from the trailing Udp: section must not leak in
        self.assertNotIn("InDatagrams", tcp)

    def test_collect_counters_flattens_both_files(self):
        snap = tcp_stat.collect_counters(_SNMP, _NETSTAT)
        self.assertEqual(snap["retrans_segs"], 160)
        self.assertEqual(snap["out_rsts"], 12)
        self.assertEqual(snap["attempt_fails"], 4)
        self.assertEqual(snap["estab_resets"], 7)
        self.assertEqual(snap["tcp_syn_retrans"], 40)
        self.assertEqual(snap["tcp_lost_retransmit"], 3)

    def test_missing_counters_default_to_zero(self):
        snap = tcp_stat.collect_counters("Tcp: OutSegs\nTcp: 5\n", "")
        self.assertEqual(snap["out_segs"], 5)
        self.assertEqual(snap["retrans_segs"], 0)
        self.assertEqual(snap["tcp_syn_retrans"], 0)

    def test_counter_fields_order_matches_table_columns(self):
        # sample_row prepends ts, so 8 counter columns follow it
        self.assertEqual(len(tcp_stat.COUNTER_FIELDS), 8)
        self.assertEqual(tcp_stat.COUNTER_FIELDS[0], "in_segs")
        self.assertEqual(tcp_stat.COUNTER_FIELDS[-1], "tcp_lost_retransmit")

    def test_read_proc_missing_files_returns_none(self):
        self.assertIsNone(tcp_stat.read_proc(
            Path("/nonexistent/snmp"), Path("/nonexistent/netstat")))


class EwmaTests(unittest.TestCase):
    def test_constant_series_is_unchanged(self):
        self.assertEqual(trends.ewma([5, 5, 5]), [5, 5, 5])

    def test_first_value_is_seed(self):
        self.assertEqual(trends.ewma([2, 4, 8])[0], 2)

    def test_smoothing_lags_a_step_change(self):
        out = trends.ewma([0, 0, 10], alpha=0.5)
        self.assertEqual(out[-1], 5.0)  # 0.5*10 + 0.5*0


class CounterDeltaTests(unittest.TestCase):
    def _s(self, ts, out_segs, retrans, rsts, syn=0):
        return {"ts": ts, "in_segs": 0, "out_segs": out_segs,
                "retrans_segs": retrans, "out_rsts": rsts, "attempt_fails": 0,
                "estab_resets": 0, "tcp_syn_retrans": syn, "tcp_lost_retransmit": 0}

    def test_retrans_ratio_is_delta_over_delta(self):
        samples = [self._s(0, 1000, 10, 0), self._s(10, 2000, 30, 0)]
        d = trends.counter_deltas(samples)
        self.assertEqual(len(d), 1)
        # 20 retrans / 1000 sent = 0.02
        self.assertAlmostEqual(d[0]["retrans_ratio"], 0.02)

    def test_reset_rate_is_per_second(self):
        samples = [self._s(0, 1000, 0, 0), self._s(10, 1000, 0, 5)]
        d = trends.counter_deltas(samples)
        self.assertAlmostEqual(d[0]["reset_rate"], 0.5)  # 5 resets / 10 s

    def test_counter_reset_interval_is_skipped(self):
        # second snapshot has smaller counters (reboot) -> that interval dropped
        samples = [self._s(0, 5000, 100, 10), self._s(10, 10, 0, 0),
                   self._s(20, 1010, 0, 0)]
        d = trends.counter_deltas(samples)
        # only the 10->20 interval survives; the reboot interval is gone
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["ts"], 20)

    def test_zero_segments_gives_zero_ratio_not_div0(self):
        samples = [self._s(0, 1000, 5, 0), self._s(10, 1000, 5, 0)]
        d = trends.counter_deltas(samples)
        self.assertEqual(d[0]["retrans_ratio"], 0.0)


class AssessSeriesTests(unittest.TestCase):
    def test_insufficient_data(self):
        r = trends.assess_series([0.5], warn=0.02, crit=0.05)
        self.assertEqual(r["state"], "insufficient_data")

    def test_stable_below_warn(self):
        r = trends.assess_series([0.0, 0.0, 0.0, 0.0], warn=0.02, crit=0.05)
        self.assertEqual(r["state"], "stable")

    def test_single_spike_not_flagged_as_rising(self):
        # one high bucket at the end after a calm run -> spike, not rising
        r = trends.assess_series([0.0, 0.0, 0.0, 0.0, 0.10], warn=0.02, crit=0.05,
                                 sustain=3, alpha=0.6)
        self.assertEqual(r["state"], "spike")
        self.assertLess(r["sustained_count"], 3)

    def test_sustained_rise_is_rising(self):
        r = trends.assess_series([0.0, 0.0, 0.03, 0.03, 0.03, 0.03], warn=0.02,
                                 crit=0.5, sustain=3, alpha=0.6)
        self.assertEqual(r["state"], "rising")
        self.assertGreaterEqual(r["sustained_count"], 3)

    def test_sustained_and_over_crit_is_degraded(self):
        r = trends.assess_series([0.1, 0.1, 0.1, 0.1, 0.1], warn=0.02, crit=0.05,
                                 sustain=3)
        self.assertEqual(r["state"], "degraded")


class TcpTrendTests(unittest.TestCase):
    def _s(self, ts, out_segs, retrans, rsts):
        return {"ts": ts, "in_segs": 0, "out_segs": out_segs,
                "retrans_segs": retrans, "out_rsts": rsts, "attempt_fails": 0,
                "estab_resets": 0, "tcp_syn_retrans": 0, "tcp_lost_retransmit": 0}

    def test_healthy_traffic_is_stable(self):
        # steady 1% retransmit, well under 2% warn
        samples = [self._s(i * 30, 1000 * (i + 1), 10 * (i + 1), 0) for i in range(20)]
        out = trends.tcp_trend(samples, bucket_s=60)
        self.assertEqual(out["verdict"]["state"], "stable")
        self.assertTrue(out["series"]["retrans_ratio"])

    def test_empty_samples_is_insufficient(self):
        out = trends.tcp_trend([], bucket_s=60)
        self.assertEqual(out["verdict"]["state"], "insufficient_data")
        self.assertEqual(out["series"]["ts"], [])


class DnsTrendTests(unittest.TestCase):
    def test_all_ok_is_zero_failure_stable(self):
        rows = [{"ts": i * 30, "ok": 1} for i in range(20)]
        out = trends.dns_trend(rows, bucket_s=60)
        self.assertEqual(out["verdict"]["state"], "stable")
        self.assertTrue(all(v == 0.0 for v in out["series"]["fail_pct"]))

    def test_sustained_failures_flagged(self):
        # first calm, then a long run of failures
        rows = [{"ts": i * 60, "ok": 1} for i in range(3)]
        rows += [{"ts": (3 + i) * 60, "ok": 0} for i in range(8)]
        out = trends.dns_trend(rows, bucket_s=60, sustain=3)
        self.assertIn(out["verdict"]["state"], ("rising", "degraded"))

    def test_failure_pct_scaling(self):
        # 1 of 4 failed in one bucket -> 25%
        rows = [{"ts": 1, "ok": 1}, {"ts": 2, "ok": 1},
                {"ts": 3, "ok": 1}, {"ts": 4, "ok": 0}]
        out = trends.dns_trend(rows, bucket_s=3600)
        self.assertEqual(out["series"]["fail_pct"], [25.0])


def _seed_monitor_db(path: Path) -> None:
    now = time.time()
    db = sqlite3.connect(str(path))
    db.executescript(
        """
        CREATE TABLE tcp_samples (ts REAL, in_segs INTEGER, out_segs INTEGER,
            retrans_segs INTEGER, out_rsts INTEGER, attempt_fails INTEGER,
            estab_resets INTEGER, tcp_syn_retrans INTEGER, tcp_lost_retransmit INTEGER);
        CREATE TABLE service_samples (ts REAL, name TEXT, kind TEXT, ok INTEGER,
            duration_ms REAL, detail TEXT);
        """
    )
    # 20 cumulative TCP snapshots, steady ~1% retransmit
    for i in range(20):
        ts = now - (20 - i) * 30
        db.execute("INSERT INTO tcp_samples VALUES (?,?,?,?,?,?,?,?,?)",
                   (ts, 0, 1000 * (i + 1), 10 * (i + 1), 0, 0, 0, 0, 0))
    # DNS: mostly ok
    for i in range(20):
        ts = now - (20 - i) * 30
        db.execute("INSERT INTO service_samples VALUES (?,?,?,?,?,?)",
                   (ts, "dns:1.1.1.1", "dns", 1, 5.0, ""))
    db.commit()
    db.close()


class EndpointTests(unittest.TestCase):
    def setUp(self):
        appmod.AUTH_DISABLED = True
        self.c = appmod.app.test_client()
        self._db = Path(os.environ["PROBE_MONITOR_DB"])
        if self._db.exists():
            self._db.unlink()

    def test_tcp_no_db_returns_503(self):
        r = self.c.get("/api/monitor/tcp")
        self.assertEqual(r.status_code, 503)

    def test_dns_no_db_returns_503(self):
        r = self.c.get("/api/monitor/dns")
        self.assertEqual(r.status_code, 503)

    def test_tcp_endpoint_returns_trend(self):
        _seed_monitor_db(self._db)
        r = self.c.get("/api/monitor/tcp?minutes=60")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("verdict", data)
        self.assertIn("retrans_ratio", data["series"])
        self.assertEqual(data["samples"], 20)

    def test_dns_endpoint_returns_trend(self):
        _seed_monitor_db(self._db)
        r = self.c.get("/api/monitor/dns?minutes=60")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("fail_pct", data["series"])
        self.assertEqual(data["verdict"]["state"], "stable")

    def test_bad_minutes_returns_400(self):
        _seed_monitor_db(self._db)
        r = self.c.get("/api/monitor/tcp?minutes=notanumber")
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
