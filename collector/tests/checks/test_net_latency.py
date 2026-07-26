"""Tests for collector.checks.net_latency — RTT jitter probe."""
from __future__ import annotations

import asyncio

import pytest
from collector.checks.net_latency import LatencyCheck, compute_jitter_ms
from collector.config import load_settings


class TestComputeJitterMs:
    def test_empty_list_returns_zero(self):
        assert compute_jitter_ms([]) == 0.0

    def test_single_sample_returns_zero(self):
        assert compute_jitter_ms([10.0]) == 0.0

    def test_two_samples_is_their_difference(self):
        assert compute_jitter_ms([10.0, 12.0]) == 2.0

    def test_mean_absolute_successive_difference(self):
        # diffs: |12-10|=2, |9-12|=3 -> mean 2.5
        assert compute_jitter_ms([10.0, 12.0, 9.0]) == 2.5


class TestLatencyCheck:
    def test_interval_s_from_icmp_config(self):
        settings = load_settings(collector_id="c", icmp={"interval_s": 7})
        check = LatencyCheck(settings, meter=None, target="10.0.0.1")
        assert check.interval_s == 7

    def test_semaphore_stored(self):
        settings = load_settings(collector_id="c")
        sem = asyncio.Semaphore(3)
        check = LatencyCheck(settings, meter=None, target="10.0.0.1", semaphore=sem)
        assert check.semaphore is sem

    async def test_all_samples_succeed(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = LatencyCheck(settings, meter=None, target="10.0.0.1", sample_count=3)
        rtts = iter([10.0, 12.0, 9.0])

        async def fake_ping(target, *, identifier, sequence, timeout_s):
            return next(rtts)

        monkeypatch.setattr("collector.checks.net_latency.ping", fake_ping)
        result = await check.run()

        assert result.ok is True
        assert result.metrics["icmp_rtt_ms"] == pytest.approx(31.0 / 3)
        assert result.metrics["icmp_rtt_jitter_ms"] == 2.5
        assert result.metrics["icmp_loss_pct"] == 0.0
        assert result.labels == {"target": "10.0.0.1"}

    async def test_partial_failures_reflected_in_loss_and_jitter(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = LatencyCheck(settings, meter=None, target="10.0.0.1", sample_count=4)
        outcomes = iter([10.0, TimeoutError("no reply"), 12.0, TimeoutError("no reply")])

        async def fake_ping(target, *, identifier, sequence, timeout_s):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr("collector.checks.net_latency.ping", fake_ping)
        result = await check.run()

        assert result.ok is True
        assert result.metrics["icmp_loss_pct"] == 50.0
        assert result.metrics["icmp_rtt_ms"] == 11.0
        assert result.metrics["icmp_rtt_jitter_ms"] == 2.0

    async def test_all_samples_fail(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = LatencyCheck(settings, meter=None, target="10.0.0.1", sample_count=3)

        async def failing_ping(target, *, identifier, sequence, timeout_s):
            raise TimeoutError("no reply")

        monkeypatch.setattr("collector.checks.net_latency.ping", failing_ping)
        result = await check.run()

        assert result.ok is False
        assert result.metrics == {"icmp_loss_pct": 100.0}
        assert "all 3 samples" in result.error

    async def test_uses_distinct_sequence_per_sample(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = LatencyCheck(settings, meter=None, target="10.0.0.1", sample_count=3)
        seen_sequences: list[int] = []

        async def fake_ping(target, *, identifier, sequence, timeout_s):
            seen_sequences.append(sequence)
            return 1.0

        monkeypatch.setattr("collector.checks.net_latency.ping", fake_ping)
        await check.run()

        assert seen_sequences == [1, 2, 3]
