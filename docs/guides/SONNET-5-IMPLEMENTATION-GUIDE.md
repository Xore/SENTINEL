# Sonnet 5 Implementation Guide — SENTINEL v2

> **Audience:** Sonnet 5 acting as the primary implementation agent.
> **Architecture authority:** `docs/architecture/ARCHITECTURE-V2-EXTENDED.md`.
> **Implementation-pattern reference:** `docs/guides/OPUS-AGENT-GUIDE-V2.md`.
> **Purpose:** Implement the complete system in safe, testable vertical slices, including the single-site baseline and every extended feature.
> **Important:** Treat repository inspection as the authority for what already exists. The `[EXISTS]` and `[CREATE]` labels in older guides are snapshots and may be stale.
> **Multi-agent coordination:** Before planning or coding, read `docs/guides/AGENT-COORDINATION.md`. Codex and Sonnet 5 use that file as their durable handoff channel.

---

## 1. Mission and Non-Negotiable Rules

Build SENTINEL v2 as a passive-first IT/OT monitoring platform:

1. lightweight Python 3.12 collectors;
2. a single-site hub with Go ingest, Python analysis, Go API, VictoriaMetrics, PostgreSQL, and SvelteKit;
3. optional multi-site federation and a global tier;
4. optional site HA and large-fleet clustering;
5. cross-site anomaly correlation and federated ML;
6. air-gap operation, scalable alerting, evidence, audit, RBAC, signed updates, fleet health, and capacity planning.

Apply these rules throughout:

- Do not redesign the architecture while implementing it. Record ambiguities as architecture decision records (ADRs) and choose the smallest reversible implementation.
- Never skip phase gates. A phase is complete only when its tests and end-to-end acceptance checks pass.
- Build collector and hub capabilities as vertical slices. A metric is not implemented until it is emitted, ingested, stored, queryable, and tested.
- Preserve local-site autonomy. Global-tier failure must never stop site-local collection, analysis, alerting, API access, or dashboards.
- Keep OT passive-first. Active probes must be allow-listed, low-rate, read-only, timeout-bounded, and explicitly enabled.
- Never run generic scanners, fuzzing, Modbus writes, unsafe SNMP sweeps, S7 reads/writes, OPC UA browsing, or high-rate discovery against production OT.
- All collector operations are asynchronous. No blocking network, subprocess, sleep, or CPU-heavy work on the event loop.
- Optional facilities must degrade gracefully: eBPF, Wi-Fi, OT modules, WAN federation, global ML, and external notifiers.
- Add the minimum Linux capabilities. `NET_ADMIN` belongs only in the Wi-Fi override.
- Sensitive hub secrets are file-mounted Docker secrets, not environment variables or committed files.
- Use migrations for all database changes. Never rely only on a mutable `init.sql`.
- Pin runtime and development dependencies. Validate compatible dependency families together.
- Do not delete, stub, weaken, or bypass failing tests to obtain a green build.

### Collector resource gates

| Constraint | Required limit |
|---|---:|
| RSS on Raspberry Pi 3B | <= 80 MB |
| Average CPU on Raspberry Pi 3B | <= 5% |
| PyInstaller binary | <= 25 MB |
| Full scan-level-2 cycle | <= 30 seconds |
| LMDB retry/local hot buffer | <= 200 MB |
| Collector ML dependencies | None; ML is hub-side |

---

## 2. Required Reading and Precedence

Read the relevant files completely before changing code.

### Precedence when documents conflict

1. `docs/architecture/ARCHITECTURE-V2-EXTENDED.md` — target system behavior.
2. Safety and deployment constraints in `README.md`, `docs/guides/01-design-and-safety.md`, and `docs/architecture/IaC-DEPLOYMENT-STRATEGY.md`.
3. Component specifications:
   - `docs/collector/COLLECTOR-V2-REFACTOR.md`
   - `docs/ml/ML_BASELINE_LEARNING.md`
   - `docs/architecture/COLLECTOR-FLEET-MONITORING.md`
4. `docs/guides/OPUS-AGENT-GUIDE-V2.md` — implementation order and coding patterns.
5. Theory and gap-analysis documents — algorithms, validation gates, and research qualifications.
6. The current repository — implementation status, not desired behavior.

### Mandatory topic references

| Work area | Read first |
|---|---|
| Collector code | `COLLECTOR-V2-REFACTOR.md`, `OPUS-AGENT-GUIDE-V2.md`, `ASYNCIO-OPTIMIZATION.md` |
| Deployment/CI | `IaC-DEPLOYMENT-STRATEGY.md`, `code-scanning-remediation.md` |
| Fleet monitoring | `COLLECTOR-FLEET-MONITORING.md` |
| ML | `ML_BASELINE_LEARNING.md`, anomaly theory, Hotelling T2, RCA theory |
| Scheduling | both MDP docs and both probe-budget docs |
| eBPF | both eBPF docs plus passive/active and high-cardinality docs |
| OT | both OT theory docs and SNMP uptime regression theory |
| Transport | OTLP batch sizing and probe-to-backend transport theory |
| Storage | embedded TSDB selection and high-cardinality storage theory |
| WireGuard | WireGuard health monitoring theory |
| Test/release | `08-testing-and-installation.md` |

Do not blindly copy example code from design documents. Convert it into production code with validation, cancellation, timeouts, observability, migrations, and tests.

---

## 3. Sonnet 5 Operating Procedure

Use this loop for every phase.

### 3.1 Before coding

1. Read `docs/guides/AGENT-COORDINATION.md` completely.
2. Do not start work marked `OWNER: CODEX`, `STATUS: BLOCKED`, or `STATUS: REVIEW`.
3. Inspect `git status`, repository files, tests, workflows, and current dependency pins.
4. Read the full source sections referenced by the phase.
5. Write a short phase plan listing:
   - files to create or change;
   - data contracts;
   - migrations;
   - security and OT-safety implications;
   - unit, integration, failure-path, and resource tests;
   - exact exit command(s).
6. Search for an existing implementation before creating a new module.
7. Confirm that every intended file is inside Sonnet's assigned write scope in the coordination ledger.
8. Update stale documentation only when the actual decision has changed.

### 3.2 While coding

1. Make the smallest coherent vertical slice.
2. Add tests in the same change.
3. Run focused tests after each module.
4. Run linters and type checking before phase integration.
5. Keep commits phase-scoped. Do not mix formatting or unrelated cleanup.
6. If implementation exposes an architectural ambiguity, do not silently choose a new architecture. Add a `QUESTION` entry to `AGENT-COORDINATION.md`, mark the affected work blocked, and continue with independent tasks.

### 3.3 Phase completion report

For every phase, report:

- implemented behavior;
- changed files and migrations;
- tests run with results;
- resource/security checks;
- unresolved risks or deviations;
- rollback procedure;
- evidence that the exit gate passed.

If the exit gate fails, stop and fix it. Do not proceed based on expected future integration.

### 3.4 Required handoff behavior

At the start and end of every work session, Sonnet 5 must update
`docs/guides/AGENT-COORDINATION.md`:

1. set its work item to `IN_PROGRESS` before editing;
2. list exact files it expects to touch;
3. record new questions and contract mismatches as soon as they are found;
4. on completion, record commands and results, changed files, assumptions, and the
   commit SHA if a commit was created;
5. set the item to `REVIEW`, never directly to `DONE`;
6. wait for Codex phase-gate review before beginning a dependent phase.

The coordination file is a control plane, not a chat transcript. Keep entries
short, factual, timestamped in UTC, and append-only except for status fields.

---

## 3A. Division of Responsibility

Codex and Sonnet 5 collaborate, but they do not edit the same files concurrently.
The live assignment in `AGENT-COORDINATION.md` overrides the defaults below.

### Codex owns

- architecture interpretation and ADRs;
- requirements traceability and phase decomposition;
- cross-service contracts: protobuf/OpenAPI/event envelopes/metric catalog;
- PostgreSQL schema design and migration review;
- security architecture, threat model, PKI, RBAC policy, evidence signing, and
  update trust chain;
- federation, cross-site correlation, federated-ML protocol, air-gap sync, HA,
  clustering, RPO/RTO, and capacity architecture;
- deployment topology and privilege review;
- final integration of cross-component changes;
- phase-gate review and the decision to mark work `DONE`.

Codex may directly implement these areas, especially shared contracts, migrations,
security middleware, deployment configuration, federation/HA foundations, and
integration tests. Sonnet 5 must not rewrite Codex-owned designs or files without
an accepted handoff entry.

### Sonnet 5 owns

- bounded collector modules assigned by phase;
- bounded Go ingest/API handlers against Codex-approved contracts;
- Python analysis and ML modules against Codex-approved schemas;
- unit tests and component integration tests for its changes;
- frontend views against approved API contracts;
- implementation documentation local to the module;
- focused bug fixes found while completing an assigned work item.

### Shared, but serialized

These require an explicit file-level assignment before edits:

- `deploy/**`;
- `.github/**`;
- database migrations;
- protobuf/OpenAPI/schema files;
- shared Pydantic or Go contract models;
- dependency manifests and lock files;
- top-level architecture and implementation guides.

Only one agent may own a shared file at a time. The other agent reviews via the
coordination ledger and a diff; it does not apply competing edits.

---

## 4. Resolve Design Ambiguities Before They Become Code

Create `docs/architecture/decisions/` and record ADRs for these points during Phase 0:

1. **Naming:** product metrics should use one canonical prefix. Existing docs mix bare names, `analyselaptop_*`, and collector-specific names.
2. **Repository paths:** architecture uses both `backend/` and `hub/`. Choose one source layout and keep deployment paths consistent.
3. **Federation language:** the extended architecture specifies a Go federation agent, while the Opus guide calls it Python. Prefer Go because the authoritative architecture explicitly says “lightweight Go binary,” unless measured implementation constraints justify an ADR changing it.
4. **Global PostgreSQL flow:** the document mentions both a REST append endpoint and logical replication. Define which is canonical:
   - recommended default: idempotent application-level event replication over mTLS;
   - optional trusted-network deployment: PostgreSQL logical replication.
5. **Collector delivery path:** define whether collectors send OTLP to ingest directly or through a site vmagent. Keep metrics dual-write at the site backend, not in every edge collector, unless an ADR proves otherwise.
6. **Modbus detection:** passive Modbus function-code detection needs packet metadata beyond a simple 5-tuple flow counter. Specify a payload-free parser/event contract before implementing the OT write-command rule.
7. **Federated privacy claim:** gradients can leak training data. Do not state that gradients have “no recoverable sample data.” Add clipping, authenticated aggregation, optional differential privacy, and a documented threat model.
8. **Auto-update restart authority:** a non-root process cannot safely replace itself and invoke systemd without a constrained privileged helper. Define the updater/service boundary and rollback.
9. **HA compose examples:** floating image tags and placeholder Patroni configuration are not production-ready. Pin versions and implement health-tested configuration.
10. **Scale language:** replace “unlimited” with measured, tested capacity envelopes.

---

## 5. Implementation Roadmap

## Phase 0 — Baseline Audit, Contracts, and Architecture Decisions

**Goal:** Establish a reliable starting point and prevent schema/interface drift.

1. Inventory all existing collector, deploy, workflow, test, dashboard, and monitor files.
2. Run the current collector quality suite:
   - `ruff check .`
   - `mypy .`
   - `pylint collector tests`
   - `pytest -q`
3. Produce a requirements traceability matrix mapping every architecture feature to:
   - component owner;
   - API/metric/table contract;
   - planned phase;
   - test;
   - status.
4. Add ADRs from Section 4.
5. Define shared contracts:
   - metric naming, required labels, units, and cardinality limits;
   - event envelope with UUID, `site_id`, timestamps, schema version, and idempotency key;
   - error format and API versioning;
   - UTC timestamp policy;
   - site, collector, target, anomaly, RCA, alert, and model identifiers.
6. Add a migration framework and an empty-database migration test.
7. Add a CI job that detects schema/migration drift.

**Exit gate:** Existing tests pass; ADRs are accepted; the traceability matrix covers every row in the extended architecture’s feature-upgrade map.

## Phase 1 — Single-Site Hub Foundation and Collector Heartbeat

**Goal:** One collector enrolls with the hub and a heartbeat is stored and queryable.

1. Create the canonical hub source tree:
   - Go OTLP/gRPC ingest;
   - Python analyse skeleton;
   - Go/Gin API;
   - PostgreSQL migrations;
   - VictoriaMetrics;
   - development Compose.
2. Implement health/readiness endpoints for every service.
3. Implement one-time collector enrollment:
   - consumed enrollment tokens;
   - CA-signed per-collector certificate;
   - restrictive file permissions;
   - revocation-ready certificate identity.
4. Complete collector configuration, PKI enrollment, mTLS transport, OTLP export, scheduler, graceful shutdown, and heartbeat.
5. Require `collector_id` and `site_id` labels at ingest; reject malformed identities.
6. Persist collector registration and `last_seen`.
7. Test untrusted CA, expired certificate, mismatched identity, reused token, hub outage, and recovery.

**Exit gate:** A real collector process sends a heartbeat over mTLS; the metric is visible in VictoriaMetrics and `last_seen` is visible through the API.

## Phase 2 — Core Network Probe Vertical Slices

**Goal:** ICMP, TCP, HTTP(S), DNS, and latency/jitter work end to end.

For each probe:

1. implement a Pydantic config model and allow-list;
2. implement an async, cancellation-safe check with an explicit timeout;
3. return a typed `CheckResult` instead of raising into the scheduler;
4. emit stable metrics with bounded labels;
5. add unit tests for success, timeout, malformed output, permission failure, and cancellation;
6. verify ingest, storage, MetricsQL query, and API response.

Apply a global configurable network semaphore (20 on Pi 3B), reuse HTTP sessions, and use async DNS APIs.

**Exit gate:** All probe metrics are queryable with correct units and labels, and one broken check cannot stop other checks.

## Phase 3 — Host Health, Fleet Visibility, and Scheduler Robustness

**Goal:** Operators can distinguish collector death, service failure, host stress, and check degradation.

1. Add Linux host CPU, memory, disk, load, network, process, and service checks.
2. Add event-loop watchdog, per-check duration, cycle duration, overrun count, export failure, queue depth, and certificate-expiry metrics.
3. Implement three-layer fleet health:
   - heartbeat/`last_seen`;
   - collector service state;
   - host vitals.
4. Add vmalert fleet rules and frontend/API fleet status data.
5. Use `asyncio.TaskGroup`, explicit stop events, bounded thread pool, and per-check timeouts.
6. Test scheduler fairness, no task leaks, graceful SIGTERM, SIGHUP validation rollback, and a deliberately blocking fake check.

**Exit gate:** Killing the collector, failing its service, exhausting disk, and blocking a check produce distinct observable states and alerts.

## Phase 4 — Offline Storage, Retry, and Idempotent Replay

**Goal:** A site/hub outage loses no accepted local telemetry within the retention envelope.

1. Implement the capped LMDB hot queue and SQLite WAL cold/history store.
2. Store a versioned record envelope with event ID, creation time, attempt count, expiry, and payload checksum.
3. Implement exponential backoff with jitter, reconnect detection, ordered batch replay, and poison-record quarantine.
4. Make ingest idempotent. Duplicate replay must not create duplicate events.
5. Enforce 200 MB eviction policy and expose queue bytes, oldest age, drops, retries, and replay throughput.
6. Test process crash during write, full disk, corrupt record, schema upgrade, 24-hour simulated outage, reconnect, and duplicate delivery.

**Exit gate:** A forced hub outage buffers data; reconnect drains it; duplicate count is zero; the collector stays within resource limits.

## Phase 5 — PKI Lifecycle, Config Reload, and Health Score

**Goal:** Collector identity operates safely without routine manual intervention.

1. Implement renewal when certificate lifetime is below 14 days.
2. Replace credentials atomically and reconnect without losing buffered telemetry.
3. Add revocation and collector-disable handling at ingest.
4. Implement validated SIGHUP reload that retains the last valid config on error.
5. Implement collector health score with documented normalization and missing-data behavior.
6. Store score history in VictoriaMetrics and alert below 0.6.

**Exit gate:** Short-lived test certificates renew automatically; revoked collectors are rejected; bad reloads preserve the working configuration.

## Phase 6 — Wi-Fi and Capability Isolation

**Goal:** Wi-Fi nodes report RF/link health without broadening privileges for wired nodes.

1. Implement Linux `iw link`, station, and scan parsing using async subprocesses.
2. Make interface names configuration-driven.
3. Add Wi-Fi metrics and bounded BSSID/SSID label policy.
4. Keep `NET_ADMIN` only in `docker-compose.wifi.yml`.
5. Test wrong interface, missing `iw`, missing capability, disconnected state, malformed output, and disabled configuration.
6. Validate on safe lab hardware before any live Wi-Fi-only node.

**Exit gate:** Wi-Fi metrics work with the override; the base container lacks `NET_ADMIN`; wired nodes continue normally.

## Phase 7 — Advanced Network and OT-Safe Checks

**Goal:** Add MTR, ARP/DHCP segment health, broadcast/multicast, WireGuard, SNMP, and Modbus safely.

1. Implement each check independently with an enable flag and explicit target allow-list.
2. Follow the theory documents:
   - ARP: combine per-segment rate baseline with IP–MAC binding consistency.
   - DHCP: use message-type distribution and DECLINE/ACK ratio, not only lease percentage.
   - SNMP reboot: distinguish true reboot, TimeTicks rollover, and agent restart using multiple uptime sources where available.
   - WireGuard: use handshake age, transfer deltas, routing/endpoint context, and tunnel state.
   - broadcast/multicast: use kernel filters, short bounded windows, and cardinality caps.
   - Modbus: passive discovery first; active reads only for designated OT-owner collectors; categorically refuse write function codes.
3. Add ownership/lease coordination so only one collector actively polls a given OT device.
4. Add topology, route, WAN, TLS, and device inventory API contracts.
5. Test using simulators and packet fixtures, never production OT.

**Exit gate:** Every optional check fails closed and degrades independently; OT write attempts are impossible through the collector API/config.

## Phase 8 — eBPF Passive Telemetry

**Goal:** Provide payload-free passive flow/RTT telemetry where the host supports it.

1. Feature-probe kernel, BTF, hook availability, capabilities, lockdown, AppArmor, container namespace, memlock, and required maps.
2. Guard imports and startup. Unsupported platforms must run without eBPF.
3. Implement bounded LRU maps, overflow/drop metrics, batch export, and cardinality controls.
4. Keep payload collection prohibited.
5. Define and implement the additional safe metadata/event mechanism needed for passive Modbus write-function detection.
6. Test no-BCC, no-BTF, permission failure, map pressure, kernel rejection, clean detach, and fallback.
7. Benchmark CPU/RSS on ARM64.

**Exit gate:** Supported Linux emits flow telemetry; unsupported or restricted Linux reports degraded state without collector failure; no payload is exported.

## Phase 9 — Site Analysis Tier 1 and Root-Cause Analysis

**Goal:** Convert telemetry into explainable local anomalies and RCA.

1. Implement feature extraction and clean time alignment.
2. Implement CUSUM/EWMA univariate detectors using empirically tuned thresholds.
3. Implement multivariate Hotelling T2/PCA where sample-size assumptions hold.
4. Store anomaly evidence, detector version, thresholds, and contributing metrics.
5. Implement the causal/RCA DAG and active causal probe sequence with strict budgets.
6. Implement maintenance contamination masks.
7. Export anomaly and RCA metrics/events with bounded labels.
8. Backtest thresholds on at least 30 days of representative history as prescribed by the research guide.

**Exit gate:** Known injected faults produce explainable anomalies/RCA; false-positive and missed-outage reports are recorded; unvalidated thresholds do not ship.

## Phase 10 — Adaptive Scheduling and Probe Budgets

**Goal:** Reduce detection latency without increasing load or missing outages.

1. Implement the STABLE/SUSPECT/DEGRADED/DOWN state machine using hysteresis and validated CUSUM-derived transitions.
2. Treat the scheduler as a practical threshold policy, not a literal proof of the cited MDP.
3. At 5–15 targets, compare exact A-optimal allocation with the documented approximation and uniform scheduling.
4. Measure allocation churn and apply smoothing only if it improves outcomes.
5. Keep a fixed total probe budget, per-target minimums, OT-specific ceilings, and an immediate uniform fallback.
6. Ship only if backtests show positive detection-latency improvement with zero additional missed outages.

**Exit gate:** Backtest and shadow-mode reports meet the research criteria; rollback to fixed scheduling is one configuration change.

## Phase 11 — Site ML Baseline Learning

**Goal:** Add local LSTM autoencoder detection without contaminating training data.

1. Add migrations for model state, versions, training jobs, thresholds, and contamination masks.
2. Implement feature groups, resampling, interpolation limits, robust scaling, cyclical time features, and 128-step windows.
3. Implement the learning lifecycle and minimum-data checks.
4. Train the specified two-layer LSTM-AE, validate chronologically, early-stop, and derive thresholds from validation reconstruction errors.
5. Export an ONNX inference artifact; version model, scaler, schema, features, code, and training interval together.
6. Implement ADWIN drift detection and retrain/fine-tune policy.
7. Fuse Tier 1 and Tier 2 scores and retain the evidence behind every verdict.
8. Add rollback and shadow/canary promotion.

**Exit gate:** Reproducible training, contamination tests, ONNX parity tests, drift tests, and rollback all pass; ML failure never disables Tier 1.

## Phase 12 — Site API, Alerting, and Frontend

**Goal:** Deliver a usable single-site product before introducing global dependencies.

1. Implement versioned REST and WebSocket APIs for collectors, metrics, anomalies, RCA, topology, ML state, alerts, maintenance, evidence, and health.
2. Add pagination, filters, rate limits, request IDs, timeouts, and reconnect-safe WebSockets.
3. Implement JWT authentication with key rotation hooks.
4. Implement baseline webhook/SMTP alert delivery with retry and deduplication.
5. Build the SvelteKit site dashboard:
   - fleet status;
   - anomaly timeline;
   - RCA details/evidence;
   - topology;
   - ML lifecycle;
   - maintenance banner;
   - capacity/health panels.
6. Add accessibility, empty/loading/error states, timezone display, and end-to-end browser tests.

**Exit gate:** A user can diagnose an injected incident entirely through the UI and API; disconnect/reconnect behavior is tested.

## Phase 13 — Packaging, Single-Site Deployment, and Release

**Goal:** Produce reproducible amd64/arm64 releases and a hardened single-site deployment.

1. Complete PyInstaller specs, Dockerfiles, Compose variants, Nginx, secrets, bootstrap, rotation, inventory, and workflows.
2. Pin container images by version or digest.
3. Generate SBOMs, scan images/dependencies, sign artifacts, and verify provenance.
4. Run migration backup/restore tests.
5. Validate least privilege, read-only filesystems where possible, non-root users, log limits, health checks, and resource limits.
6. Run the entire `08-testing-and-installation.md` acceptance plan first on safe amd64 lab hardware, then ARM64.
7. Do not modify the documented live Wi-Fi-only node during automated testing.

**Exit gate:** CI is green; resource limits pass on Pi 3B; fresh install, upgrade, rollback, backup, and restore are demonstrated.

## Phase 14 — Federation Agent and Global Query Tier

**Goal:** Multiple autonomous sites appear in one global control plane.

1. Implement a per-site Go federation agent with:
   - selective metric forwarding;
   - idempotent event/RCA replication;
   - PostgreSQL-backed durable queue;
   - 60-second heartbeat;
   - mTLS and certificate rotation;
   - bandwidth/backlog/lag metrics.
2. Forward only configured aggregates by default; inject and validate `site_id`.
3. Build global storage, API, and SvelteKit views for sites, anomaly timeline, collapsed topology, and correlations.
4. Enforce tenancy/site filters in every global query.
5. Test WAN loss, clock skew, replay, duplicates, schema mismatch, site ID spoofing, global outage, and site recovery.

**Exit gate:** Disconnecting the global tier has zero site-local effect; reconnect drains queues without duplicates; global queries cannot cross unauthorized tenant/site boundaries.

## Phase 15 — Cross-Site Correlation and ASN Enrichment

**Goal:** Correlate weak site-local signals into explainable shared incidents.

1. Add a versioned local ASN database updater with checksum verification and offline fallback.
2. Normalize event time and account for measured site clock skew.
3. Implement deterministic temporal grouping first; add DBSCAN only after a labeled evaluation shows benefit.
4. Require time proximity, at least two sites, compatible metric groups, and a shared target/ASN/VPN-hub feature.
5. Store group membership, hypothesis, confidence inputs, algorithm version, and evidence.
6. Make correlation idempotent and recomputable.
7. Evaluate precision/recall against synthetic and historical multi-site incidents.

**Exit gate:** The correlator groups shared faults, rejects unrelated coincidences, and explains every confidence modifier.

## Phase 16 — Federated ML

**Goal:** Improve cold start and cross-site learning without exporting raw site data.

1. Define model/feature compatibility and minimum sample/quality requirements.
2. Implement signed, authenticated training rounds with round IDs and replay protection.
3. Clip updates, validate tensor shape and norm, reject non-finite/outlier updates, and add optional differential privacy.
4. Implement sample-weighted FedAvg with minimum participating sites and timeout behavior.
5. Preserve local opt-in, local validation, local fine-tuning, and rollback.
6. Never auto-promote a global model. Evaluate it in shadow mode against the local model first.
7. Test malicious/poisoned updates, stale models, dropped sites, mixed schema versions, privacy budget accounting, and global outage.
8. Measure cold-start improvement and detection quality. Do not promise “2 days” until verified.

**Exit gate:** No raw windows leave a site; a global model is promoted only after local validation; poisoning and privacy controls are tested.

## Phase 17 — HA and Large-Fleet Clustering

**Goal:** Remove single-server failure modes and scale based on measured capacity.

Implement HA first:

1. VictoriaMetrics dual-write with query-time deduplication.
2. PostgreSQL Patroni with a production DCS quorum, PgBouncer, backups, and restore drills.
3. Two ingest instances behind HAProxy.
4. Two API instances behind Nginx.
5. Active/standby analysis using PostgreSQL advisory locks and fencing-safe behavior.
6. Test failover during ingest, replay, API requests, WebSockets, migrations, and analysis cycles.

Then implement >500-collector clustering:

1. VictoriaMetrics cluster (`vminsert`, `vmstorage`, `vmselect`) with replication.
2. PostgreSQL read replicas for query traffic.
3. Horizontally shard analysis by stable hash of `(site_id, collector_id)` or use a durable work queue.
4. Load-test 50, 200, 500, and the target collector count; publish saturation curves and safe operating envelopes.

**Exit gate:** Failure drills meet documented RPO/RTO; no split-brain analysis writes occur; capacity claims are backed by load-test results.

## Phase 18 — Air-Gap, Advanced Alerting, Compliance, RBAC, Updates, and Operations

**Goal:** Complete all remaining extended-architecture capabilities.

### Air-gap and supervised sync

1. Support fully local DNS/NTP, package/image mirrors, PKI, model storage, and alerts.
2. Provide offline installation bundles with signatures, SBOM, and integrity manifest.
3. Implement supervised export/import bundles with IDs, hashes, signatures, schema versions, replay protection, and duplicate detection.
4. Never make USB insertion trigger unsupervised import.

### vmalert and Alertmanager

1. Add scalable rule evaluation, grouping by `(site_id, metric_group, rca_cause)`, inhibition, silences, and channel routing.
2. Retain the simple site-local dispatcher for small/air-gapped deployments.
3. Propagate `rca_cause` without creating unbounded cardinality.

### OT rules

Implement deterministic rules for:

- passive Modbus write-function observation;
- STP topology-change bursts;
- new MAC on an OT VLAN;
- confirmed PLC reboot;
- WireGuard OT tunnel degradation.

These bypass ML readiness but still require deduplication, maintenance suppression policy, evidence, and operator-visible rationale.

### Maintenance

Implement create/list/end/history endpoints, overlap rules, scoped suppression, training contamination masks, UI banners, and audit records.

### Evidence and audit

1. Canonicalize JSON before hashing.
2. Sign evidence bundles; SHA-256 alone detects changes but does not prove origin.
3. Include query parameters, time range, config/model versions, correlation evidence, and manifest.
4. Make audit rows append-only using separate DB roles and permissions; record actor, action, target, payload, source IP, request ID, and outcome.
5. Add retention, export, verification, and key-rotation procedures.

### RBAC

1. Implement viewer, operator, analyst, admin, and OT-operator roles.
2. Enforce authorization in middleware and again at query/data scope.
3. Add site/tenant scopes and second-factor workflow for sensitive OT actions.
4. Test a permission matrix, privilege escalation, stale JWT roles, revoked users, WebSockets, and exports.

### Signed collector update

1. Publish a signed version manifest and Ed25519 signature, not only a hash.
2. Verify signature, platform, version monotonicity, and checksum before staging.
3. Use a narrowly privileged updater helper; atomically switch binaries; preserve previous version; health-check; auto-rollback.
4. Roll out canary → cohort → fleet with pause/abort.
5. Test power loss, corrupt download, invalid signature, disk full, failed startup, and rollback.

### Capacity planning

Expose VM disk, PostgreSQL growth, analysis latency, training duration, model size, federation lag, queue age, and projected exhaustion. Alert on both current thresholds and forecast windows.

**Exit gate:** Complete security review, OT safety review, disaster-recovery exercise, air-gap install/sync test, RBAC matrix, evidence verification, and update rollback drill.

---

## 6. Coding Patterns Sonnet 5 Must Preserve

### Collector

- Pydantic at module boundaries; avoid anonymous dictionaries for contracts.
- `asyncio.TaskGroup` for structured concurrency.
- `asyncio.wait_for`/timeouts for every external operation.
- `asyncio.create_subprocess_exec`; never shell interpolation.
- Shared bounded thread pool (maximum two workers on Pi profile).
- Shared configurable semaphore for outbound probes.
- Reused `aiohttp.ClientSession`.
- Monotonic time for durations; UTC wall time for records.
- Catch operational errors inside checks and return typed failure results.
- Close sessions, subprocesses, sockets, database handles, and eBPF hooks during shutdown.

### Go services

- Context propagation and deadlines on all I/O.
- Graceful HTTP/gRPC shutdown.
- Structured logs with request/event/site/collector IDs.
- Parameterized SQL and bounded database pools.
- Input size limits and strict JSON/protobuf validation.
- Idempotency keys on replication and write endpoints.
- `/healthz`, `/readyz`, and Prometheus metrics.

### Data and storage

- Schema versions in every durable envelope.
- Forward-only migrations plus tested rollback/restore procedures.
- Bounded metric label cardinality; do not put arbitrary errors, URLs, payloads, or raw model values in labels.
- PostgreSQL for events/config/state/audit; VictoriaMetrics for time series.
- Retention, backup, restore, and deletion policies are part of implementation.

### Security

- mTLS between collectors/sites/global services.
- JWT is authentication context, not the sole authorization check.
- No floating `latest` tags in production.
- No secret values in logs, environment examples, fixtures, or evidence exports.
- Sign distributable artifacts and verify before execution/import.

---

## 7. Required Test Matrix

Every feature must include:

1. unit tests;
2. contract/schema tests;
3. integration tests with real storage/protocol boundaries where practical;
4. failure and recovery tests;
5. security/authorization tests;
6. observability assertions;
7. upgrade/migration tests;
8. resource or load tests proportional to the feature;
9. platform tests for Linux amd64 and ARM64 when collector-facing;
10. an end-to-end acceptance scenario.

Minimum system scenarios:

- fresh single-site install;
- collector enrollment and renewal;
- hub unavailable for 24 simulated hours and replay;
- optional capability missing;
- malformed probe response;
- duplicate event delivery;
- PostgreSQL and VictoriaMetrics restart;
- HA primary failure;
- WAN/global-tier outage;
- federation schema mismatch;
- model drift and rollback;
- unauthorized site/role access;
- maintenance suppression and contamination masking;
- evidence generation and signature verification;
- failed collector upgrade and automatic rollback;
- air-gapped export/import replay attempt.

---

## 8. Definition of Done for the Complete System

The system is complete only when:

- every extended-architecture feature is implemented or explicitly disabled by a documented deployment profile;
- the traceability matrix has no unowned or untested requirement;
- single-site operation remains fully functional without the global tier;
- all mandatory CI, integration, field, failure, HA, air-gap, and security tests pass;
- Pi 3B resource limits pass with representative workloads;
- collector, hub, federation, and global-tier upgrades and rollbacks are documented and demonstrated;
- RPO/RTO, retention, capacity, and scale limits are measured;
- threat model, OT safety case, privacy model, and operator runbooks are current;
- no architecture examples remain as placeholder production configuration;
- dashboards and alerts expose degraded operation rather than hiding it;
- a clean environment can be built and deployed solely from the repository and documented secret bootstrap process.

---

## 9. First Prompt to Give Sonnet 5

Use this as the initial execution prompt:

> Read `docs/guides/SONNET-5-IMPLEMENTATION-GUIDE.md` completely, then read all documents required by Phase 0. Do not implement later phases. Inspect the current repository and run the existing quality suite. Create the Phase 0 requirements traceability matrix and the listed ADRs, using `ARCHITECTURE-V2-EXTENDED.md` as the target behavior and current files as implementation status. Report contradictions with evidence, propose the smallest reversible decisions, and stop at the Phase 0 exit gate. Do not weaken tests or modify live hardware.

For subsequent runs, replace “Phase 0” with exactly one phase and provide the prior phase completion report. Do not ask Sonnet 5 to “implement everything” in one context window.
