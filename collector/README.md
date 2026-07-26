# SENTINEL v2 Collector

A Python 3.12 `asyncio` agent that probes the local network and ships metrics to
the hub via OTLP/gRPC over mTLS. This is the **v2 greenfield rewrite**. The
frozen v1 Go collector lives on the `release/v1.0` branch and the `v1.0` tag.

## Status

Phase 1 (project scaffold) complete. Phase 2 (core network probes) complete.
Scheduler and check base class also incorporate the `asyncio.TaskGroup` /
semaphore / shared-session patterns from
[`../docs/guides/ASYNCIO-OPTIMIZATION.md`](../docs/guides/ASYNCIO-OPTIMIZATION.md).
See the phased plan in
[`../docs/guides/OPUS-AGENT-GUIDE-V2.md`](../docs/guides/OPUS-AGENT-GUIDE-V2.md)
§4 and the primary design spec
[`../docs/collector/COLLECTOR-V2-REFACTOR.md`](../docs/collector/COLLECTOR-V2-REFACTOR.md).

| Piece | Module | Done |
|---|---|---|
| Config (pydantic + YAML + SIGHUP) | `config.py` | ✅ |
| PKI enroll | `pki/enroll.py` | ✅ |
| PKI renew | `pki/renew.py` | ☐ |
| Transport (mTLS, OTLP) | `transport/mtls.py`, `transport/otlp.py` | ✅ |
| Transport retry buffer | `transport/retry.py` | ☐ |
| Scheduler (`asyncio.TaskGroup`, per-check interval) | `scheduler.py` | ✅ |
| Event loop latency watchdog | `health/loop_watchdog.py` | ✅ |
| Health score | `health/score.py` | ☐ |
| Shared CPU-bound thread pool | `utils/thread_pool.py` | ✅ |
| Entry point (heartbeat, uvloop, TaskGroup) | `__main__.py` | ✅ |
| Check base class (semaphore-capped) | `checks/__init__.py` | ✅ |
| ICMP echo probe | `checks/net_icmp.py` | ✅ |
| TCP connect probe | `checks/net_tcp.py` | ✅ |
| HTTP/HTTPS probe (shared session) | `checks/net_http.py` | ✅ |
| DNS resolution probe | `checks/net_dns.py` | ✅ |
| RTT jitter probe | `checks/net_latency.py` | ✅ |
| OS health (CPU/mem/disk/net) | `os_health/` | ☐ |

## Development

```bash
cd collector
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

## Configuration

Config resolves in precedence order (highest wins): explicit kwargs → process
env / `.env` → optional YAML file (`COLLECTOR_CONFIG` or passed path) → defaults.
Nested env vars use the `__` delimiter, e.g. `WIFI__ENABLED=false`,
`BACKEND__URL=https://hub:4317`. The full schema is in `config.py` and mirrors
`COLLECTOR-V2-REFACTOR.md` §9. `collector_id` is the only required field.
