# SENTINEL v2 Requirements Traceability

> **Work item:** C0-01
> **Architecture authority:** `ARCHITECTURE-V2-EXTENDED.md`
> **Audit date:** 2026-07-26
> **Status meanings:** `PARTIAL` means production behavior or an end-to-end
> boundary is missing. Documentation and examples alone count as `NOT STARTED`.

## 1. Audit Summary

The repository is an early Phase 1/2 vertical slice, not an operational v2
system. It currently contains:

- a Python 3.12 collector scaffold;
- configuration, enrollment client, mTLS/OTLP wiring, structured scheduler,
  event-loop watchdog, and thread-pool utilities;
- ICMP, TCP, HTTP, DNS, and derived latency checks with unit tests;
- a development-only hub Compose stack using an OpenTelemetry Collector,
  VictoriaMetrics, PostgreSQL bootstrap SQL, and a Python stub PKI service;
- collector lint/type/test workflows.

It does not contain the production Go ingest/API services, Python analysis
service, SvelteKit frontend, production deployment, durable replay stores,
advanced/OT probes, ML, federation/global tier, HA, clustering, air-gap support,
advanced alerting, evidence, audit, RBAC, or signed updates.

The current source layout also proves that old `[CREATE]` annotations in
`OPUS-AGENT-GUIDE-V2.md` cannot be used as implementation status.

## 2. Requirement Status Matrix

| ID | Requirement | Owner component | Target phase | Current evidence | Status | Acceptance evidence required |
|---|---|---|---:|---|---|---|
| CON-01 | Canonical metric names, units, required labels, and cardinality policy | contracts | 0 | Names exist in code/docs but use mixed prefixes | PARTIAL | Versioned catalog + validation tests |
| CON-02 | Versioned event envelope with UUID, `site_id`, timestamps, checksum, idempotency key | contracts | 0 | No shared envelope | NOT STARTED | Schema + Go/Python compatibility tests |
| CON-03 | Versioned REST, WebSocket, and error contracts | contracts/API | 0/12 | No production API | NOT STARTED | OpenAPI/AsyncAPI and contract tests |
| CON-04 | Forward-only database migration framework | PostgreSQL | 0 | Only dev `init.sql` exists | NOT STARTED | Empty/upgrade database CI tests |
| COL-01 | Validated layered collector configuration | collector | 1 | `collector/config.py` and tests | PARTIAL | Full feature schema + reload integration |
| COL-02 | Enrollment and per-collector mTLS credentials | collector/PKI | 1 | Enrollment client and stub PKI exist | PARTIAL | Real CA endpoint, token consumption, identity tests |
| COL-03 | OTLP/gRPC metric export with required identity | collector/ingest | 1 | OTLP exporter and OTel dev bridge exist | PARTIAL | Production ingest and E2E verification |
| COL-04 | Heartbeat and graceful shutdown | collector | 1 | Heartbeat, TaskGroup, signals exist | PARTIAL | Real hub `last_seen` update and failure tests |
| PRB-01 | Async ICMP probe | collector | 2 | Module and tests exist | PARTIAL | Linux capability + hub E2E |
| PRB-02 | Async TCP-connect probe | collector | 2 | Module and tests exist | PARTIAL | Hub E2E and allow-list enforcement |
| PRB-03 | Async HTTP(S) probe | collector | 2 | Module and tests exist | PARTIAL | Session lifecycle + hub E2E |
| PRB-04 | Async DNS probe | collector | 2 | Module and tests exist | PARTIAL | Resolver policy + hub E2E |
| PRB-05 | RTT histogram/jitter | collector | 2 | `net_latency.py` and tests exist | PARTIAL | Metric contract + hub E2E |
| FLT-01 | Host CPU/memory/disk/load/network metrics | collector | 3 | No host-health implementation | NOT STARTED | Unit + Linux field tests |
| FLT-02 | Service/process state metrics | collector | 3 | No implementation | NOT STARTED | Failed-service scenario |
| FLT-03 | Event-loop/check/cycle/export self-observability | collector | 3 | Loop watchdog exists | PARTIAL | All metrics and overrun alerts |
| FLT-04 | Three-layer fleet health and status API/UI | analyse/API/UI | 3/12 | Design only | NOT STARTED | Distinct failure scenario E2E |
| STO-01 | Capped LMDB hot/retry queue | collector | 4 | No LMDB store/retry module | NOT STARTED | 200 MB cap and crash tests |
| STO-02 | SQLite WAL cold/history store | collector | 4 | No implementation | NOT STARTED | Upgrade/corruption/recovery tests |
| STO-03 | Backoff, replay, quarantine, and ingest idempotency | collector/ingest | 4 | Config fields only | NOT STARTED | 24-hour outage simulation |
| PKI-01 | Automatic certificate renewal below 14 days | collector/hub | 5 | No renew module | NOT STARTED | Short-lived certificate E2E |
| PKI-02 | Revocation/disable enforcement | ingest/API | 5 | No production ingest/API | NOT STARTED | Revoked identity rejection |
| FLT-05 | Collector health score and degraded alert | analyse/VM | 5 | No score implementation in current tree | NOT STARTED | Historical score + threshold alert |
| WIF-01 | Linux Wi-Fi link/station/scan metrics | collector | 6 | Config only | NOT STARTED | Safe-lab hardware test |
| WIF-02 | `NET_ADMIN` only on Wi-Fi deployment profile | deploy | 6 | No collector Compose in current tree | NOT STARTED | Compose/capability inspection test |
| ADV-01 | MTR multi-hop checks | collector | 7 | Config only | NOT STARTED | Fixture + safe network test |
| ADV-02 | ARP rate/binding anomaly detection | collector/analyse | 7 | Theory only | NOT STARTED | Segment-baseline/spoof fixtures |
| ADV-03 | DHCP distribution/starvation detection | collector/analyse | 7 | Theory only | NOT STARTED | Packet fixtures and baselines |
| ADV-04 | Broadcast/multicast top talkers | collector | 7 | Config only | NOT STARTED | Filter/cardinality/resource tests |
| ADV-05 | WireGuard health | collector/analyse | 7 | Theory only | NOT STARTED | Tunnel failure scenarios |
| OT-01 | SNMP identity, health, and reboot classification | collector/analyse | 7 | Theory only | NOT STARTED | Rollover/agent-restart/reboot fixtures |
| OT-02 | Passive-first Modbus and read-only owned polling | collector | 7 | Theory only | NOT STARTED | Simulator proves writes impossible |
| OT-03 | Single OT-owner lease per device | hub/collector | 7 | Design only | NOT STARTED | Multi-collector contention test |
| TOP-01 | Route/WAN/TLS/device inventory and topology | collector/API/UI | 7/12 | Design only | NOT STARTED | Topology E2E |
| EBP-01 | Feature-probed, graceful eBPF telemetry | collector | 8 | Config only | NOT STARTED | Supported and degraded Linux paths |
| EBP-02 | Bounded LRU maps, drops, batch export, no payload | collector | 8 | Theory only | NOT STARTED | Pressure/privacy/resource tests |
| ANA-01 | CUSUM/EWMA Tier-1 detection | analyse | 9 | Theory only | NOT STARTED | 30-day backtest |
| ANA-02 | Hotelling T2/PCA multivariate detection | analyse | 9 | Theory only | NOT STARTED | Assumption and fault-injection tests |
| ANA-03 | Explainable RCA DAG and causal probes | analyse | 9 | Theory only | NOT STARTED | Known-fault scenarios |
| SCH-01 | Hysteretic adaptive target-state scheduler | collector/analyse | 10 | Fixed scheduler only | NOT STARTED | Backtest + shadow mode |
| SCH-02 | Small-N exact probe-budget allocation and fallback | collector/analyse | 10 | Theory only | NOT STARTED | Improvement with zero added misses |
| MLT-01 | LSTM-AE learning lifecycle and clean features | analyse | 11 | Design only | NOT STARTED | Reproducible training tests |
| MLT-02 | ONNX inference, versioning, threshold, rollback | analyse | 11 | Design only | NOT STARTED | PyTorch/ONNX parity + rollback |
| MLT-03 | ADWIN drift and retraining policy | analyse | 11 | Design only | NOT STARTED | Synthetic drift tests |
| MLT-04 | Tier-1/Tier-2 score fusion and evidence | analyse | 11 | Design only | NOT STARTED | Verdict/evidence tests |
| API-01 | Production Go REST/WebSocket API | API | 12 | No API source | NOT STARTED | Contract, auth, reconnect E2E |
| ALT-01 | Baseline webhook/SMTP alerts with retry/dedup | API | 12 | No implementation | NOT STARTED | Delivery failure/recovery tests |
| UI-01 | Site SvelteKit dashboard | frontend | 12 | No frontend source | NOT STARTED | Browser acceptance scenario |
| DEP-01 | Production Compose, Nginx, file secrets, health/resource limits | deploy | 13 | Dev-only Compose | NOT STARTED | Fresh install/least-privilege test |
| DEP-02 | Reproducible amd64/arm64 artifacts under NFRs | CI/release | 13 | No packaging files | NOT STARTED | Signed builds + Pi acceptance |
| DEP-03 | SBOM, scans, provenance, backup/restore/rollback | CI/ops | 13 | Some static workflows only | PARTIAL | Release and DR evidence |
| FED-01 | Site federation agent with durable selective forwarding | federation | 14 | Architecture only | NOT STARTED | WAN outage/replay E2E |
| FED-02 | Global metrics/events storage and query tier | global | 14 | Architecture only | NOT STARTED | Multi-site query E2E |
| FED-03 | Global sites/anomalies/topology/WebSocket API and UI | global | 14 | Architecture only | NOT STARTED | Tenant-isolation browser/API tests |
| COR-01 | Cross-site temporal/shared-cause correlation | correlator | 15 | Algorithm sketch only | NOT STARTED | Labeled precision/recall evaluation |
| COR-02 | Offline ASN enrichment | correlator | 15 | Design only | NOT STARTED | Version/checksum/offline tests |
| FML-01 | Authenticated compatible federated training rounds | global/site ML | 16 | Design only | NOT STARTED | Dropped/stale/mixed-version tests |
| FML-02 | Clipping, validation, optional DP, poisoning controls | global/site ML | 16 | Design only | NOT STARTED | Adversarial update tests |
| FML-03 | Local validation and shadow promotion/rollback | site ML | 16 | Design only | NOT STARTED | Quality/cold-start report |
| HA-01 | VictoriaMetrics dual-write and deduplicated reads | deploy/storage | 17 | Design example only | NOT STARTED | Failure-during-ingest drill |
| HA-02 | Patroni/DCS/PgBouncer PostgreSQL HA | deploy/storage | 17 | Placeholder example only | NOT STARTED | Quorum/failover/RPO/RTO drill |
| HA-03 | Redundant ingest/API and fenced analysis standby | services/deploy | 17 | Design only | NOT STARTED | Service failure drills |
| SCL-01 | VictoriaMetrics cluster and PG read scaling | storage | 17 | Design only | NOT STARTED | 500+ collector load tests |
| SCL-02 | Horizontally sharded analysis | analyse | 17 | Design only | NOT STARTED | No duplicate/missed work under load |
| AIR-01 | Autonomous air-gapped deployment | deploy/ops | 18 | Services not built | NOT STARTED | Offline fresh install |
| AIR-02 | Signed supervised periodic export/import sync | federation/ops | 18 | Design only | NOT STARTED | Replay/tamper/duplicate tests |
| ALT-02 | vmalert/Alertmanager grouping, silence, routing | alerting | 18 | Rules documented only | NOT STARTED | Alert-storm test |
| ALT-03 | Maintenance API, suppression, masks, banner | API/analyse/UI | 18 | Table mentioned only | NOT STARTED | Scope/history/overlap E2E |
| OT-04 | Deterministic IEC 62443 OT alert rules | analyse | 18 | Design only | NOT STARTED | Rule fixtures + evidence |
| EVD-01 | Canonical, signed site/cross-site evidence bundles | API/global | 18 | Hash-only design example | NOT STARTED | Tamper/origin/rotation verification |
| AUD-01 | Append-only operator audit log | API/PostgreSQL | 18 | Design SQL only | NOT STARTED | Role-enforced mutation denial |
| RBAC-01 | Viewer/operator/analyst/admin/OT-operator authorization | API/UI | 18 | Design only | NOT STARTED | Complete permission matrix |
| RBAC-02 | Site/tenant scoping and OT second-factor workflow | API/UI | 18 | Design only | NOT STARTED | Cross-tenant/escalation tests |
| UPD-01 | Signed staged collector update with rollback | collector/updater/API | 18 | Design only | NOT STARTED | Corruption/power-loss/canary tests |
| CAP-01 | Capacity metrics, forecast, and safe scale envelopes | analyse/UI/ops | 18 | Metric list only | NOT STARTED | Load-derived projections |

## 3. Cross-Cutting Verification Matrix

Every requirement above must link to at least one entry in each applicable
column before it can become `DONE`.

| Concern | Required artifact |
|---|---|
| Functional behavior | Unit and component integration tests |
| Cross-service behavior | Contract test and end-to-end scenario |
| Failure handling | Injected failure and recovery evidence |
| Security | Authentication/authorization/input/threat test |
| OT safety | Passive-first/allow-list/rate/write-refusal evidence |
| Observability | Health, metrics, logs, and actionable alert |
| Data lifecycle | Migration, retention, backup/restore, deletion behavior |
| Upgrade safety | Compatibility and rollback test |
| Collector resource use | ARM64 CPU/RSS/binary/cycle measurements |
| Scale claim | Repeatable load test and saturation envelope |

## 4. Immediate Critical Path

1. Finalize ADRs and canonical contracts (`C0-02`).
2. Replace the dev OTel/stub-PKI bridge with the production hub foundation.
3. Complete the collector heartbeat slice against that foundation.
4. Close core-probe end-to-end gaps before adding new check types.
5. Add migrations and durable/idempotent delivery before analysis and ML.
6. Complete a production-quality single-site system through Phase 13.
7. Add federation and later extensions only after site autonomy is proven.

## 5. Audit Qualifications

- `ARCHITECTURE-V2-EXTENDED.md` is authoritative but internally contains
  proposal-level examples and unresolved design choices. C0-02 ADRs must resolve
  those before implementation.
- The dev PKI service is intentionally a stub and must not be promoted.
- The PostgreSQL `init.sql` is not a migration system and its current schema is
  insufficient for production.
- Existing unit tests establish component progress but do not demonstrate an
  end-to-end production boundary.
- Hardware and field checks have not been inferred as passed merely because
  acceptance checklists exist.
