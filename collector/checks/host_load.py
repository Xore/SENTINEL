"""System load average check (host_load) — wraps `os.getloadavg()`.

Not routed through the bounded executor: `getloadavg()` reads an
already-computed kernel average, not a blocking file/subprocess call.
`os.getloadavg` is POSIX-only — it doesn't exist as an attribute on Windows
Python builds (`AttributeError`) and can raise `OSError` if the load average
is otherwise unobtainable, both handled as a normal failed run.

Standalone in this claim: not yet registered by `collector/__main__.py` and
does not create any OTel instrument. Registration and metric emission are a
later, separately reviewed claim (see the S3-01B forward package in
docs/guides/AGENT-COORDINATION.md).
"""

from __future__ import annotations

import math
import os

import structlog

from collector.checks import BaseCheck, CheckResult

log = structlog.get_logger()


class HostLoadCheck(BaseCheck):
    """1/5/15-minute load averages."""

    name = "host_load"
    scan_level = 1
    interval_s = 30.0

    async def run(self) -> CheckResult:
        getloadavg = getattr(os, "getloadavg", None)
        if not callable(getloadavg):
            error = "os.getloadavg is unavailable on this platform"
            log.warning("check.degraded", check=self.name, error=error)
            return CheckResult(ok=False, error=error)
        try:
            # Astroid resolves the Windows `os` surface, where the dynamic
            # callable is absent, despite the explicit runtime guard above.
            load1, load5, load15 = getloadavg()  # pylint: disable=not-callable
            averages = (float(load1), float(load5), float(load15))
        except Exception as exc:  # BaseCheck.run() must never raise
            # Broader than `OSError` on purpose: this is a dynamically resolved
            # callable, and an unpacking or conversion failure must still become
            # a failed run rather than escaping into the scheduler.
            log.warning("check.degraded", check=self.name, error=str(exc))
            return CheckResult(ok=False, error=str(exc))

        for value in averages:
            # A load average is a non-negative finite number. NaN would silently
            # poison every downstream aggregate, so fail closed instead.
            if not math.isfinite(value) or value < 0:
                error = f"implausible load average: {value!r}"
                log.warning("check.degraded", check=self.name, error=error)
                return CheckResult(ok=False, error=error)

        return CheckResult(
            ok=True,
            metrics={"load1": averages[0], "load5": averages[1], "load15": averages[2]},
            labels={},
        )
