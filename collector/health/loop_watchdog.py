"""Event-loop-latency watchdog — detects a blocked asyncio event loop.

Co-schedule alongside `run_scheduler()` in `__main__.py`. Measures how long
a no-op `await asyncio.sleep(0)` actually takes to resume; a high value
means something upstream is blocking the loop. See
`docs/guides/ASYNCIO-OPTIMIZATION.md` §2.
"""
from __future__ import annotations

import asyncio
import time

import structlog

log = structlog.get_logger()

DEFAULT_WARN_THRESHOLD_MS = 50.0
DEFAULT_INTERVAL_S = 1.0


async def loop_latency_watchdog(
    *,
    warn_threshold_ms: float = DEFAULT_WARN_THRESHOLD_MS,
    interval_s: float = DEFAULT_INTERVAL_S,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Log a warning whenever the event loop is blocked longer than
    `warn_threshold_ms`.

    The source pattern in `ASYNCIO-OPTIMIZATION.md` §2 runs `while True`
    with no stop condition — co-scheduling that in an `asyncio.TaskGroup`
    alongside `run_scheduler()` would hang the whole group forever after the
    scheduler exits cleanly, since a `TaskGroup` waits for every child to
    finish. `stop_event` fixes that: the same signal that stops the
    scheduler stops this too.
    """
    while stop_event is None or not stop_event.is_set():
        t0 = time.monotonic()
        await asyncio.sleep(0)  # yield — should resume ~immediately
        latency_ms = (time.monotonic() - t0) * 1000
        if latency_ms > warn_threshold_ms:
            log.warning(
                "event_loop.blocked",
                latency_ms=round(latency_ms, 1),
                threshold_ms=warn_threshold_ms,
            )

        if stop_event is None:
            await asyncio.sleep(interval_s)
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
        except TimeoutError:
            pass
