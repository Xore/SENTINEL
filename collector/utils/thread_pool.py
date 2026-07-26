"""Shared thread pool for offloading CPU-bound work off the event loop.

Never use this for I/O-bound work (network, disk) — that should stay async.
Reserved for genuinely CPU-bound or legacy-blocking calls (eBPF map
parsing, scapy packet decoding, lmdb compaction). See
`docs/guides/ASYNCIO-OPTIMIZATION.md` §3.
"""
from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable

# On Windows/Python 3.14.5, pylint's bundled typeshed stub for this version
# fails to resolve ThreadPoolExecutor as exported from the concurrent.futures
# package `__init__.pyi` (E0611 no-name-in-module) even though it is the
# stdlib's own documented public import path and imports fine at runtime on
# every platform — a stub/astroid resolution gap, not a real absence.
# Confirmed via Codex's Windows/Python 3.14.5 pylint run (see
# docs/guides/AGENT-COORDINATION.md, S1-02 Codex review 1).
from concurrent.futures import ThreadPoolExecutor  # pylint: disable=no-name-in-module

# Hard-capped at 2 workers — the Raspberry Pi 3B 5% CPU NFR
# (docs/guides/OPUS-AGENT-GUIDE-V2.md §8) leaves no headroom for more.
_CPU_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="collector-cpu")


async def run_in_thread[**P, R](fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """Run a blocking/CPU-bound function in the shared thread pool."""
    loop = asyncio.get_running_loop()
    call = functools.partial(fn, *args, **kwargs) if kwargs else functools.partial(fn, *args)
    return await loop.run_in_executor(_CPU_POOL, call)
