"""Shared thread pool for offloading CPU-bound work off the event loop.

Never use this for I/O-bound work (network, disk) — that should stay async.
Reserved for genuinely CPU-bound or legacy-blocking calls (eBPF map
parsing, scapy packet decoding, lmdb compaction). See
`docs/guides/ASYNCIO-OPTIMIZATION.md` §3.

The worker count is configuration, not a literal. `configure()` is called
once at startup from `CollectorSettings.cpu_pool_workers`; until then the
pool sizes itself from the host's core count. See
`docs/architecture/decisions/0012-collector-reference-hardware.md`.
"""
from __future__ import annotations

import asyncio
import functools
import os
import threading
from collections.abc import Callable

# On Windows/Python 3.14.5, pylint's bundled typeshed stub for this version
# fails to resolve ThreadPoolExecutor as exported from the concurrent.futures
# package `__init__.pyi` (E0611 no-name-in-module) even though it is the
# stdlib's own documented public import path and imports fine at runtime on
# every platform — a stub/astroid resolution gap, not a real absence.
# Confirmed via Codex's Windows/Python 3.14.5 pylint run (see
# docs/guides/AGENT-COORDINATION.md, S1-02 Codex review 1).
from concurrent.futures import ThreadPoolExecutor  # pylint: disable=no-name-in-module

# Upper bound on the auto-derived default. The pool exists to keep blocking
# calls off the loop, not to saturate the node: NFR-02 caps the collector at
# 5% average CPU, so an SFF PC with 32 cores must not get 32 workers just
# because it can. Explicit configuration may still exceed this.
_MAX_AUTO_WORKERS = 8

# Floor for the auto-derived default. Two workers is what the retired
# Raspberry Pi 3B baseline hard-coded; it stays the minimum so a
# single-core or `cpu_count()`-less host still overlaps two blocking reads.
_MIN_AUTO_WORKERS = 2

_lock = threading.Lock()
_pool: ThreadPoolExecutor | None = None
_workers: int | None = None


def default_worker_count() -> int:
    """Worker count derived from the host, used when nothing configures one.

    On the reference Raspberry Pi 5 (four Cortex-A76 cores) this is 4 — twice
    the retired Pi 3B literal, which is the shape of the NFR-02 headroom the
    faster cores bought. A small-form-factor PC lands on the
    `_MAX_AUTO_WORKERS` ceiling rather than its full core count.

    This is a proposal pending measurement on the reference platform, per
    [ADR 0008](../../docs/architecture/decisions/0008-measured-capacity-envelopes.md).
    """
    return min(_MAX_AUTO_WORKERS, max(_MIN_AUTO_WORKERS, os.cpu_count() or _MIN_AUTO_WORKERS))


def configure(max_workers: int) -> None:
    """Size the shared pool. Call once at startup, before any `run_in_thread`.

    Replacing a live pool shuts the old one down without waiting: in-flight
    calls finish on their own threads, and only the pool object is swapped.
    """
    if max_workers < 1:
        raise ValueError(f"cpu pool worker count must be >= 1, got {max_workers}")
    global _pool, _workers  # pylint: disable=global-statement
    with _lock:
        previous, _pool = _pool, None
        _workers = max_workers
    if previous is not None:
        previous.shutdown(wait=False)


def shutdown() -> None:
    """Dispose the shared pool, waiting for in-flight calls to finish."""
    global _pool  # pylint: disable=global-statement
    with _lock:
        previous, _pool = _pool, None
    if previous is not None:
        previous.shutdown(wait=True)


def worker_count() -> int:
    """The pool's current size — configured if set, else auto-derived."""
    return _workers if _workers is not None else default_worker_count()


def _executor() -> ThreadPoolExecutor:
    global _pool  # pylint: disable=global-statement
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=worker_count(), thread_name_prefix="collector-cpu"
            )
        return _pool


async def run_in_thread[**P, R](fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """Run a blocking/CPU-bound function in the shared thread pool."""
    loop = asyncio.get_running_loop()
    call = functools.partial(fn, *args, **kwargs) if kwargs else functools.partial(fn, *args)
    return await loop.run_in_executor(_executor(), call)
