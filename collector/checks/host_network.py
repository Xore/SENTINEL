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
import re
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

# Linux caps an interface name at `IFNAMSIZ - 1` and forbids whitespace and
# '/'. `interface` is an allowed `METRICS.md` label, so it must still be
# bounded before it can be emitted as one.
MAX_IFNAME_LEN = 15
_INTERFACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def _validate_interface(value: str) -> str:
    """Bound the interface name so it is safe as a metric label."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(
            f"interface must be a non-empty, non-whitespace-padded value: got {value!r}"
        )
    if len(value) > MAX_IFNAME_LEN:
        raise ValueError(
            f"interface must be at most {MAX_IFNAME_LEN} characters (IFNAMSIZ-1): got {value!r}"
        )
    if not _INTERFACE_RE.match(value):
        raise ValueError(
            "interface must start with an alphanumeric character and contain only "
            f"alphanumerics, '.', '_', ':' or '-': got {value!r}"
        )
    return value


def _parse_interface_line(text: str, interface: str) -> tuple[int, int]:
    """Return `(rx_bytes, tx_bytes)` for `interface` from `/proc/net/dev`
    content.

    Fails closed: raises `ValueError` if the interface isn't present, the
    matching line doesn't have the expected field count, or a byte counter is
    non-integer or negative. `/proc/net/dev` counters are unsigned, so a
    negative value means the input is not what it claims to be.
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
        if rx_bytes < 0 or tx_bytes < 0:
            raise ValueError(f"negative /proc/net/dev byte counter for {interface!r}: {line!r}")
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
        self.interface = _validate_interface(interface)
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
            # `CancelledError` is a `BaseException`, so external cancellation
            # still propagates past this handler as the scheduler requires.
            log.warning(
                "check.degraded", check=self.name, interface=self.interface, error=str(exc)
            )
            # The full message can embed the configured path and raw file
            # content, so it stays in the structured log; the result carries
            # only the bounded interface and exception type.
            return CheckResult(ok=False, error=f"{self.interface}: {type(exc).__name__}")

        now = time.monotonic()
        if self._prev is None:
            self._prev = (now, rx_bytes, tx_bytes)
            return CheckResult(ok=True, metrics={}, labels={})

        prev_time, prev_rx, prev_tx = self._prev
        self._prev = (now, rx_bytes, tx_bytes)
        elapsed_s = now - prev_time

        if elapsed_s <= 0 or rx_bytes < prev_rx or tx_bytes < prev_tx:
            # Either no usable interval elapsed, or the kernel's monotonic byte
            # counters went backwards — the interface was recreated, the counter
            # wrapped, or a namespaced `/proc` was swapped underneath us. The
            # baseline above is already refreshed, so skip this interval rather
            # than clamping a negative delta to a 0 B/s "measurement".
            log.info(
                "check.counter_reset",
                check=self.name,
                interface=self.interface,
                elapsed_s=elapsed_s,
                rx_delta=rx_bytes - prev_rx,
                tx_delta=tx_bytes - prev_tx,
            )
            return CheckResult(ok=True, metrics={}, labels={})

        rx_bytes_per_s = (rx_bytes - prev_rx) / elapsed_s
        tx_bytes_per_s = (tx_bytes - prev_tx) / elapsed_s
        return CheckResult(
            ok=True,
            metrics={
                "network_rx_bytes_per_s": rx_bytes_per_s,
                "network_tx_bytes_per_s": tx_bytes_per_s,
            },
            labels={"interface": self.interface},
        )
