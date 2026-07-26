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
from concurrent.futures import ThreadPoolExecutor

# Hard-capped at 2 workers — the Raspberry Pi 3B 5% CPU NFR
# (docs/guides/OPUS-AGENT-GUIDE-V2.md §8) leaves no headroom for more.
_CPU_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="collector-cpu")


async def run_in_thread[**P, R](fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """Run a blocking/CPU-bound function in the shared thread pool."""
    loop = asyncio.get_running_loop()
    call = functools.partial(fn, *args, **kwargs) if kwargs else functools.partial(fn, *args)
    return await loop.run_in_executor(_CPU_POOL, call)
