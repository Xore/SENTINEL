# asyncio Event Loop Optimization — Collector Reference

> **Audience:** Claude Opus agent and human contributors implementing or debugging the SENTINEL v2 collector.
> **Cross-reference:** OPUS-AGENT-GUIDE-V2.md §12 → this document.
> **Date:** 2026-07-26

---

## 1. The Golden Rule: Never Block the Loop

The asyncio event loop is single-threaded. One blocking call freezes **all** concurrent checks for its entire duration. Every check coroutine must yield control back to the loop within a few milliseconds at most.

| Blocking anti-pattern | Correct async replacement |
|---|---|
| `time.sleep(n)` | `await asyncio.sleep(n)` |
| `subprocess.run()` / `Popen()` | `await asyncio.create_subprocess_exec()` (OPUS-AGENT-GUIDE-V2 §5.4) |
| `requests.get()` | `await aiohttp.ClientSession().get()` |
| `socket.connect()` | `await asyncio.open_connection()` |
| CPU-heavy loop (>5 ms) | `await loop.run_in_executor(None, fn)` |
| Blocking file I/O | `await asyncio.to_thread(open, ...)` (Python 3.9+) |
| `dns.resolver.resolve()` (sync) | `await dns.asyncresolver.resolve()` (dnspython async API) |

---

## 2. Detect Blocking with a Watchdog Coroutine

Measure event loop latency by scheduling a no-op `await asyncio.sleep(0)` and timing how long it takes to actually resume. A high value means something upstream is blocking the loop.

```python
# collector/health/loop_watchdog.py
import asyncio
import time
import structlog

log = structlog.get_logger()

async def loop_latency_watchdog(
    warn_threshold_ms: float = 50.0,
    interval_s: float = 1.0,
) -> None:
    """
    Co-schedule this alongside run_scheduler() in __main__.py.
    Emits a structured warning whenever the loop is blocked > warn_threshold_ms.
    """
    while True:
        t0 = time.monotonic()
        await asyncio.sleep(0)          # yield — should resume ~immediately
        latency_ms = (time.monotonic() - t0) * 1000
        if latency_ms > warn_threshold_ms:
            log.warning(
                "event_loop.blocked",
                latency_ms=round(latency_ms, 1),
                threshold_ms=warn_threshold_ms,
            )
        await asyncio.sleep(interval_s)
```

**Wire it in `__main__.py`:**

```python
async def main() -> None:
    # ... setup ...
    stop = asyncio.Event()
    async with asyncio.TaskGroup() as tg:
        tg.create_task(run_scheduler(checks, stop_event=stop))
        tg.create_task(loop_latency_watchdog())   # always co-scheduled
        tg.create_task(_sigterm_watcher(stop))
```

**Rule:** `warn_threshold_ms=50` is the correct default. The ≤30s full-cycle NFR (OPUS-AGENT-GUIDE-V2 §8) means any single blocking call >50ms is worth investigating.

---

## 3. Offload CPU-Bound Work to a Thread Pool

eBPF map reads, scapy packet parsing, and lmdb compaction can spike CPU. Use `run_in_executor` to keep them off the event loop thread.

```python
# collector/utils/thread_pool.py
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Shared pool — worker count belongs in CollectorSettings, defaulted for the
# reference Pi 5. The literal 2 below came from the retired Pi 3B baseline and
# is now the collector's tightest limit; see ADR 0012.
_CPU_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="collector-cpu")

async def run_in_thread(fn, *args):
    """Run a blocking/CPU-bound function in the shared thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_CPU_POOL, fn, *args)
```

**Usage in a check:**

```python
from collector.utils.thread_pool import run_in_thread

async def run(self) -> CheckResult:
    try:
        parsed = await run_in_thread(self._parse_bpf_map)
        return CheckResult(ok=True, metrics=parsed, labels={})
    except Exception as e:
        return CheckResult(ok=False, error=str(e))
```

**Rule:** Never use more than 2 threads. Never run I/O-bound work in the thread pool — only CPU-bound or legacy blocking calls.

---

## 4. Semaphore: Cap Concurrent Outbound Connections

Running enough probes simultaneously exhausts file descriptors on any node. A shared semaphore caps total concurrent network operations across all checks. The count at which this bites moved up with the hardware baseline ([ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md)), but the mechanism is unchanged — the cap exists to make the limit deliberate rather than discovered at runtime.

```python
# collector/checks/__init__.py — add alongside BaseCheck
import asyncio

# Shared across all check instances — 20 concurrent network ops max
_NET_SEMAPHORE = asyncio.Semaphore(20)

class BaseCheck(ABC):
    ...
    async def run_with_semaphore(self) -> CheckResult:
        """Called by the scheduler instead of run() directly."""
        async with _NET_SEMAPHORE:
            return await self.run()
```

**Update `scheduler.py` `_run_one`:**

```python
async def _run_one(task: CheckTask) -> CheckResult:
    result = await task.check.run_with_semaphore()   # was: task.check.run()
    ...
```

**Rule:** the semaphore value must be a `CollectorSettings` field, never a hard-coded literal. The default of 20 was derived from the retired Pi 3B baseline and is due to be re-derived for the reference Pi 5 ([ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md)). 50 was already the suggested value for higher-spec nodes, and the reference platform is now firmly in that class.

---

## 5. aiohttp Session: Reuse, Don't Recreate

Creating a new `aiohttp.ClientSession` per HTTP probe is expensive — it creates a new TCP connection pool and re-resolves DNS every time. Create one session per check class at first use.

```python
# collector/checks/net_http.py
import aiohttp
from collector.checks import BaseCheck, CheckResult

class HttpCheck(BaseCheck):
    name = "net_http"
    scan_level = 1
    timeout_s: float = 10.0
    _session: aiohttp.ClientSession | None = None

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            connector = aiohttp.TCPConnector(
                limit=10,            # max concurrent connections in this pool
                ttl_dns_cache=300,   # cache DNS results for 5 minutes
            )
            cls._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=cls.timeout_s),
            )
        return cls._session

    async def run(self) -> CheckResult:
        try:
            session = await self.get_session()
            t0 = asyncio.get_event_loop().time()
            async with session.get(self.config.http_target) as resp:
                elapsed_ms = (asyncio.get_event_loop().time() - t0) * 1000
                return CheckResult(
                    ok=resp.status < 500,
                    metrics={"http_response_ms": round(elapsed_ms, 1)},
                    labels={"target": self.config.http_target, "status": str(resp.status)},
                )
        except asyncio.TimeoutError:
            return CheckResult(ok=False, error=f"timeout after {self.timeout_s}s")
        except Exception as e:
            return CheckResult(ok=False, error=str(e))
```

---

## 6. Per-Check Timeout: Always Wrap in `asyncio.wait_for`

Every check must have its own explicit timeout. Never rely on the OS, the remote host, or the library's default.

```python
# Pattern — apply in every BaseCheck.run() implementation
async def run(self) -> CheckResult:
    try:
        return await asyncio.wait_for(self._do_check(), timeout=self.timeout_s)
    except asyncio.TimeoutError:
        return CheckResult(ok=False, error=f"timeout after {self.timeout_s}s")
    except Exception as e:
        return CheckResult(ok=False, error=str(e))
```

**Default timeout values by check type:**

| Check | `timeout_s` | Rationale |
|---|---|---|
| `net_icmp` | 2.0 | RTT > 2s is anomalous on local network |
| `net_tcp` | 5.0 | TCP SYN timeout |
| `net_http` | 10.0 | Allow for slow TLS handshake |
| `net_dns` | 3.0 | DNS should resolve within 3s |
| `net_snmp` | 10.0 | SNMP WALK on large MIB can be slow |
| `net_modbus` | 5.0 | OT devices tolerate up to 5s |
| `net_mtr` | 15.0 | Multiple TTL hops |
| `net_wifi_linux` | 5.0 | `iw scan` can block briefly |

---

## 7. uvloop: Drop-in Speed Boost (Linux Only, Optional)

`uvloop` is a libuv-based replacement for the default asyncio event loop. It provides 2–4× throughput improvement on I/O-heavy workloads with zero code changes beyond installation.

```python
# collector/__main__.py — call before asyncio.run()
import sys

def _install_uvloop() -> None:
    """Install uvloop as the default event loop policy on Linux. No-op otherwise."""
    if sys.platform != "linux":
        return
    try:
        import uvloop
        uvloop.install()  # replaces asyncio.DefaultEventLoopPolicy globally
    except ImportError:
        pass              # graceful degradation — stdlib event loop is fine

_install_uvloop()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

**`requirements.txt` entry (Linux-only conditional):**

```
uvloop==0.21.0; sys_platform == "linux"
```

**Rule:** `uvloop` is a soft dependency. The collector must run correctly without it (Windows dev machines, macOS CI). The import guard ensures this. Never make `uvloop` a hard requirement.

---

## 8. TaskGroup vs gather() — Why TaskGroup Wins

This project uses `asyncio.TaskGroup` (§5.8 in OPUS-AGENT-GUIDE-V2) rather than `asyncio.gather()`. The key difference:

| | `asyncio.gather()` | `asyncio.TaskGroup` |
|---|---|---|
| Unhandled exception | Cancels siblings; exception silently dropped unless you inspect return values | Re-raises immediately as `ExceptionGroup`; impossible to miss |
| Cancellation | Manual | Automatic on any child failure |
| Python version | 3.4+ | 3.11+ (stdlib) |
| Structured concurrency | No | Yes (PEP 654) |

**Never use `asyncio.gather()` in the scheduler.** It is acceptable inside a single check's `run()` method when fanning out sub-operations (e.g., pinging multiple targets), but always with explicit error handling on the returned results.

---

## 9. Common asyncio Mistakes in This Codebase

| Mistake | Symptom | Fix |
|---|---|---|
| `time.sleep()` in a coroutine | `event_loop.blocked` warning > 1000ms; all checks stall | `await asyncio.sleep()` |
| No timeout on a probe | Check hangs indefinitely; semaphore slot never released; cycle exceeds 30s | Wrap in `asyncio.wait_for(self._do_check(), timeout=self.timeout_s)` |
| New `aiohttp.ClientSession` per call | Memory leak; connection pool exhaustion after ~100 probes | Class-level session singleton (§5 above) |
| `asyncio.gather()` in scheduler | Silent exception swallow; broken check goes undetected | `asyncio.TaskGroup` (OPUS-AGENT-GUIDE-V2 §5.8) |
| Blocking DNS in `net_dns.py` | Event loop stalls during DNS resolution | Use `dns.asyncresolver.resolve()` from dnspython |
| CPU work on loop thread | `event_loop.blocked` warnings; CPU usage spikes | `await run_in_thread(fn)` (§3 above) |
| Thread pool > 2 workers on Pi | Exceeds 5% CPU NFR under load | Hard cap at 2 in `ThreadPoolExecutor(max_workers=2)` |

---

## 10. References

- Python docs — [Developing with asyncio](https://docs.python.org/3/library/asyncio-dev.html)
- Python docs — [Coroutines and Tasks](https://docs.python.org/3/library/asyncio-task.html)
- Mergify blog — [Detecting Blocking Tasks in Asyncio by Measuring Event Loop Latency](https://mergify.com/blog/detecting-blocking-tasks-in-asyncio-by-measuring-event-loop-latency)
- DSi Blog — [Python async patterns for high-throughput backend systems (2025)](https://www.dsinnovators.com/blog/python/python-async-patterns-backend-2025/)
- oneuptime — [How to Use asyncio Effectively for I/O-Bound Workloads (2025)](https://oneuptime.com/blog/post/2025-01-06-python-asyncio-io-bound/view)
- Medium — [Async Python 2025: Fast, Safe, and Under Control — uvloop + TaskGroups](https://medium.com/@hadiyolworld007/async-python-2025-fast-safe-and-under-control-ee2c0e2b2bf6)
- dhirendrabiswal.com — [Advanced Python Concurrency: Asyncio Event Loop Optimization (2025)](https://dhirendrabiswal.com/advanced-python-concurrency-asyncio-event-loop-optimization-and-concurrent-futures-patterns/)
- arXiv:2411.16254 — [Asynchronous I/O — With Great Power Comes Great Responsibility (2024)](https://arxiv.org/abs/2411.16254)
