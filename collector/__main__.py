"""Collector entry point — wires config, PKI enrollment, OTLP/gRPC transport,
and the scheduler together; emits `collector_heartbeat_total` on each cycle.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

import structlog
from opentelemetry.metrics import Meter

from collector.checks import BaseCheck, CheckResult
from collector.checks.net_dns import DnsCheck
from collector.checks.net_http import HttpCheck
from collector.checks.net_icmp import IcmpCheck
from collector.checks.net_latency import LatencyCheck
from collector.checks.net_tcp import TcpCheck
from collector.config import CollectorSettings, ConfigError, install_sighup_reload, load_settings
from collector.health.loop_watchdog import loop_latency_watchdog
from collector.pki.enroll import ensure_enrolled
from collector.scheduler import run_scheduler
from collector.transport.otlp import build_meter_provider, get_meter, shutdown_meter_provider

HEARTBEAT_INTERVAL_S = 30.0


class _HeartbeatCheck(BaseCheck):
    """Internal check emitting the collector heartbeat on its own cycle.

    Emits both `sentinel_collector_heartbeat_total` (canonical, per
    `docs/contracts/METRICS.md`) and `collector_heartbeat_total` (temporary
    Phase 1 compatibility alias, retained until consumers migrate).
    """

    name = "heartbeat"
    scan_level = 1

    def __init__(
        self,
        config: CollectorSettings,
        meter: Meter | None,
        log: structlog.BoundLogger,
        *,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(config, meter, semaphore=semaphore)
        # Read at construction time (not a class-body assignment) so tests
        # can monkeypatch the module-level HEARTBEAT_INTERVAL_S before main()
        # builds this check.
        self.interval_s = HEARTBEAT_INTERVAL_S
        self._log = log
        self._counter = (
            meter.create_counter(
                "sentinel_collector_heartbeat_total",
                description="Collector scheduler heartbeat",
                unit="1",
            )
            if meter is not None
            else None
        )
        self._legacy_counter = (
            meter.create_counter(
                "collector_heartbeat_total",
                description="Collector scheduler heartbeat (temporary compatibility alias)",
                unit="1",
            )
            if meter is not None
            else None
        )

    async def run(self) -> CheckResult:
        if self._counter is not None:
            self._counter.add(1)
        if self._legacy_counter is not None:
            self._legacy_counter.add(1)
        self._log.info("collector.heartbeat")
        return CheckResult(ok=True)


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


async def _close_checks(checks: list[BaseCheck], log: structlog.BoundLogger) -> None:
    """Call `aclose()` on every check during shutdown.

    `aclose()` itself must never raise (same contract as `run()`), but this
    defends anyway: one check's broken close must not stop the others from
    closing or block the rest of shutdown.
    """
    for check in checks:
        try:
            await check.aclose()
        except Exception as exc:  # checks must never raise; defend anyway
            log.warning("check.close_failed", check=check.name, error=str(exc))


def _build_checks(
    settings: CollectorSettings,
    meter: Meter | None,
    log: structlog.BoundLogger,
    *,
    semaphore: asyncio.Semaphore | None,
) -> list[BaseCheck]:
    """One check per target in each enabled probe family, plus heartbeat."""
    checks: list[BaseCheck] = [_HeartbeatCheck(settings, meter, log, semaphore=semaphore)]

    if settings.icmp.enabled:
        for icmp_target in settings.icmp.targets:
            checks.append(IcmpCheck(settings, meter, icmp_target, semaphore=semaphore))

    if settings.tcp.enabled:
        for tcp_target in settings.tcp.targets:
            checks.append(TcpCheck(settings, meter, tcp_target, semaphore=semaphore))

    if settings.http.enabled:
        for http_target in settings.http.targets:
            checks.append(HttpCheck(settings, meter, http_target, semaphore=semaphore))

    if settings.dns.enabled:
        for dns_target in settings.dns.targets:
            for record_type in settings.dns.record_types:
                checks.append(
                    DnsCheck(settings, meter, dns_target, record_type, semaphore=semaphore)
                )

    if settings.latency.enabled:
        for latency_target in settings.latency.targets:
            checks.append(LatencyCheck(settings, meter, latency_target, semaphore=semaphore))

    return checks


def _install_uvloop() -> None:
    """Install uvloop as the default event loop policy on Linux, if
    available. A soft dependency: the collector must run correctly without
    it (Windows dev machines, environments where it isn't installed) — see
    `docs/guides/ASYNCIO-OPTIMIZATION.md` §7.
    """
    if sys.platform != "linux":
        return
    try:
        # Imported here, not at module scope, so the collector still starts
        # on platforms/environments without uvloop installed.
        import uvloop  # pylint: disable=import-outside-toplevel

        uvloop.install()
    except ImportError:
        pass


async def main(*, stop_event: asyncio.Event | None = None) -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"invalid collector configuration: {exc}", file=sys.stderr)
        sys.exit(1)

    _configure_logging(settings.log_level)
    log = structlog.get_logger().bind(collector_id=settings.collector_id, site_id=settings.site_id)

    install_sighup_reload(lambda s: log.info("config.reloaded", scan_level_max=s.scan_level_max))

    log.info("pki.enroll.starting")
    await ensure_enrolled(settings)

    provider = build_meter_provider(settings)
    meter = get_meter(provider)

    semaphore = asyncio.Semaphore(settings.max_concurrent_probes)
    checks = _build_checks(settings, meter, log, semaphore=semaphore)

    if stop_event is None:
        stop_event = asyncio.Event()
    _install_shutdown_signals(stop_event)

    log.info("collector.started", heartbeat_interval_s=HEARTBEAT_INTERVAL_S)
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                run_scheduler(checks, stop_event=stop_event, meter=meter), name="scheduler"
            )
            tg.create_task(loop_latency_watchdog(stop_event=stop_event), name="loop_watchdog")
    finally:
        await _close_checks(checks, log)
        shutdown_meter_provider(provider)
        log.info("collector.shutdown")


if __name__ == "__main__":
    _install_uvloop()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
