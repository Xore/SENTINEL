"""Tests for collector.health.loop_watchdog — event loop latency detection."""
from __future__ import annotations

import asyncio
import time

import collector.health.loop_watchdog as watchdog_module
from collector.health.loop_watchdog import loop_latency_watchdog


async def test_stops_immediately_when_event_already_set():
    stop_event = asyncio.Event()
    stop_event.set()
    # Would hang forever without a working stop_event check — bounded by
    # the test runner's own timeout if this regresses.
    await loop_latency_watchdog(stop_event=stop_event)


async def test_no_warning_when_loop_not_blocked(monkeypatch, capsys):
    stop_event = asyncio.Event()

    async def fake_sleep_zero(_delay):
        stop_event.set()  # ensure exactly one measurement

    monkeypatch.setattr(watchdog_module.asyncio, "sleep", fake_sleep_zero)
    await loop_latency_watchdog(stop_event=stop_event)

    out = capsys.readouterr().out
    assert "event_loop.blocked" not in out


async def test_warns_when_loop_blocked_beyond_threshold(monkeypatch, capsys):
    stop_event = asyncio.Event()

    async def blocking_sleep_zero(_delay):
        # Genuinely block the loop thread — exactly the scenario this
        # watchdog exists to catch. Faking time.monotonic() instead would
        # also fool asyncio's own internal loop.time() calls (used by
        # wait_for's timeout machinery), since they share the same stdlib
        # time module.
        time.sleep(0.06)  # noqa: ASYNC251 — intentionally blocking, that's the test
        stop_event.set()  # ensure exactly one measurement

    monkeypatch.setattr(watchdog_module.asyncio, "sleep", blocking_sleep_zero)
    await loop_latency_watchdog(stop_event=stop_event)

    out = capsys.readouterr().out
    assert "event_loop.blocked" in out


async def test_custom_threshold_respected(monkeypatch, capsys):
    stop_event = asyncio.Event()

    async def blocking_sleep_zero(_delay):
        time.sleep(0.01)  # noqa: ASYNC251 — intentionally blocking, ~10ms below default threshold
        stop_event.set()

    monkeypatch.setattr(watchdog_module.asyncio, "sleep", blocking_sleep_zero)

    # ...but above a stricter 5ms one.
    await loop_latency_watchdog(stop_event=stop_event, warn_threshold_ms=5.0)

    out = capsys.readouterr().out
    assert "event_loop.blocked" in out
