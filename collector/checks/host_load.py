"""System load average check (host_load) — wraps `os.getloadavg()`.

Not routed through the bounded executor: `getloadavg()` reads an
already-computed kernel average, not a blocking file/subprocess call.
`os.getloadavg` is POSIX-only — it doesn't exist as an attribute on Windows
Python builds (`AttributeError`) and can raise `OSError` if the load average
is otherwise unobtainable, both handled as a normal failed run.

Standalone in this claim: not yet registered by `collector/__main__.py` and
does not create any OTel instrument. Registration and metric emission are a
later, separately reviewed claim (see docs/guides/SONNET-5-WORK-QUEUE.md).
"""

from __future__ import annotations

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
        except OSError as exc:
            log.warning("check.degraded", check=self.name, error=str(exc))
            return CheckResult(ok=False, error=str(exc))

        return CheckResult(
            ok=True,
            metrics={"load1": load1, "load5": load5, "load15": load15},
            labels={},
        )
