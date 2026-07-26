"""Linux process-presence check (host_process) — is one named process
currently running, per `/proc/<pid>/comm`.

One check instance monitors exactly one process name, mirroring the
one-instance-per-target shape of `net_icmp.py`/`net_tcp.py`/etc. — a bounded
process allow-list becomes however many instances a later registration claim
constructs, one per configured name.

Note: the kernel truncates `/proc/<pid>/comm` to 15 characters (`TASK_COMM_LEN`
- 1), so a `process_name` longer than that will never match; this is a
kernel limitation, not a bug in this check.

Standalone in this claim: not yet registered by `collector/__main__.py` and
does not create any OTel instrument. Registration and metric emission are a
later, separately reviewed claim (see docs/guides/SONNET-5-WORK-QUEUE.md).
"""
from __future__ import annotations

import asyncio
import os
import sys

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings
from collector.utils.thread_pool import run_in_thread

log = structlog.get_logger()

DEFAULT_PROC_ROOT = "/proc"


def _is_process_running(proc_root: str, process_name: str) -> bool:
    """True if any PID under `proc_root` reports `process_name` as its
    `comm`. PIDs that vanish or become unreadable mid-scan (a normal race
    when enumerating `/proc`) are skipped, not treated as a hard failure —
    only a failure to list `proc_root` itself propagates.
    """
    for entry in os.listdir(proc_root):
        if not entry.isdigit():
            continue
        comm_path = os.path.join(proc_root, entry, "comm")
        try:
            with open(comm_path, encoding="utf-8", errors="replace") as f:
                comm = f.read().strip()
        except OSError:
            continue
        if comm == process_name:
            return True
    return False


class HostProcessCheck(BaseCheck):
    """Whether one named process is currently running."""

    name = "host_process"
    scan_level = 1
    interval_s = 60.0

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        process_name: str,
        *,
        proc_root: str = DEFAULT_PROC_ROOT,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self.process_name = process_name
        self._proc_root = proc_root

    async def run(self) -> CheckResult:
        if sys.platform != "linux":
            return CheckResult(ok=False, error=f"unsupported platform: {sys.platform}")

        labels = {"process": self.process_name}
        try:
            running = await run_in_thread(_is_process_running, self._proc_root, self.process_name)
        except Exception as exc:  # BaseCheck.run() must never raise
            log.warning(
                "check.degraded", check=self.name, process=self.process_name, error=str(exc)
            )
            return CheckResult(ok=False, labels=labels, error=str(exc))

        if not running:
            return CheckResult(
                ok=False,
                metrics={"process_running": 0.0},
                labels=labels,
                error=f"process {self.process_name!r} not running",
            )
        return CheckResult(ok=True, metrics={"process_running": 1.0}, labels=labels)
