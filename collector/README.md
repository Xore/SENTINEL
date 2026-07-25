# SENTINEL v2 Collector

A Python 3.12 `asyncio` agent that probes the local network and ships metrics to
the hub via OTLP/gRPC over mTLS. This is the **v2 greenfield rewrite**. The
frozen v1 Go collector lives on the `release/v1.0` branch and the `v1.0` tag.

## Status

Phase 1 (project scaffold) in progress. See the phased plan in
[`../docs/guides/OPUS-AGENT-GUIDE-V2.md`](../docs/guides/OPUS-AGENT-GUIDE-V2.md)
§4 and the primary design spec
[`../docs/collector/COLLECTOR-V2-REFACTOR.md`](../docs/collector/COLLECTOR-V2-REFACTOR.md).

| Piece | Module | Done |
|---|---|---|
| Config (pydantic + YAML + SIGHUP) | `config.py` | ✅ |
| PKI enroll/renew | `pki/` | ☐ |
| Transport (mTLS, OTLP, retry buffer) | `transport/` | ☐ |
| Scheduler (asyncio priority loop) | `scheduler.py` | ☐ |
| Health score | `health/score.py` | ☐ |
| Entry point (heartbeat) | `__main__.py` | ☐ |

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
