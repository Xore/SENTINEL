"""Linux process-presence check (host_process) — is one named process
currently running, per `/proc/<pid>/comm`.

One check instance monitors exactly one process name, mirroring the
one-instance-per-target shape of `net_icmp.py`/`net_tcp.py`/etc. — a bounded
process allow-list becomes however many instances a later registration claim
constructs, one per configured name.

Only the operator-assigned `target_id` may ever reach a metric label
(`docs/contracts/METRICS.md`): the configured process name is an operational
lookup value that stays in structured logs, never in `CheckResult.labels`.

A `found=False` scan is only reported as "not running" when every PID was
inspectable. If part of `/proc` could not be read, absence has not been
established, so the check degrades instead of asserting a false negative.

Standalone in this claim: not yet registered by `collector/__main__.py` and
does not create any OTel instrument. Registration and metric emission are a
later, separately reviewed claim (see the S3-01B forward package in
docs/guides/AGENT-COORDINATION.md).
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from typing import NamedTuple

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings
from collector.utils.thread_pool import run_in_thread

log = structlog.get_logger()

DEFAULT_PROC_ROOT = "/proc"

# The kernel truncates `/proc/<pid>/comm` to `TASK_COMM_LEN - 1` characters, so
# a longer configured name can never match any process. Rejecting it at
# construction turns a permanently-false check into a startup error.
MAX_COMM_LEN = 15

# docs/contracts/METRICS.md's ADR 0009 identifier rule. Duplicated here rather
# than imported from `collector/config.py`, which is frozen under the active
# S2-02 claim; ledger Q-12 proposes consolidating it in S3-01B.
_TARGET_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _validate_target_id(value: str) -> str:
    """The only identifier permitted to become a metric label."""
    if not isinstance(value, str) or not _TARGET_ID_RE.match(value):
        raise ValueError(
            "target_id must be a lowercase RFC 1123 DNS label 1-63 characters "
            f"long, matching [a-z0-9]([a-z0-9-]*[a-z0-9])? (ADR 0009): got {value!r}"
        )
    return value


def _validate_process_name(value: str) -> str:
    """Bound the operational lookup value: non-empty, single-line, printable,
    and short enough that the kernel's `comm` truncation cannot make it
    unmatchable."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(
            f"process_name must be a non-empty, non-whitespace-padded value: got {value!r}"
        )
    if not value.isprintable():
        raise ValueError("process_name must not contain control characters")
    if len(value) > MAX_COMM_LEN:
        raise ValueError(
            f"process_name must be at most {MAX_COMM_LEN} characters — the kernel truncates "
            f"/proc/<pid>/comm to TASK_COMM_LEN-1, so a longer name never matches: got {value!r}"
        )
    return value


class ProcessScan(NamedTuple):
    """Outcome of one `/proc` scan.

    `found=False` with `unreadable > 0` means the process was not seen *and*
    at least one PID could not be inspected, so absence is unproven.
    """

    found: bool
    unreadable: int


def _scan_for_process(proc_root: str, process_name: str) -> ProcessScan:
    """Scan `proc_root` for a PID whose `comm` equals `process_name`.

    A PID that vanishes between `listdir()` and the read is a normal race and
    is skipped silently. A PID that exists but cannot be read (permission,
    I/O error) is counted in `unreadable`, because it could be the process
    being looked for. Failure to list `proc_root` itself propagates.
    """
    unreadable = 0
    for entry in os.listdir(proc_root):
        if not entry.isdigit():
            continue
        comm_path = os.path.join(proc_root, entry, "comm")
        try:
            with open(comm_path, encoding="utf-8", errors="replace") as f:
                comm = f.read().strip()
        except (FileNotFoundError, NotADirectoryError, ProcessLookupError):
            continue  # the process exited mid-scan — a normal /proc race
        except OSError:
            unreadable += 1
            continue
        if comm == process_name:
            return ProcessScan(found=True, unreadable=unreadable)
    return ProcessScan(found=False, unreadable=unreadable)


class HostProcessCheck(BaseCheck):
    """Whether one named process is currently running."""

    name = "host_process"
    scan_level = 1
    interval_s = 60.0

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        target_id: str,
        process_name: str,
        *,
        proc_root: str = DEFAULT_PROC_ROOT,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self.target_id = _validate_target_id(target_id)
        self._process_name = _validate_process_name(process_name)
        self._proc_root = proc_root

    async def run(self) -> CheckResult:
        if sys.platform != "linux":
            return CheckResult(ok=False, error=f"unsupported platform: {sys.platform}")

        labels = {"target_id": self.target_id}
        try:
            scan = await run_in_thread(_scan_for_process, self._proc_root, self._process_name)
        except Exception as exc:  # BaseCheck.run() must never raise
            # `CancelledError` is a `BaseException`, so external cancellation
            # still propagates past this handler as the scheduler requires.
            log.warning(
                "check.degraded",
                check=self.name,
                target_id=self.target_id,
                process=self._process_name,
                error=str(exc),
            )
            return CheckResult(
                ok=False, labels=labels, error=f"{self.target_id}: {type(exc).__name__}"
            )

        if scan.found:
            return CheckResult(ok=True, metrics={"process_running": 1.0}, labels=labels)

        if scan.unreadable:
            # Not observed, but not proven absent either: emit no
            # `process_running` sample rather than a possibly false zero.
            log.warning(
                "check.degraded",
                check=self.name,
                target_id=self.target_id,
                process=self._process_name,
                unreadable_pids=scan.unreadable,
            )
            return CheckResult(
                ok=False,
                labels=labels,
                error=(
                    f"{self.target_id}: absence unproven — "
                    f"{scan.unreadable} PID(s) could not be inspected"
                ),
            )

        return CheckResult(
            ok=False,
            metrics={"process_running": 0.0},
            labels=labels,
            error=f"{self.target_id}: process not running",
        )
