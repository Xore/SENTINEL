"""Collector entry point — wires config, PKI enrollment, OTLP/gRPC transport,
and the scheduler together; emits `collector_heartbeat_total` on each cycle.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time

import structlog

from collector.config import ConfigError, install_sighup_reload, load_settings
from collector.pki.enroll import ensure_enrolled
from collector.scheduler import CheckTask, run_scheduler
from collector.transport.otlp import build_meter_provider, get_meter, shutdown_meter_provider

HEARTBEAT_INTERVAL_S = 30.0


def _log_level(name: str) -> int:
    return getattr(logging, name.upper(), logging.INFO)


def _configure_logging(log_level: str) -> None:
    level = _log_level(log_level)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _install_shutdown_signals(stop_event: asyncio.Event) -> None:
    """Set stop_event on SIGTERM/SIGINT for a graceful shutdown.

    No-op on platforms without `add_signal_handler` (e.g. Windows) — Ctrl+C
    there still raises KeyboardInterrupt, handled at the top level.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            return


async def main(*, stop_event: asyncio.Event | None = None) -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"invalid collector configuration: {exc}", file=sys.stderr)
        sys.exit(1)

    _configure_logging(settings.log_level)
    log = structlog.get_logger().bind(
        collector_id=settings.collector_id, site_id=settings.site_id
    )

    install_sighup_reload(
        lambda s: log.info("config.reloaded", scan_level_max=s.scan_level_max)
    )

    log.info("pki.enroll.starting")
    await ensure_enrolled(settings)

    provider = build_meter_provider(settings)
    meter = get_meter(provider)
    heartbeat_counter = meter.create_counter(
        "collector_heartbeat_total", description="Collector scheduler heartbeat", unit="1"
    )

    async def heartbeat() -> None:
        heartbeat_counter.add(1)
        log.info("collector.heartbeat")

    tasks = [
        CheckTask(
            next_run=time.monotonic(),
            interval_s=HEARTBEAT_INTERVAL_S,
            coro_fn=heartbeat,
            name="heartbeat",
        )
    ]

    if stop_event is None:
        stop_event = asyncio.Event()
    _install_shutdown_signals(stop_event)

    log.info("collector.started", heartbeat_interval_s=HEARTBEAT_INTERVAL_S)
    try:
        await run_scheduler(tasks, stop_event=stop_event)
    finally:
        shutdown_meter_provider(provider)
        log.info("collector.shutdown")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
