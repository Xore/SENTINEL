"""systemd service-status check (host_service) — `systemctl is-active
<service>` for one configured service, mirroring `host_process.py`'s
one-instance-per-name shape.

Uses `asyncio.create_subprocess_exec` directly rather than the bounded
thread pool: subprocess spawning/communication is genuinely async I/O via
the event loop, not a blocking call needing the executor.

Three properties this module owes the rest of the collector:

* **No orphaned child.** The `systemctl` process is killed and reaped on every
  exit path — timeout, error, and external cancellation alike.
* **Bounded labels.** Only the operator-assigned `target_id` reaches
  `CheckResult.labels`; the unit name stays in structured logs
  (`docs/contracts/METRICS.md`).
* **Inactive is not the same as unknown.** A state systemd actually reported is
  a measurement; a missing binary, a manager/permission failure, or an
  unrecognized token is a degraded check that emits no state sample.

Standalone in this claim: not yet registered by `collector/__main__.py` and
does not create any OTel instrument. Registration and metric emission are a
later, separately reviewed claim (see docs/guides/SONNET-5-WORK-QUEUE.md).
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import re
import sys

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.config import CollectorSettings

log = structlog.get_logger()

DEFAULT_TIMEOUT_S = 5.0

# systemd's documented unit-name length limit.
MAX_UNIT_NAME_LEN = 255

ACTIVE_STATE = "active"

# `systemctl is-active` prints exactly one of these tokens for a unit it can
# report on. Anything else — empty output, `unknown`, a D-Bus/manager error —
# means the state was not determined, which this module treats as degraded
# rather than silently as "not active".
KNOWN_INACTIVE_STATES = frozenset(
    {"inactive", "deactivating", "activating", "reloading", "failed", "maintenance"}
)

# docs/contracts/METRICS.md's ADR 0009 identifier rule. Duplicated here rather
# than imported from `collector/config.py`, which is frozen under the active
# S2-02 claim; ledger Q-12 proposes consolidating it in S3-01B.
_TARGET_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

# systemd unit names use alphanumerics plus ":-_.\" and "@" for templates. The
# leading character must be alphanumeric so a configured name can never be
# parsed by `systemctl` as an option, even before the `--` separator below.
_SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.@\\-]*$")


def _validate_target_id(value: str) -> str:
    """The only identifier permitted to become a metric label."""
    if not isinstance(value, str) or not _TARGET_ID_RE.match(value):
        raise ValueError(
            "target_id must be a lowercase RFC 1123 DNS label 1-63 characters "
            f"long, matching [a-z0-9]([a-z0-9-]*[a-z0-9])? (ADR 0009): got {value!r}"
        )
    return value


def _validate_service_name(value: str) -> str:
    """Bound the operational unit name: printable, option-safe, length-capped."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(
            f"service_name must be a non-empty, non-whitespace-padded value: got {value!r}"
        )
    if len(value) > MAX_UNIT_NAME_LEN:
        raise ValueError(
            f"service_name must be at most {MAX_UNIT_NAME_LEN} characters: got {len(value)}"
        )
    if not _SERVICE_NAME_RE.match(value):
        raise ValueError(
            "service_name must start with an alphanumeric character and contain only "
            rf"alphanumerics, ':', '_', '.', '@', '\' or '-': got {value!r}"
        )
    return value


def _validate_timeout(value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"timeout_s must be a number: got {value!r}")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"timeout_s must be a positive finite number: got {value!r}")
    return float(value)


async def _reap(proc: asyncio.subprocess.Process) -> None:
    """Wait for an already-killed child so it cannot linger as a zombie."""
    with contextlib.suppress(Exception):
        await proc.wait()


async def _kill_and_reap(proc: asyncio.subprocess.Process) -> None:
    """Kill and collect the child, safely from a cancellation path.

    An already-cancelled coroutine is cancelled again the instant it awaits,
    so the reap runs as a shielded task. On the timeout/error path the shielded
    await completes normally; on the cancellation path the `CancelledError` from
    the await is suppressed here — the reap task keeps running to completion in
    the background, and the caller re-raises the original cancellation itself.
    Either way `kill()` has already happened synchronously, so no `systemctl`
    process survives the check.
    """
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()
    reap = asyncio.ensure_future(_reap(proc))
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.shield(reap)


async def _query_service_state(service_name: str, *, timeout_s: float) -> str:
    """Return the state token `systemctl is-active` reports for `service_name`.

    Raises `RuntimeError` when no state could be determined (`systemctl`
    missing, manager or permission failure, unrecognized token) and
    `TimeoutError` if the command outlives `timeout_s`. The child is killed and
    reaped on every failure path, including external cancellation.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "is-active",
            "--",
            service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("systemctl not found") from exc

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except BaseException:
        # Every exit other than a clean completion — timeout, transport error,
        # or the enclosing task being cancelled — must still reap the child.
        await _kill_and_reap(proc)
        raise

    state = stdout.decode(errors="replace").strip()
    if state == ACTIVE_STATE or state in KNOWN_INACTIVE_STATES:
        return state

    log.warning(
        "check.service_state_undetermined",
        service=service_name,
        returncode=proc.returncode,
        stderr=stderr.decode(errors="replace").strip()[:200],
    )
    raise RuntimeError(
        f"systemctl reported no usable state (exit {proc.returncode}, state {state[:32]!r})"
    )


class HostServiceCheck(BaseCheck):
    """Whether one named systemd service is currently active."""

    name = "host_service"
    scan_level = 1
    interval_s = 60.0

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        target_id: str,
        service_name: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        self.target_id = _validate_target_id(target_id)
        self._service_name = _validate_service_name(service_name)
        self._timeout_s = _validate_timeout(timeout_s)

    async def run(self) -> CheckResult:
        if sys.platform != "linux":
            return CheckResult(ok=False, error=f"unsupported platform: {sys.platform}")

        labels = {"target_id": self.target_id}
        try:
            state = await _query_service_state(self._service_name, timeout_s=self._timeout_s)
        except Exception as exc:  # BaseCheck.run() must never raise
            # `CancelledError` is a `BaseException`, so external cancellation
            # still propagates past this handler as the scheduler requires —
            # after `_kill_and_reap()` has already dealt with the child.
            log.warning(
                "check.degraded",
                check=self.name,
                target_id=self.target_id,
                service=self._service_name,
                error=str(exc),
            )
            return CheckResult(
                ok=False, labels=labels, error=f"{self.target_id}: {type(exc).__name__}"
            )

        if state == ACTIVE_STATE:
            return CheckResult(ok=True, metrics={"service_active": 1.0}, labels=labels)
        return CheckResult(
            ok=False,
            metrics={"service_active": 0.0},
            labels=labels,
            error=f"{self.target_id}: service state {state!r}",
        )
