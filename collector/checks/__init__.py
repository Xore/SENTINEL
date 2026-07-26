"""Base check interface — every probe module implements `BaseCheck`.

`run()` must never raise: catch every exception internally and return
`CheckResult(ok=False, error=str(exc))`. `collector.scheduler` tolerates a
raising task via a done-callback so the scheduler itself survives, but a
check that raises still loses its structured result (metrics/labels) for
that cycle — checks own this contract too, not just the scheduler.
"""
from __future__ import annotations

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

    def __init__(self, config: CollectorSettings, meter: Meter) -> None:
        self.config = config
        self.meter = meter

    @abstractmethod
    async def run(self) -> CheckResult:
        """Execute the check.

        Must be non-blocking (async) and must never raise — catch every
        exception internally and return `CheckResult(ok=False, error=...)`.
        """

    def is_enabled(self) -> bool:
        """False if this check should be skipped on this node."""
        return self.config.scan_level_max >= self.scan_level
