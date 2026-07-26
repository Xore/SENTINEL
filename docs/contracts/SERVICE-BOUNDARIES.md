# Service Boundaries and Data Flow

## Site tier

| Service | Owns | Reads | Writes | Must not own |
|---|---|---|---|---|
| Collector | probes, local queue, certificate files | local OS/network/config | OTLP metrics/events to ingest | ML, global routing, alert dispatch |
| Ingest (Go) | collector auth, OTLP validation, PKI enrollment endpoint | certificate/collector registry | VictoriaMetrics, registry/event ingress | anomaly decisions |
| Analyse (Python) | detectors, RCA, ML, health scores | VM time series, PG state | anomaly/RCA/model/event state | public authentication |
| API (Go) | authn/authz, REST/WS, maintenance, evidence orchestration | VM and PG | commands/audit/maintenance | metric ingestion or ML training |
| Site frontend | presentation and operator workflows | API/WS | API commands only | direct DB/VM access |
| Federation agent (Go) | durable global replication and site heartbeat | allow-listed site metrics/events/model updates | global endpoints | local source-of-truth mutation |

## Global tier

| Service | Owns |
|---|---|
| Global ingest/API | authenticated site registry, idempotent event receipt, global query/authz |
| Correlator | recomputable cross-site groups and evidence |
| ML aggregator | authenticated rounds and candidate global models |
| Global frontend | multi-site presentation through global API |

## Critical flows

```text
collector --OTLP/mTLS--> ingest --> VictoriaMetrics
                                --> PostgreSQL registry/events

VictoriaMetrics + PostgreSQL --> analyse --> PostgreSQL anomaly/RCA/model state
                                        --> VictoriaMetrics scores/health

frontend --> API --> VictoriaMetrics/PostgreSQL
                 --> audited operator commands

site VM/PG --> federation agent --mTLS/idempotent--> global tier
```

## Failure invariants

- No global component is on a site-local critical path.
- Ingest outage causes collector buffering, not data loss or collector exit.
- Analyse outage stops new decisions but not ingestion.
- API/frontend outage does not stop ingest or analysis.
- Optional probe failure cannot stop the scheduler.
- An authorization failure never falls back to an unscoped query.
