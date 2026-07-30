"""Base check interface — every probe module implements `BaseCheck`.

`run()` must never raise: catch every exception internally and return
`CheckResult(ok=False, error=str(exc))`. `collector.scheduler` runs checks
inside an `asyncio.TaskGroup`, which cancels every sibling and re-raises as
`ExceptionGroup` on an unhandled exception — that is a safety net for bugs
that bypass this contract, not the primary error boundary. Checks own the
contract too, not just the scheduler.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from opentelemetry.metrics import Meter

from collector.config import CollectorSettings


@dataclass
class CheckResult:
    ok: bool
    metrics: dict[str, float | int] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    error: str | None = None


class BaseCheck(ABC):
    name: str
    scan_level: int
    interval_s: float = 30.0

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        *,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self.config = config
        self.meter = meter
        self.semaphore = semaphore

    @abstractmethod
    async def run(self) -> CheckResult:
        """Execute the check.

        Must be non-blocking (async) and must never raise — catch every
        exception internally and return `CheckResult(ok=False, error=...)`.
        """

    async def run_with_semaphore(self) -> CheckResult:
        """What the scheduler calls instead of `run()` directly.

        Bounds total concurrent network operations across every check via a
        shared `asyncio.Semaphore` (sized from
        `CollectorSettings.max_concurrent_probes`), so a burst of due checks
        can't exhaust file descriptors on a constrained node — the reference
        platform is a Raspberry Pi 5 (ADR 0012), but the cap exists to make
        the limit deliberate rather than discovered at runtime, on any node.
        A no-op passthrough if no semaphore was supplied —
        constructing a check directly, as most unit tests do, doesn't need
        one.
        """
        if self.semaphore is None:
            return await self.run()
        async with self.semaphore:
            return await self.run()

    def is_enabled(self) -> bool:
        """False if this check should be skipped on this node."""
        return self.config.scan_level_max >= self.scan_level

    async def aclose(self) -> None:  # noqa: B027 — intentional default no-op, not abstract
        """Release any resource this check owns (sessions, sockets, file
        handles). Called once per check during collector shutdown.

        Default is a no-op — most checks own nothing beyond `self.config`/
        `self.meter`. Override when a check holds something that needs an
        explicit close (e.g. `checks.net_http.HttpCheck`'s shared
        `aiohttp.ClientSession`). Must itself never raise, for the same
        reason `run()` must never raise: one check's shutdown failure must
        not stop the rest of the collector from shutting down cleanly.
        """
