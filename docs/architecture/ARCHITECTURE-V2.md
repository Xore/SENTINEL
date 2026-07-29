# SENTINEL v2 Architecture

> **Moved.** This file has been consolidated into [`ARCHITECTURE-V2-EXTENDED.md`](ARCHITECTURE-V2-EXTENDED.md).
>
> `ARCHITECTURE-V2-EXTENDED.md` is the single authoritative v2 architecture document. It covers:
> - Single-site baseline (50-collector, single-server Docker Compose)
> - Service decomposition: collector (Go), ingest (Go), analyse (Python), api (Go/Gin), frontend (SvelteKit)
> - Storage tier: VictoriaMetrics + PostgreSQL
> - Multi-site federation and global tier
> - Backend HA (VictoriaMetrics dual-write, Patroni PostgreSQL)
> - Cross-site anomaly correlation
> - Federated ML (FedAvg gradient aggregation)
> - Backend clustering (>500 collectors)
> - OT air-gap and IEC 62443 rule-based detections
> - Alerting: vmalert + Alertmanager
> - RBAC, evidence bundles, audit log, collector auto-update
>
> Implementation phases are tracked in
> [`../collector/ROADMAP.md`](../collector/ROADMAP.md).
