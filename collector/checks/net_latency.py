"""RTT jitter probe (net_latency) — wraps `net_icmp.ping` with a burst of N
samples per cycle to compute mean RTT, RFC 3550-style jitter, and loss for a
single target in one measurement.
"""
from __future__ import annotations

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.checks.net_icmp import ping, target_identifier
from collector.config import CollectorSettings

log = structlog.get_logger()

DEFAULT_SAMPLE_COUNT = 5


def compute_jitter_ms(rtts_ms: list[float]) -> float:
    """RFC 3550 §6.4.1-style jitter: mean absolute difference between
    consecutive RTT samples. Needs at least 2 samples; 0.0 otherwise.
    """
    if len(rtts_ms) < 2:
        return 0.0
    diffs = [abs(b - a) for a, b in zip(rtts_ms, rtts_ms[1:], strict=False)]
    return sum(diffs) / len(diffs)


class LatencyCheck(BaseCheck):
    name = "net_latency"
    scan_level = 1

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter,
        target: str,
        sample_count: int = DEFAULT_SAMPLE_COUNT,
    ) -> None:
        super().__init__(config, meter)
        self.target = target
        self.sample_count = sample_count
        self._sequence = 0
        self._identifier = target_identifier(target)

    async def run(self) -> CheckResult:
        labels = {"target": self.target}
        rtts_ms: list[float] = []
        failures = 0

        for _ in range(self.sample_count):
            self._sequence = (self._sequence + 1) % 65536
            try:
                rtt_ms = await ping(
                    self.target,
                    identifier=self._identifier,
                    sequence=self._sequence,
                    timeout_s=self.config.icmp.timeout_s,
                )
                rtts_ms.append(rtt_ms)
            except Exception as exc:
                failures += 1
                log.warning(
                    "check.degraded", check=self.name, target=self.target, error=str(exc)
                )

        loss_pct = (failures / self.sample_count) * 100.0

        if not rtts_ms:
            return CheckResult(
                ok=False,
                metrics={"icmp_loss_pct": loss_pct},
                labels=labels,
                error=f"all {self.sample_count} samples to {self.target} failed",
            )

        return CheckResult(
            ok=True,
            metrics={
                "icmp_rtt_ms": sum(rtts_ms) / len(rtts_ms),
                "icmp_rtt_jitter_ms": compute_jitter_ms(rtts_ms),
                "icmp_loss_pct": loss_pct,
            },
            labels=labels,
        )
