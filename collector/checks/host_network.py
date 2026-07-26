"""Linux network interface throughput check (host_network) — computes
RX/TX byte rate from the delta between two consecutive `/proc/net/dev`
samples across scheduler cycles, mirroring `host_cpu`'s jiffies-delta
approach.

Standalone in this claim: not yet registered by `collector/__main__.py` and
does not create any OTel instrument. Registration and metric emission are a
later, separately reviewed claim (see docs/guides/SONNET-5-WORK-QUEUE.md).
"""
from __future__ import annotations

import asyncio
import sys
import time

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings
from collector.utils.thread_pool import run_in_thread

log = structlog.get_logger()

DEFAULT_NET_DEV_PATH = "/proc/net/dev"
DEFAULT_INTERFACE = "eth0"


def _parse_interface_line(text: str, interface: str) -> tuple[int, int]:
    """Return `(rx_bytes, tx_bytes)` for `interface` from `/proc/net/dev`
    content. Raises `ValueError` if the interface isn't present or the
    matching line doesn't have the expected field count.
    """
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        if name.strip() != interface:
            continue
        fields = rest.split()
        if len(fields) < 9:
            raise ValueError(f"unexpected /proc/net/dev fields for {interface!r}: {line!r}")
        try:
            rx_bytes = int(fields[0])
            tx_bytes = int(fields[8])
        except ValueError as exc:
            raise ValueError(f"non-integer /proc/net/dev field for {interface!r}") from exc
        return rx_bytes, tx_bytes
    raise ValueError(f"interface {interface!r} not found in /proc/net/dev")


def _read_interface_counters(path: str, interface: str) -> tuple[int, int]:
    with open(path, encoding="ascii") as f:
        return _parse_interface_line(f.read(), interface)


class HostNetworkCheck(BaseCheck):
    """RX/TX byte rate for one configured interface.

    The first `run()` after construction has no prior sample to diff
    against, so it records a baseline and reports success with no metrics
    yet — a rate is only meaningful across an interval.
    """

    name = "host_network"
    scan_level = 1
    interval_s = 30.0

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        *,
        interface: str = DEFAULT_INTERFACE,
        net_dev_path: str = DEFAULT_NET_DEV_PATH,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self.interface = interface
        self._net_dev_path = net_dev_path
        self._prev: tuple[float, int, int] | None = None

    async def run(self) -> CheckResult:
        if sys.platform != "linux":
            return CheckResult(ok=False, error=f"unsupported platform: {sys.platform}")

        try:
            rx_bytes, tx_bytes = await run_in_thread(
                _read_interface_counters, self._net_dev_path, self.interface
            )
        except Exception as exc:  # BaseCheck.run() must never raise
            log.warning(
                "check.degraded", check=self.name, interface=self.interface, error=str(exc)
            )
            return CheckResult(ok=False, error=str(exc))

        now = time.monotonic()
        if self._prev is None:
            self._prev = (now, rx_bytes, tx_bytes)
            return CheckResult(ok=True, metrics={}, labels={})

        prev_time, prev_rx, prev_tx = self._prev
        self._prev = (now, rx_bytes, tx_bytes)
        elapsed_s = now - prev_time

        if elapsed_s <= 0:
            error = f"non-positive elapsed time since previous sample: {elapsed_s}"
            log.warning("check.degraded", check=self.name, error=error)
            return CheckResult(ok=False, error=error)

        rx_bytes_per_s = max(0.0, (rx_bytes - prev_rx) / elapsed_s)
        tx_bytes_per_s = max(0.0, (tx_bytes - prev_tx) / elapsed_s)
        return CheckResult(
            ok=True,
            metrics={
                "network_rx_bytes_per_s": rx_bytes_per_s,
                "network_tx_bytes_per_s": tx_bytes_per_s,
            },
            labels={"interface": self.interface},
        )
