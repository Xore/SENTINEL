"""Tests for collector.checks.net_latency — RTT jitter probe."""
from __future__ import annotations

import asyncio

import pytest
from collector.checks.net_latency import LatencyCheck, compute_jitter_ms
from collector.config import LatencyTarget, load_settings

_TARGET = LatencyTarget(target_id="core-switch", host="10.0.0.1")
_HOSTNAME_TARGET = LatencyTarget(target_id="named-switch", host="switch.lan")


class _FakeGauge:
    def __init__(self):
        self.calls: list[tuple[float, dict]] = []

    def set(self, amount, attributes=None):
        self.calls.append((amount, attributes or {}))


class _FakeMeter:
    def __init__(self):
        self.instruments: dict[str, object] = {}

    def create_gauge(self, name, description=None, unit=None):
        instrument = _FakeGauge()
        self.instruments[name] = instrument
        return instrument


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
    def test_interval_s_from_latency_config(self):
        settings = load_settings(collector_id="c", latency={"interval_s": 7})
        check = LatencyCheck(settings, meter=None, target=_TARGET)
        assert check.interval_s == 7

    def test_sample_count_defaults_from_latency_config(self):
        settings = load_settings(collector_id="c", latency={"sample_count": 9})
        check = LatencyCheck(settings, meter=None, target=_TARGET)
        assert check.sample_count == 9

    def test_sample_count_constructor_override_wins(self):
        settings = load_settings(collector_id="c", latency={"sample_count": 9})
        check = LatencyCheck(settings, meter=None, target=_TARGET, sample_count=2)
        assert check.sample_count == 2

    def test_is_enabled_false_by_default(self):
        # LatencyConfig.enabled defaults to False (Q-4's resolution).
        settings = load_settings(collector_id="c")
        check = LatencyCheck(settings, meter=None, target=_TARGET)
        assert check.is_enabled() is False

    def test_is_enabled_true_when_latency_config_enabled(self):
        settings = load_settings(collector_id="c", latency={"enabled": True})
        check = LatencyCheck(settings, meter=None, target=_TARGET)
        assert check.is_enabled() is True

    def test_semaphore_stored(self):
        settings = load_settings(collector_id="c")
        sem = asyncio.Semaphore(3)
        check = LatencyCheck(settings, meter=None, target=_TARGET, semaphore=sem)
        assert check.semaphore is sem

    async def test_all_samples_succeed(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = LatencyCheck(settings, meter=None, target=_TARGET, sample_count=3)
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
        check = LatencyCheck(settings, meter=None, target=_TARGET, sample_count=4)
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
        check = LatencyCheck(settings, meter=None, target=_TARGET, sample_count=3)

        async def failing_ping(target, *, identifier, sequence, timeout_s):
            raise TimeoutError("no reply")

        monkeypatch.setattr("collector.checks.net_latency.ping", failing_ping)
        result = await check.run()

        assert result.ok is False
        assert result.metrics == {"icmp_loss_pct": 100.0}
        assert "all 3 samples" in result.error

    async def test_uses_distinct_sequence_per_sample(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = LatencyCheck(settings, meter=None, target=_TARGET, sample_count=3)
        seen_sequences: list[int] = []

        async def fake_ping(target, *, identifier, sequence, timeout_s):
            seen_sequences.append(sequence)
            return 1.0

        monkeypatch.setattr("collector.checks.net_latency.ping", fake_ping)
        await check.run()

        assert seen_sequences == [1, 2, 3]

    async def test_run_ok_emits_canonical_gauges_with_target_id_label(self, monkeypatch):
        settings = load_settings(collector_id="c")
        meter = _FakeMeter()
        check = LatencyCheck(settings, meter=meter, target=_TARGET, sample_count=3)
        rtts = iter([10.0, 12.0, 9.0])

        async def fake_ping(target, *, identifier, sequence, timeout_s):
            return next(rtts)

        monkeypatch.setattr("collector.checks.net_latency.ping", fake_ping)
        await check.run()

        rtt_calls = meter.instruments["sentinel_collector_latency_rtt_seconds"].calls
        jitter_calls = meter.instruments["sentinel_collector_latency_jitter_seconds"].calls
        loss_calls = meter.instruments["sentinel_collector_latency_loss_ratio"].calls

        assert len(rtt_calls) == 1
        assert rtt_calls[0][0] == pytest.approx(31.0 / 3 / 1000.0)
        assert rtt_calls[0][1] == {"target_id": "core-switch"}
        assert jitter_calls == [(0.0025, {"target_id": "core-switch"})]
        assert loss_calls == [(0.0, {"target_id": "core-switch"})]

    async def test_external_cancellation_during_burst_is_not_swallowed(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = LatencyCheck(settings, meter=None, target=_TARGET, sample_count=3)

        async def slow_ping(target, *, identifier, sequence, timeout_s):
            await asyncio.sleep(10.0)
            return 1.0  # pragma: no cover — never reached

        monkeypatch.setattr("collector.checks.net_latency.ping", slow_ping)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(check.run(), timeout=0.05)

    async def test_resolution_happens_once_per_burst_not_once_per_sample(self, monkeypatch):
        """A burst is one measurement of one destination. Resolving per sample
        would cost `sample_count` timeouts against a failing resolver and could
        mix samples from two addresses into a single mean/jitter figure.
        """
        settings = load_settings(collector_id="c")
        check = LatencyCheck(settings, meter=None, target=_HOSTNAME_TARGET, sample_count=3)
        resolved: list[str] = []

        async def fake_resolve(host, *, timeout_s):
            resolved.append(host)
            return "192.0.2.7"

        pinged: list[str] = []

        async def fake_ping(destination_ip, *, identifier, sequence, timeout_s):
            pinged.append(destination_ip)
            return 1.0

        monkeypatch.setattr("collector.checks.net_latency.resolve_ipv4", fake_resolve)
        monkeypatch.setattr("collector.checks.net_latency.ping", fake_ping)
        result = await check.run()

        assert resolved == ["switch.lan"]
        assert pinged == ["192.0.2.7"] * 3
        assert result.ok is True
        assert result.labels == {"target": "switch.lan"}

    async def test_resolution_failure_degrades_the_burst_without_pinging(self, monkeypatch):
        settings = load_settings(collector_id="c")
        meter = _FakeMeter()
        check = LatencyCheck(settings, meter=meter, target=_HOSTNAME_TARGET, sample_count=3)

        async def failing_resolve(host, *, timeout_s):
            raise TimeoutError(f"could not resolve {host} within {timeout_s}s")

        pinged: list[str] = []

        async def fake_ping(destination_ip, *, identifier, sequence, timeout_s):
            pinged.append(destination_ip)  # pragma: no cover — must not be reached
            return 1.0

        monkeypatch.setattr("collector.checks.net_latency.resolve_ipv4", failing_resolve)
        monkeypatch.setattr("collector.checks.net_latency.ping", fake_ping)
        result = await check.run()

        assert pinged == []
        assert result.ok is False
        assert result.metrics == {"icmp_loss_pct": 100.0}
        assert "could not resolve switch.lan" in result.error

        rtt_calls = meter.instruments["sentinel_collector_latency_rtt_seconds"].calls
        jitter_calls = meter.instruments["sentinel_collector_latency_jitter_seconds"].calls
        loss_calls = meter.instruments["sentinel_collector_latency_loss_ratio"].calls
        assert rtt_calls == []
        assert jitter_calls == []
        assert loss_calls == [(1.0, {"target_id": "named-switch"})]

    async def test_all_samples_fail_emits_only_loss_ratio(self, monkeypatch):
        settings = load_settings(collector_id="c")
        meter = _FakeMeter()
        check = LatencyCheck(settings, meter=meter, target=_TARGET, sample_count=3)

        async def failing_ping(target, *, identifier, sequence, timeout_s):
            raise TimeoutError("no reply")

        monkeypatch.setattr("collector.checks.net_latency.ping", failing_ping)
        await check.run()

        rtt_calls = meter.instruments["sentinel_collector_latency_rtt_seconds"].calls
        jitter_calls = meter.instruments["sentinel_collector_latency_jitter_seconds"].calls
        loss_calls = meter.instruments["sentinel_collector_latency_loss_ratio"].calls

        assert rtt_calls == []
        assert jitter_calls == []
        assert loss_calls == [(1.0, {"target_id": "core-switch"})]
