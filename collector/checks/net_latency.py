"""RTT jitter probe (net_latency) — wraps `net_icmp.ping` with a burst of N
samples per cycle to compute mean RTT, RFC 3550-style jitter, and loss for a
single target in one measurement.
"""
from __future__ import annotations

import asyncio

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.checks.net_icmp import ping, target_identifier
from collector.config import CollectorSettings, LatencyTarget

log = structlog.get_logger()


def compute_jitter_ms(rtts_ms: list[float]) -> float:
    """RFC 3550 §6.4.1-style jitter: mean absolute difference between
    consecutive RTT samples. Needs at least 2 samples; 0.0 otherwise.
    """
    if len(rtts_ms) < 2:
        return 0.0
    diffs = [abs(b - a) for a, b in zip(rtts_ms, rtts_ms[1:], strict=False)]
    return sum(diffs) / len(diffs)


class LatencyCheck(BaseCheck):
    """RTT/jitter burst probe. Configured independently from `IcmpCheck` via
    `LatencyConfig` (its own targets, interval, timeout, sample count) —
    disabled by default so enabling it is a deliberate opt-in to the extra
    packet volume a multi-sample burst adds per cycle, not an automatic
    multiplier on every `IcmpConfig` target.
    """

    name = "net_latency"
    scan_level = 1

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        target: LatencyTarget,
        sample_count: int | None = None,
        *,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self.target = target
        self.sample_count = (
            sample_count if sample_count is not None else config.latency.sample_count
        )
        self.interval_s = config.latency.interval_s
        self._sequence = 0
        self._identifier = target_identifier(target.host)
        # Grouped in one dict (rather than three separate attributes) to
        # keep this class's instance-attribute count reasonable.
        self._gauges = (
            {
                "rtt_seconds": meter.create_gauge(
                    "sentinel_collector_latency_rtt_seconds",
                    description="Mean RTT across the latency probe's sample burst",
                    unit="s",
                ),
                "jitter_seconds": meter.create_gauge(
                    "sentinel_collector_latency_jitter_seconds",
                    description="RFC 3550-style jitter across the latency probe's sample burst",
                    unit="s",
                ),
                "loss_ratio": meter.create_gauge(
                    "sentinel_collector_latency_loss_ratio",
                    description="Sample loss ratio (0.0-1.0) for the latency probe's burst",
                    unit="1",
                ),
            }
            if meter is not None
            else {}
        )

    def is_enabled(self) -> bool:
        return super().is_enabled() and self.config.latency.enabled

    def _record(self, *, rtt_ms: float | None, jitter_ms: float | None, loss_pct: float) -> None:
        attributes = {"target_id": self.target.target_id}
        if rtt_ms is not None and "rtt_seconds" in self._gauges:
            self._gauges["rtt_seconds"].set(rtt_ms / 1000.0, attributes=attributes)
        if jitter_ms is not None and "jitter_seconds" in self._gauges:
            self._gauges["jitter_seconds"].set(jitter_ms / 1000.0, attributes=attributes)
        if "loss_ratio" in self._gauges:
            self._gauges["loss_ratio"].set(loss_pct / 100.0, attributes=attributes)

    async def run(self) -> CheckResult:
        labels = {"target": self.target.host}
        rtts_ms: list[float] = []
        failures = 0

        for _ in range(self.sample_count):
            self._sequence = (self._sequence + 1) % 65536
            try:
                rtt_ms = await ping(
                    self.target.host,
                    identifier=self._identifier,
                    sequence=self._sequence,
                    timeout_s=self.config.latency.timeout_s,
                )
                rtts_ms.append(rtt_ms)
            except Exception as exc:
                failures += 1
                log.warning(
                    "check.degraded", check=self.name, target=self.target.host, error=str(exc)
                )

        loss_pct = (failures / self.sample_count) * 100.0

        if not rtts_ms:
            self._record(rtt_ms=None, jitter_ms=None, loss_pct=loss_pct)
            return CheckResult(
                ok=False,
                metrics={"icmp_loss_pct": loss_pct},
                labels=labels,
                error=f"all {self.sample_count} samples to {self.target.host} failed",
            )

        mean_rtt_ms = sum(rtts_ms) / len(rtts_ms)
        jitter_ms = compute_jitter_ms(rtts_ms)
        self._record(rtt_ms=mean_rtt_ms, jitter_ms=jitter_ms, loss_pct=loss_pct)

        return CheckResult(
            ok=True,
            metrics={
                "icmp_rtt_ms": mean_rtt_ms,
                "icmp_rtt_jitter_ms": jitter_ms,
                "icmp_loss_pct": loss_pct,
            },
            labels=labels,
        )
