# SENTINEL v2 Requirements Traceability

> **Work item:** C0-01
> **Architecture authority:** `ARCHITECTURE-V2-EXTENDED.md`
> **Audit date:** 2026-07-26
> **Status meanings:** `PARTIAL` means production behavior or an end-to-end
> boundary is missing. Documentation and examples alone count as `NOT STARTED`.
> **Issue column added 2026-07-30.** Every `PARTIAL` and `NOT STARTED` row now maps
> to exactly one GitHub issue holding its scope and exit criteria; several rows share
> an issue where one work item satisfies both. This matrix stays the authority on
> *what is required*; the issue is the authority on *what is still open*. When a row
> changes status, say so in the same change that closes the issue.

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

| ID | Requirement | Owner component | Target phase | Current evidence | Status | Acceptance evidence required | Issue |
|---|---|---|---:|---|---|---|---|
| CON-01 | Canonical metric names, units, required labels, and cardinality policy | contracts | 0 | Names exist in code/docs but use mixed prefixes | PARTIAL | Versioned catalog + validation tests | [#66](https://github.com/Xore/SENTINEL/issues/66) |
| CON-02 | Versioned event envelope with UUID, `site_id`, timestamps, checksum, idempotency key | contracts | 0 | No shared envelope | NOT STARTED | Schema + Go/Python compatibility tests | [#67](https://github.com/Xore/SENTINEL/issues/67) |
| CON-03 | Versioned REST, WebSocket, and error contracts | contracts/API | 0/12 | No production API | NOT STARTED | OpenAPI/AsyncAPI and contract tests | [#68](https://github.com/Xore/SENTINEL/issues/68) |
| CON-04 | Forward-only database migration framework | PostgreSQL | 0 | Only dev `init.sql` exists | NOT STARTED | Empty/upgrade database CI tests | [#69](https://github.com/Xore/SENTINEL/issues/69) |
| COL-01 | Validated layered collector configuration | collector | 1 | `collector/config.py` and tests | PARTIAL | Full feature schema + reload integration | [#70](https://github.com/Xore/SENTINEL/issues/70) |
| COL-02 | Enrollment and per-collector mTLS credentials | collector/PKI | 1 | Enrollment client and stub PKI exist | PARTIAL | Real CA endpoint, token consumption, identity tests | [#71](https://github.com/Xore/SENTINEL/issues/71) |
| COL-03 | OTLP/gRPC metric export with required identity | collector/ingest | 1 | OTLP exporter and OTel dev bridge exist | PARTIAL | Production ingest and E2E verification | [#72](https://github.com/Xore/SENTINEL/issues/72) |
| COL-04 | Heartbeat and graceful shutdown | collector | 1 | Heartbeat, TaskGroup, signals exist | PARTIAL | Real hub `last_seen` update and failure tests | [#73](https://github.com/Xore/SENTINEL/issues/73) |
| PRB-01 | Async ICMP probe | collector | 2 | Module and tests exist | PARTIAL | Linux capability + hub E2E | [#74](https://github.com/Xore/SENTINEL/issues/74) |
| PRB-02 | Async TCP-connect probe | collector | 2 | Module and tests exist | PARTIAL | Hub E2E and allow-list enforcement | [#75](https://github.com/Xore/SENTINEL/issues/75) |
| PRB-03 | Async HTTP(S) probe | collector | 2 | Module and tests exist | PARTIAL | Session lifecycle + hub E2E | [#76](https://github.com/Xore/SENTINEL/issues/76) |
| PRB-04 | Async DNS probe | collector | 2 | Module and tests exist | PARTIAL | Resolver policy + hub E2E | [#77](https://github.com/Xore/SENTINEL/issues/77) |
| PRB-05 | RTT histogram/jitter | collector | 2 | `net_latency.py` and tests exist | PARTIAL | Metric contract + hub E2E | [#78](https://github.com/Xore/SENTINEL/issues/78) |
| FLT-01 | Host CPU/memory/disk/load/network metrics | collector | 3 | No host-health implementation | NOT STARTED | Unit + Linux field tests | [#31](https://github.com/Xore/SENTINEL/issues/31) [#36](https://github.com/Xore/SENTINEL/issues/36) |
| FLT-02 | Service/process state metrics | collector | 3 | No implementation | NOT STARTED | Failed-service scenario | [#31](https://github.com/Xore/SENTINEL/issues/31) [#36](https://github.com/Xore/SENTINEL/issues/36) |
| FLT-03 | Event-loop/check/cycle/export self-observability | collector | 3 | Loop watchdog exists | PARTIAL | All metrics and overrun alerts | [#79](https://github.com/Xore/SENTINEL/issues/79) |
| FLT-04 | Three-layer fleet health and status API/UI | analyse/API/UI | 3/12 | Design only | NOT STARTED | Distinct failure scenario E2E | [#80](https://github.com/Xore/SENTINEL/issues/80) |
| STO-01 | Capped LMDB hot/retry queue | collector | 4 | No LMDB store/retry module | NOT STARTED | 200 MB cap and crash tests | [#35](https://github.com/Xore/SENTINEL/issues/35) |
| STO-02 | SQLite WAL cold/history store | collector | 4 | No implementation | NOT STARTED | Upgrade/corruption/recovery tests | [#81](https://github.com/Xore/SENTINEL/issues/81) |
| STO-03 | Backoff, replay, quarantine, and ingest idempotency | collector/ingest | 4 | Config fields only | NOT STARTED | 24-hour outage simulation | [#32](https://github.com/Xore/SENTINEL/issues/32) |
| PKI-01 | Automatic certificate renewal below 14 days | collector/hub | 5 | No renew module | NOT STARTED | Short-lived certificate E2E | [#34](https://github.com/Xore/SENTINEL/issues/34) |
| PKI-02 | Revocation/disable enforcement | ingest/API | 5 | No production ingest/API | NOT STARTED | Revoked identity rejection | [#82](https://github.com/Xore/SENTINEL/issues/82) |
| FLT-05 | Collector health score and degraded alert | analyse/VM | 5 | No score implementation in current tree | NOT STARTED | Historical score + threshold alert | [#34](https://github.com/Xore/SENTINEL/issues/34) |
| WIF-01 | Linux Wi-Fi link/station/scan metrics | collector | 6 | Config only | NOT STARTED | Safe-lab hardware test | [#37](https://github.com/Xore/SENTINEL/issues/37) |
| WIF-02 | `NET_ADMIN` only on Wi-Fi deployment profile | deploy | 6 | No collector Compose in current tree | NOT STARTED | Compose/capability inspection test | [#83](https://github.com/Xore/SENTINEL/issues/83) |
| ADV-01 | MTR multi-hop checks | collector | 7 | Config only | NOT STARTED | Fixture + safe network test | [#38](https://github.com/Xore/SENTINEL/issues/38) |
| ADV-02 | ARP rate/binding anomaly detection | collector/analyse | 7 | Theory only | NOT STARTED | Segment-baseline/spoof fixtures | [#84](https://github.com/Xore/SENTINEL/issues/84) |
| ADV-03 | DHCP distribution/starvation detection | collector/analyse | 7 | Theory only | NOT STARTED | Packet fixtures and baselines | [#85](https://github.com/Xore/SENTINEL/issues/85) |
| ADV-04 | Broadcast/multicast top talkers | collector | 7 | Config only | NOT STARTED | Filter/cardinality/resource tests | [#43](https://github.com/Xore/SENTINEL/issues/43) |
| OT-01 | SNMP identity, health, and reboot classification | collector/analyse | 7 | Theory only | NOT STARTED | Rollover/agent-restart/reboot fixtures | [#39](https://github.com/Xore/SENTINEL/issues/39) |
| OT-02 | Passive-first Modbus and read-only owned polling | collector | 7 | Theory only | NOT STARTED | Simulator proves writes impossible | [#41](https://github.com/Xore/SENTINEL/issues/41) |
| OT-03 | Single OT-owner lease per device | hub/collector | 7 | Design only | NOT STARTED | Multi-collector contention test | [#86](https://github.com/Xore/SENTINEL/issues/86) |
| TOP-01 | Route/WAN/TLS/device inventory and topology | collector/API/UI | 7/12 | Design only | NOT STARTED | Topology E2E | [#61](https://github.com/Xore/SENTINEL/issues/61) [#62](https://github.com/Xore/SENTINEL/issues/62) [#63](https://github.com/Xore/SENTINEL/issues/63) [#64](https://github.com/Xore/SENTINEL/issues/64) [#65](https://github.com/Xore/SENTINEL/issues/65) |
| EBP-01 | Feature-probed, graceful eBPF telemetry | collector | 8 | Config only | NOT STARTED | Supported and degraded Linux paths | [#45](https://github.com/Xore/SENTINEL/issues/45) |
| EBP-02 | Bounded LRU maps, drops, batch export, no payload | collector | 8 | Theory only | NOT STARTED | Pressure/privacy/resource tests | [#87](https://github.com/Xore/SENTINEL/issues/87) |
| ANA-01 | CUSUM/EWMA Tier-1 detection | analyse | 9 | Theory only | NOT STARTED | 30-day backtest | [#88](https://github.com/Xore/SENTINEL/issues/88) |
| ANA-02 | Hotelling T2/PCA multivariate detection | analyse | 9 | Theory only | NOT STARTED | Assumption and fault-injection tests | [#89](https://github.com/Xore/SENTINEL/issues/89) |
| ANA-03 | Explainable RCA DAG and causal probes | analyse | 9 | Theory only | NOT STARTED | Known-fault scenarios | [#90](https://github.com/Xore/SENTINEL/issues/90) |
| SCH-01 | Hysteretic adaptive target-state scheduler | collector/analyse | 10 | Fixed scheduler only | NOT STARTED | Backtest + shadow mode | [#91](https://github.com/Xore/SENTINEL/issues/91) |
| SCH-02 | Small-N exact probe-budget allocation and fallback | collector/analyse | 10 | Theory only | NOT STARTED | Improvement with zero added misses | [#92](https://github.com/Xore/SENTINEL/issues/92) |
| MLT-01 | LSTM-AE learning lifecycle and clean features | analyse | 11 | Design only | NOT STARTED | Reproducible training tests | [#93](https://github.com/Xore/SENTINEL/issues/93) |
| MLT-02 | ONNX inference, versioning, threshold, rollback | analyse | 11 | Design only | NOT STARTED | PyTorch/ONNX parity + rollback | [#94](https://github.com/Xore/SENTINEL/issues/94) |
| MLT-03 | ADWIN drift and retraining policy | analyse | 11 | Design only | NOT STARTED | Synthetic drift tests | [#95](https://github.com/Xore/SENTINEL/issues/95) |
| MLT-04 | Tier-1/Tier-2 score fusion and evidence | analyse | 11 | Design only | NOT STARTED | Verdict/evidence tests | [#96](https://github.com/Xore/SENTINEL/issues/96) |
| API-01 | Production Go REST/WebSocket API | API | 12 | No API source | NOT STARTED | Contract, auth, reconnect E2E | [#97](https://github.com/Xore/SENTINEL/issues/97) |
| ALT-01 | Baseline webhook/SMTP alerts with retry/dedup | API | 12 | No implementation | NOT STARTED | Delivery failure/recovery tests | [#56](https://github.com/Xore/SENTINEL/issues/56) |
| UI-01 | Site SvelteKit dashboard | frontend | 12 | No frontend source | NOT STARTED | Browser acceptance scenario | [#98](https://github.com/Xore/SENTINEL/issues/98) |
| DEP-01 | Production Compose, Nginx, file secrets, health/resource limits | deploy | 13 | Dev-only Compose | NOT STARTED | Fresh install/least-privilege test | [#99](https://github.com/Xore/SENTINEL/issues/99) |
| DEP-02 | Reproducible amd64/arm64 artifacts under NFRs | CI/release | 13 | No packaging files | NOT STARTED | Signed builds + Pi acceptance | [#46](https://github.com/Xore/SENTINEL/issues/46) [#48](https://github.com/Xore/SENTINEL/issues/48) |
| DEP-03 | SBOM, scans, provenance, backup/restore/rollback | CI/ops | 13 | Some static workflows only | PARTIAL | Release and DR evidence | [#100](https://github.com/Xore/SENTINEL/issues/100) |
| FED-01 | Site federation agent with durable selective forwarding | federation | 14 | Architecture only | NOT STARTED | WAN outage/replay E2E | [#101](https://github.com/Xore/SENTINEL/issues/101) |
| FED-02 | Global metrics/events storage and query tier | global | 14 | Architecture only | NOT STARTED | Multi-site query E2E | [#102](https://github.com/Xore/SENTINEL/issues/102) |
| FED-03 | Global sites/anomalies/topology/WebSocket API and UI | global | 14 | Architecture only | NOT STARTED | Tenant-isolation browser/API tests | [#103](https://github.com/Xore/SENTINEL/issues/103) |
| COR-01 | Cross-site temporal/shared-cause correlation | correlator | 15 | Algorithm sketch only | NOT STARTED | Labeled precision/recall evaluation | [#104](https://github.com/Xore/SENTINEL/issues/104) |
| COR-02 | Offline ASN enrichment | correlator | 15 | Design only | NOT STARTED | Version/checksum/offline tests | [#105](https://github.com/Xore/SENTINEL/issues/105) |
| FML-01 | Authenticated compatible federated training rounds | global/site ML | 16 | Design only | NOT STARTED | Dropped/stale/mixed-version tests | [#106](https://github.com/Xore/SENTINEL/issues/106) |
| FML-02 | Clipping, validation, optional DP, poisoning controls | global/site ML | 16 | Design only | NOT STARTED | Adversarial update tests | [#107](https://github.com/Xore/SENTINEL/issues/107) |
| FML-03 | Local validation and shadow promotion/rollback | site ML | 16 | Design only | NOT STARTED | Quality/cold-start report | [#108](https://github.com/Xore/SENTINEL/issues/108) |
| HA-01 | VictoriaMetrics dual-write and deduplicated reads | deploy/storage | 17 | Design example only | NOT STARTED | Failure-during-ingest drill | [#109](https://github.com/Xore/SENTINEL/issues/109) |
| HA-02 | Patroni/DCS/PgBouncer PostgreSQL HA | deploy/storage | 17 | Placeholder example only | NOT STARTED | Quorum/failover/RPO/RTO drill | [#110](https://github.com/Xore/SENTINEL/issues/110) |
| HA-03 | Redundant ingest/API and fenced analysis standby | services/deploy | 17 | Design only | NOT STARTED | Service failure drills | [#111](https://github.com/Xore/SENTINEL/issues/111) |
| SCL-01 | VictoriaMetrics cluster and PG read scaling | storage | 17 | Design only | NOT STARTED | 500+ collector load tests | [#112](https://github.com/Xore/SENTINEL/issues/112) |
| SCL-02 | Horizontally sharded analysis | analyse | 17 | Design only | NOT STARTED | No duplicate/missed work under load | [#113](https://github.com/Xore/SENTINEL/issues/113) |
| AIR-01 | Autonomous air-gapped deployment | deploy/ops | 18 | Services not built | NOT STARTED | Offline fresh install | [#114](https://github.com/Xore/SENTINEL/issues/114) |
| AIR-02 | Signed supervised periodic export/import sync | federation/ops | 18 | Design only | NOT STARTED | Replay/tamper/duplicate tests | [#115](https://github.com/Xore/SENTINEL/issues/115) |
| ALT-02 | vmalert/Alertmanager grouping, silence, routing | alerting | 18 | Rules documented only | NOT STARTED | Alert-storm test | [#116](https://github.com/Xore/SENTINEL/issues/116) |
| ALT-03 | Maintenance API, suppression, masks, banner | API/analyse/UI | 18 | Table mentioned only | NOT STARTED | Scope/history/overlap E2E | [#59](https://github.com/Xore/SENTINEL/issues/59) [#60](https://github.com/Xore/SENTINEL/issues/60) |
| OT-04 | Deterministic IEC 62443 OT alert rules | analyse | 18 | Design only | NOT STARTED | Rule fixtures + evidence | [#117](https://github.com/Xore/SENTINEL/issues/117) |
| EVD-01 | Canonical, signed site/cross-site evidence bundles | API/global | 18 | Hash-only design example | NOT STARTED | Tamper/origin/rotation verification | [#53](https://github.com/Xore/SENTINEL/issues/53) [#54](https://github.com/Xore/SENTINEL/issues/54) |
| AUD-01 | Append-only operator audit log | API/PostgreSQL | 18 | Design SQL only | NOT STARTED | Role-enforced mutation denial | [#57](https://github.com/Xore/SENTINEL/issues/57) [#58](https://github.com/Xore/SENTINEL/issues/58) |
| RBAC-01 | Viewer/operator/analyst/admin/OT-operator authorization | API/UI | 18 | Design only | NOT STARTED | Complete permission matrix | [#118](https://github.com/Xore/SENTINEL/issues/118) |
| RBAC-02 | Site/tenant scoping and OT second-factor workflow | API/UI | 18 | Design only | NOT STARTED | Cross-tenant/escalation tests | [#119](https://github.com/Xore/SENTINEL/issues/119) |
| UPD-01 | Signed staged collector update with rollback | collector/updater/API | 18 | Design only | NOT STARTED | Corruption/power-loss/canary tests | [#33](https://github.com/Xore/SENTINEL/issues/33) |
| CAP-01 | Capacity metrics, forecast, and safe scale envelopes | analyse/UI/ops | 18 | Metric list only | NOT STARTED | Load-derived projections | [#120](https://github.com/Xore/SENTINEL/issues/120) |

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
