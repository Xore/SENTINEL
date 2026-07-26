# Codex ↔ Sonnet 5 Coordination Ledger

> **Purpose:** Compact active control plane for SENTINEL v2 implementation.
> **Required reading:** Pull and read this file before planning, editing, or
> reviewing.
> **History:** Completed work is archived under
> [`agent-coordination-history/`](agent-coordination-history/README.md).
> **Architecture guide:** `SONNET-5-IMPLEMENTATION-GUIDE.md`

---

## Protocol

Owners: `CODEX`, `SONNET5`, `UNASSIGNED`.

Statuses:

- `READY` — owner may claim the item when its stated start gate is satisfied.
- `QUEUED` — specified next work; its start gate is not yet satisfied.
- `IN_PROGRESS` — owner has pushed an active file claim.
- `BLOCKED` — a recorded answer or dependency is required.
- `REVIEW` — implementation awaits Codex review.
- `DONE` — Codex verified the exit criteria; archive on the next ledger cleanup.

Rules:

1. Start with `git status`, `git fetch origin`, and compare `HEAD` to
   `origin/main`.
2. With a clean tree, run `git pull --ff-only origin main` before reading this
   ledger. Never pull over uncommitted work.
3. Read the newly pulled active ledger, then referenced history or commits.
4. Claim exact files before editing. A claim is active only after commit, push,
   fetch, revision comparison, and remote read-back.
5. Never edit a file claimed by the other agent.
6. Record architecture questions instead of making silent system-wide decisions.
7. Sonnet moves finished work to `REVIEW`; only Codex moves it to `DONE`.
8. Every claim, question, decision, handoff, review, or status transition is a
   prompt Git transaction.
9. Before acting on the other agent’s information, pull, read the remote entry,
   and inspect its referenced commit/diff.
10. Preserve unrelated changes. On rejected push, fetch, inspect, rebase only
    non-overlapping owned work, and re-read this ledger.
11. Use UTC ISO 8601 timestamps and actual command results.
12. Keep this file small: active work/claims/questions/exchanges only; archive
    completed work after review.

Required synchronization:

```bash
git fetch origin
git pull --ff-only origin main
# read ledger/history/commits; make one scoped coordination update
git add <only-owned-files>
git commit -m "<scoped message>"
git push origin main
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
git show origin/main:docs/guides/AGENT-COORDINATION.md
```

The revisions must match; the final command is required remote read-back.

---

## Active Work Board

| ID | Phase | Work item | Owner | Status | Prerequisites | Write scope |
|---|---:|---|---|---|---|---|
| S2-02 | 2 | Core network probe activation and hardening | SONNET5 | REVIEW | S2-01 DONE | exact scope below |
| S3-01A | 3 | Linux host-health new-file foundation | SONNET5 | REVIEW | S2-02 REVIEW | exact new-file scope below |
| S4-01A | 4 | Envelope and SQLite cold queue foundation | SONNET5 | IN_PROGRESS | S3-01A REVIEW | exact new-file scope below |
| S5-00 | 5 | Signed-update read-only preflight | SONNET5 | QUEUED | S4-01A REVIEW | ledger only |
| C1-02 | 1–13 | GitHub Actions CI/CD foundations | CODEX | IN_PROGRESS | C0-02 | `.github/**`, CI-only build/validation files |
| C2-03 | 2 | Live probe metric workflow assertion | CODEX | QUEUED | S2-02 REVIEW | `.github/workflows/integration-test.yml`, ledger |

Completed: C0-01, C0-02, S0-01, S1-01, S1-02, S2-01, C1-01, C1-03, C1-04, C2-01, C2-02. See
[July 2026 history](agent-coordination-history/2026-07.md).
Detailed Sonnet follow-on scopes and gates are in
[`SONNET-5-WORK-QUEUE.md`](SONNET-5-WORK-QUEUE.md).

---

## File Claims

| Timestamp (UTC) | Agent | Work ID | Files/directories |
|---|---|---|---|
| 2026-07-26T09:26:06Z | CODEX | C1-02 | `.github/**`, CI-only build/validation files, this ledger |
| 2026-07-26T13:00:00Z | SONNET5 | S2-02 | `collector/checks/net_icmp.py`, `collector/checks/net_tcp.py`, `collector/checks/net_http.py`, `collector/checks/net_dns.py`, `collector/checks/net_latency.py`, `collector/checks/__init__.py`, `collector/config.py` (network + latency target sections only), `collector/__main__.py` (check-registration wiring only), `collector/tests/checks/test_net_icmp.py`, `collector/tests/checks/test_net_tcp.py`, `collector/tests/checks/test_net_http.py`, `collector/tests/checks/test_net_dns.py`, `collector/tests/checks/test_net_latency.py`, `collector/tests/checks/test_base.py`, `collector/tests/test_config.py` (target-validation portions only), `collector/tests/test_main.py` (registration portions only), this ledger |
| 2026-07-26T14:10:00Z | SONNET5 | S3-01A | new files only: `collector/checks/host_cpu.py`, `collector/checks/host_memory.py`, `collector/checks/host_disk.py`, `collector/checks/host_load.py`, `collector/checks/host_network.py`, `collector/checks/host_process.py`, `collector/checks/host_service.py`, `collector/tests/checks/test_host_cpu.py`, `collector/tests/checks/test_host_memory.py`, `collector/tests/checks/test_host_disk.py`, `collector/tests/checks/test_host_load.py`, `collector/tests/checks/test_host_network.py`, `collector/tests/checks/test_host_process.py`, `collector/tests/checks/test_host_service.py`, this ledger |
| 2026-07-26T15:05:00Z | SONNET5 | S4-01A | new files only: `collector/store/__init__.py`, `collector/store/envelope.py`, `collector/store/sqlite_queue.py`, `collector/tests/store/__init__.py`, `collector/tests/store/test_envelope.py`, `collector/tests/store/test_sqlite_queue.py`, this ledger |


---

## Next Sonnet Actions

Plan updated after S2-01 corrected REVIEW handoff `becfaba`. Sonnet must pull
and read this section plus the continuity queue before doing more work.

1. Freeze S1-02 and S2-01. Do not amend their files while Codex is unavailable.
2. The S2-02 claim pushed at `748e01d` is active; implement only its exact
   preflight scope plus the approved `LatencyConfig` additions.
3. Implement S2-02 in this order: shared bounded
   target/result contract; ICMP and TCP; DNS; HTTP with credential/query
   redaction; latency; registration/config wiring; focused tests; real
   collector-to-storage/query integration. Preserve cancellation, enforce a
   finite timeout on every operation, and keep raw URLs, credentials, and
   unbounded network identifiers out of metric attributes.
4. Push the S2-02 implementation and separate REVIEW handoff with exact gates,
   then continue through S3-01A, S4-01A, and S5-00 using the disjoint gates
   below and in `SONNET-5-WORK-QUEUE.md`.

### Continuity authority through 2026-08-02

Sonnet may follow the explicit REVIEW-handoff gates in
`SONNET-5-WORK-QUEUE.md` without waiting for Codex to mark each predecessor
`DONE`. This is not self-approval: handed-off scopes are frozen, successors are
disjoint, and only Codex may mark work `DONE`. Authorized sequence: S2-01
corrections → S2-02 → S3-01A new host files → S4-01A new store files → S5-00
ledger-only preflight, then stop.

---

## S2-02 Preflight (complete)

Read-only preflight `b6c2e81` and Codex contract/API decision `67f13e0` are
archived under
[`agent-coordination-history/2026-07.md`](agent-coordination-history/2026-07.md).
`docs/contracts/METRICS.md` is the implementation authority.

After the corrected S2-01 REVIEW handoff, the S2-02 claim must enumerate: the five
`collector/checks/net_*.py` modules; `collector/checks/__init__.py`; the
network plus new latency target sections of `collector/config.py`; registration
wiring in `collector/__main__.py`; the five matching probe tests;
`collector/tests/checks/test_base.py`; target-validation portions of
`collector/tests/test_config.py`; registration portions of
`collector/tests/test_main.py`; this ledger.

Required decisions: structured unique `target_id` targets capped at 32 per
family; separate latency config disabled by default; per-family `enabled` gates
construction; exact seconds/ratio families and bounded labels from the Metrics
Contract; no raw target/URL/credential labels. Required tests and the gap
inventory are preserved in history.

---

## Open Questions

None.

Use:

```text
### Q-<number> — Title
- Raised/UTC/work ID:
- Question and affected files:
- Evidence:
- Smallest reversible proposal:
- Decision: pending
```

Archive answered questions in the commit applying the answer.

---

## Active Exchanges

### A-S2-02-1 — Sonnet 5 claim

- **Timestamp:** 2026-07-26T13:00:00Z
- **Status:** REVIEW — handoff below. (S2-01's files —
  `collector/scheduler.py`, `collector/__main__.py`'s scheduler wiring,
  `collector/tests/test_scheduler.py`, `test_main.py`'s existing
  scheduler-focused tests — were frozen and left untouched; this claim
  only added to `__main__.py`'s check-registration list and
  `test_main.py`'s registration-focused tests.)
- **Scope:** exactly the File Claims row above, per the archived S2-02
  preflight (`b6c2e81`) and Codex's contract decision
  (`67f13e0`/`docs/contracts/METRICS.md`).
- **Plan (mirrors `SONNET-5-WORK-QUEUE.md` + Next Sonnet Actions step 3):**
  1. Shared bounded target/result contract: structured `target_id`-bearing
     targets (capped at 32/family) for ICMP/HTTP/DNS, mirroring
     `TcpTarget`; a new `LatencyConfig` (disabled by default, its own
     target list, per Codex's decision — not derived from ICMP targets);
     route `net_icmp.ping`'s blocking call through
     `collector.utils.thread_pool.run_in_thread`.
  2. ICMP and TCP canonical metrics (`sentinel_collector_icmp_rtt_seconds`,
     `sentinel_collector_icmp_loss_ratio`, `sentinel_collector_tcp_connect_seconds`).
  3. DNS canonical metrics (`sentinel_collector_dns_resolve_seconds`,
     `target_id`+`record_type` labels).
  4. HTTP canonical metrics (`sentinel_collector_http_response_seconds`,
     `target_id`+`state` labels) with credential/query redaction — only
     `target_id` identifies a target in a metric, never the raw URL.
  5. Latency canonical metrics (`sentinel_collector_latency_rtt_seconds`,
     `_jitter_seconds`, `_loss_ratio`).
  6. Registration/config wiring in `__main__.py`: one instance per
     configured target per enabled check type, respecting
     `scan_level_max` and each family's `enabled` flag.
  7. Focused tests per the required test matrix (name/unit/label,
     target-ID isolation, success/failure/timeout, malformed target,
     ICMP permission denial, cancellation/no leaks, registration).
  8. Real collector-to-storage/query integration fixture.
- **Exit:** push implementation + separate REVIEW handoff with exact
  Ruff/mypy/Pylint/pytest and integration results, per the work queue.

#### S2-02 handoff

Implementation commit: `4ba26c2`.

- **Files:** exactly the claimed scope (`collector/checks/net_*.py` × 5,
  `collector/config.py`'s network/latency sections, `collector/__main__.py`'s
  registration wiring, and the matching test files). `collector/checks/
  __init__.py` needed no change — `BaseCheck`'s existing `is_enabled()`/
  `aclose()` contract already supported every concrete check's override.
- **Req 1 (shared target/result contract):** `IcmpTarget`/`HttpTarget`/
  `DnsTarget`/`LatencyTarget` (all `target_id` + one operational field) and
  `TcpTarget` (gained `target_id`) — each with a `target_id` DNS-label
  validator (reusing the `collector_id`/`site_id` slug rule) and a
  format validator on the operational field (`_validate_host`: IP or
  lenient hostname; `_validate_target_url`: absolute `http(s)://`). A
  shared `_validate_target_list` caps every family at 32 targets and
  rejects duplicate `target_id`s. New `LatencyConfig` (own targets,
  `enabled=False` default, `sample_count`/`interval_s`/`timeout_s`) —
  separate from `IcmpConfig` per Q-4, so enabling bursts is an explicit
  opt-in, not an automatic multiplier on every ICMP target.
  `net_icmp.ping()` now runs via `collector.utils.thread_pool.run_in_thread`
  (the bounded 2-worker pool) instead of the default `asyncio.to_thread`
  executor.
- **Req 2 (ICMP/TCP metrics):** `IcmpCheck` emits
  `sentinel_collector_icmp_rtt_seconds` (histogram, seconds) and
  `sentinel_collector_icmp_loss_ratio` (gauge, ratio), `target_id`-only
  label. `TcpCheck` emits `sentinel_collector_tcp_connect_seconds`
  (histogram), `target_id`-only label. Both convert the existing ms/pct
  internal values to seconds/ratio only at the metric boundary —
  `CheckResult.metrics`/`.labels` (internal/test-facing, never exported)
  are otherwise unchanged.
- **Req 3 (DNS metrics):** `DnsCheck` emits
  `sentinel_collector_dns_resolve_seconds`, labels `target_id` +
  `record_type` (already restricted to METRICS.md's enumerated allow-list
  at config-load time, so it's safe as a label per the contract's own
  carve-out).
- **Req 4 (HTTP metrics + redaction):** `HttpCheck` emits
  `sentinel_collector_http_response_seconds`, labels `target_id` + `state`
  (`ok`/`error` from the existing strict-2xx check — never the raw status
  code or URL). Verified by a test asserting the recorded attribute set is
  exactly `{target_id, state}` even when the target URL carries a query
  string.
- **Req 5 (latency metrics):** `LatencyCheck` emits
  `sentinel_collector_latency_rtt_seconds`, `_jitter_seconds` (gauges,
  seconds), and `_loss_ratio` (gauge, ratio), `target_id`-only label;
  `sample_count`/`interval_s`/`timeout_s` now come from `LatencyConfig`
  (constructor override still available, used by tests).
- **Req 6 (registration):** `__main__._build_checks()` constructs one
  instance per configured target for every family (plus heartbeat),
  unconditionally — each check's own `is_enabled()` now also requires its
  family's `enabled` flag (previously read but never checked), independent
  of `scan_level_max`.
- **Req 7 (tests):** per-check canonical metric name/unit/label tests (fake
  meter) and target-only-label assertions for all five checks; ICMP
  permission-denial (`PermissionError`) and timeout tests; HTTP/DNS timeout
  tests; DNS external-cancellation test (`asyncio.wait_for` against a slow
  fake resolver); Latency external-cancellation test; `test_config.py`'s
  new `TestTargetValidation` (bad `target_id`, duplicates, 32-cap boundary,
  malformed host/URL, DNS record-type allow-list, `LatencyConfig`
  defaults); `test_main.py`'s new `TestBuildChecks` (one instance per
  target per family, one `DnsCheck` per configured record type, multiple
  targets in one family, disabled-family/disabled-by-default-latency still
  construct but report `is_enabled() is False`).
- **Req 8 (integration gate):** ran the real disposable dev hub stack
  (`deploy/hub/docker-compose.dev.yml` — production Go migration,
  enrollment, mTLS OTLP ingest, VictoriaMetrics; no modifications to any
  `deploy/**` file). Enrolled `dev-node-1`/`site-a` with the standard
  one-time token, then ran the real Python collector (root, for the raw
  ICMP socket) configured via env vars only against safe always-reachable
  loopback targets: ICMP/latency to `127.0.0.1`, TCP to the stack's own
  VictoriaMetrics port, HTTP to VictoriaMetrics's `/health`, DNS resolving
  `localhost`. `OTEL_METRIC_EXPORT_INTERVAL=2000` (env-only, no code
  change) so the periodic exporter flushed within the run. Queried
  VictoriaMetrics directly afterward: all five families
  (`sentinel_collector_icmp_rtt_seconds`/`_loss_ratio`,
  `_tcp_connect_seconds`, `_http_response_seconds`, `_dns_resolve_seconds`,
  `_latency_rtt_seconds`/`_jitter_seconds`/`_loss_ratio`) landed with
  exactly `site_id=site-a`, `collector_id=dev-node-1`,
  `service.name=sentinel-collector`, and the correct bounded `target_id`
  (plus `state`/`record_type` where applicable) — no raw host, URL, or
  status code on any series. Stack torn down (`down -v`) and temp
  enrollment files removed afterward; `sudo docker ps -a` confirmed empty.
- **Behavior retained:** every S1-02/S2-01 test and behavior is untouched;
  all previously-passing check tests (success/failure paths, shared HTTP
  session, DNS resolver reuse, etc.) still pass unchanged.
- **Gates, run from `collector/` with the repo's `.venv` (Python 3.12.3 /
  pylint 3.3.7 / ruff 0.16.0 / mypy 1.20.2 / pytest 9.1.1):**
  - `ruff check .` → all checks passed.
  - `mypy .` → `Success: no issues found in 35 source files` (pre-existing
    `annotation-unchecked` notes on untyped test bodies only).
  - `pylint collector tests` (exact CI invocation) → 10.00/10.
  - `pytest -q` → 259 passed, 1 skipped (`test_sighup_noop_without_signal`,
    `non-POSIX only` — pre-existing).
  - Windows Ruff/mypy/Pylint/pytest: **not run** — no Windows environment
    available to this session.
- **Remaining risk:** none identified against the current contract; the
  integration run used loopback/self-targets for safety and speed rather
  than external hosts, but exercises the identical export path C1-03's
  automated workflow already validates for the heartbeat metric.

### A-S3-01A-1 — Sonnet 5 claim

- **Timestamp:** 2026-07-26T14:10:00Z
- **Status:** REVIEW — handoff below. All S2-02 files (and S1-02/S2-01
  before them) are frozen and untouched by this claim.
- **Scope:** exactly the File Claims row above — seven new check modules
  plus seven matching new test modules. No edits to `config.py`,
  `__main__.py`, `checks/__init__.py`, dependencies, contracts, or
  workflows, per the work queue.
- **Plan:** independently testable `HostCpuCheck`/`HostMemoryCheck`/
  `HostDiskCheck`/`HostLoadCheck`/`HostNetworkCheck`/`HostProcessCheck`/
  `HostServiceCheck`, each a `BaseCheck` subclass following the existing
  never-raise/`CheckResult` contract, reading real Linux system state
  (`/proc/stat`, `/proc/meminfo`, `/proc/net/dev`, `shutil.disk_usage`,
  `os.getloadavg`, bounded process/service allow-lists) with blocking
  filesystem/subprocess calls routed through the bounded executor or true
  async subprocess primitives. No registration in `__main__.py` and no
  OTel instrument creation this claim — both are explicitly a later
  Codex-reviewed claim per the work queue, so these checks compute
  `CheckResult.metrics`/`.labels` only, the same shape `net_*.py` checks
  had before S2-02 wired instruments.
- **Exit:** push implementation + separate REVIEW handoff with exact
  Ruff/mypy/Pylint/pytest results, per the work queue.

#### S3-01A handoff

Implementation commit: `8e96e8c`.

- **Files:** exactly the claimed new-file scope — seven `host_*.py` check
  modules and seven matching test modules. No existing file was edited.
- **`host_cpu.py`:** `/proc/stat`'s aggregate `cpu` line, delta-based
  utilization between consecutive `run()` calls (stored as instance
  state); the first call after construction records a baseline only,
  since utilization needs an interval to be meaningful.
- **`host_memory.py`:** `/proc/meminfo`, preferring the kernel's own
  `MemAvailable` (reclaimable-cache-aware) with a
  `MemFree+Buffers+Cached` fallback for kernels too old to report it.
- **`host_disk.py`:** `shutil.disk_usage` for one configured mount path
  — genuinely cross-platform (unlike the `/proc`-based checks), so no
  platform guard.
- **`host_load.py`:** `os.getloadavg()`; not routed through the bounded
  thread pool since it's a fast syscall reading a precomputed kernel
  value, not a blocking call — matches
  `docs/guides/ASYNCIO-OPTIMIZATION.md` §3's own scope for the pool.
- **`host_network.py`:** `/proc/net/dev`, same delta-across-cycles
  approach as `host_cpu.py`, for one configured interface's RX/TX byte
  rate.
- **`host_process.py`:** one named process per instance (mirrors
  `net_tcp.py`'s one-target-per-instance shape — a bounded allow-list
  becomes however many instances a later registration claim constructs).
  Scans `/proc/<pid>/comm`; a PID that vanishes or becomes unreadable
  mid-scan is skipped, not treated as a hard failure — only a failure to
  list `/proc` itself propagates. Documented the kernel's 15-character
  `comm` truncation as a known limitation, not a bug.
- **`host_service.py`:** one named systemd service per instance, via
  `systemctl is-active` over `asyncio.create_subprocess_exec` — genuinely
  async I/O, not routed through the thread pool. A timeout kills the
  subprocess before re-raising; a missing `systemctl` binary (non-systemd
  Linux, minimal containers) raises a clear `RuntimeError` instead of an
  opaque `FileNotFoundError`.
- **Shared design decisions:** all six file-reading/subprocess checks
  route blocking work through `collector.utils.thread_pool.run_in_thread`
  except `host_load`/`host_service` (neither is a blocking call — see
  above). `host_cpu`/`host_memory`/`host_network`/`host_process` report a
  clear `ok=False` "unsupported platform" failure on non-Linux instead of
  crashing; `host_disk` doesn't need this (portable) and `host_load`/
  `host_service` fail naturally through their own real error paths
  (`OSError`/`AttributeError`, missing `systemctl`) without a separate
  guard. No check creates an OTel instrument or gets constructed by
  `__main__.py` — both explicitly deferred to a later claim, so every
  `CheckResult.metrics`/`.labels` here is internal/test-facing only, the
  same shape `net_*.py`'s checks had before S2-02.
- **Tests:** each module has success, malformed/missing-input, and
  cancellation-of-a-slow-call coverage; permission-denial where a real
  chmod is meaningful (`host_cpu`, `host_memory`, `host_network`,
  `host_process`); platform/tool-unavailability handling
  (`host_cpu`/`host_memory`/`host_network`/`host_process`'s non-Linux
  guard; `host_load`'s missing-`getloadavg`-attribute case;
  `host_service`'s missing-`systemctl` case). `host_process`'s tests build
  a real fake `/proc` directory tree under `tmp_path` rather than mocking
  individual calls. `host_service`'s tests use a fake async subprocess
  object (`communicate`/`kill`/`wait`) to exercise the timeout-kills-the-
  process path without a real hung process. No test depends on the
  developer host's actual process/service/interface state.
- **Behavior retained:** every S1-02/S2-01/S2-02 test and behavior is
  unchanged.
- **Gates, run from `collector/` with the repo's `.venv` (Python 3.12.3 /
  pylint 3.3.7 / ruff 0.16.0 / mypy 1.20.2 / pytest 9.1.1):**
  - `ruff check .` → all checks passed.
  - `mypy .` → `Success: no issues found in 49 source files` (pre-existing
    `annotation-unchecked` notes on untyped test bodies only).
  - `pylint collector tests` (exact CI invocation) → 10.00/10.
  - `pytest -q` → 340 passed, 1 skipped (`test_sighup_noop_without_signal`,
    `non-POSIX only` — pre-existing).
  - Windows Ruff/mypy/Pylint/pytest: **not run** — no Windows environment
    available to this session. The four Linux-only checks' own tests
    explicitly simulate non-Linux behavior via monkeypatching rather than
    depending on an actual Windows run.
- **Remaining risk:** none identified against the current contract;
  registration/config wiring and OTel instrument design for these seven
  checks remain open for the later claim the work queue already
  anticipates.

### A-S4-01A-1 — Sonnet 5 claim

- **Timestamp:** 2026-07-26T15:05:00Z
- **Status:** IN_PROGRESS. All S1-02/S2-01/S2-02/S3-01A files remain frozen
  and untouched by this claim.
- **Scope:** exactly the File Claims row above — a new `collector/store/`
  package (envelope + SQLite cold queue) and matching new
  `collector/tests/store/` package. No dependency, config, transport,
  scheduler, probe, or entry-point edits, per
  `SONNET-5-WORK-QUEUE.md`'s S4-01A spec.
- **Plan:**
  1. `envelope.py` — immutable, frozen `Envelope` dataclass: version `1`
     (rejects any other value now or on deserialization); `event_id`
     (UUID4, canonicalized), `site_id`/`collector_id` (existing DNS-label
     bounded-identity rule, mirrored locally since `config.py` is frozen/
     out of scope this claim); `observed_at`/`created_at`/`expires_at`
     (aware UTC only, `expires_at` must follow both `observed_at` and
     `created_at`); non-negative `attempt_count`; `content_type`; opaque
     `payload` bytes; a SHA-256 `checksum` computed from `payload` at
     construction. Deterministic `to_bytes`/`from_bytes` (sorted-key JSON,
     base64 payload) with checksum re-verification on deserialize and a
     `with_attempt_incremented()` copy-on-write helper so the frozen
     envelope never needs in-place mutation.
  2. `sqlite_queue.py` — stdlib `sqlite3`, WAL journal mode, busy-timeout
     pragma, explicit transactions per operation. `queue` table keyed by
     `event_id` (idempotent `INSERT OR IGNORE` covers duplicates) ordered
     by `(created_at, event_id)`; a separate `quarantine` table for rows
     that fail to deserialize (checksum mismatch/malformed blob) so a
     poisoned record can't wedge the queue. Constructor-supplied
     `max_records`/`max_bytes` caps enforced with oldest-first eviction
     before every insert. `peek`/`acknowledge` (delete on ack)/
     `mark_attempt` (re-serializes with `with_attempt_incremented()`)/
     `remove_expired`/`count`/`total_bytes`/`quarantined_count`/`close`.
  3. Tests per the work queue's required list: round-trip/determinism,
     checksum corruption, unknown version, duplicate idempotency,
     crash/reopen durability (abandoned connection, fresh instance against
     the same file), concurrent producer/consumer (both same-instance
     multi-thread and separate-instance-same-file), busy/locked database,
     cap eviction (bytes and records), expiry removal, retry
     (`created_at`,`event_id`) order, acknowledgement, and a simulated
     24-hour backlog drain using fake spread-out timestamps (not real
     wall-clock waiting).
  4. Run all four Linux gates (Ruff/mypy/Pylint/pytest).
- **Exit:** push implementation + separate REVIEW handoff with exact gate
  results, per the work queue. LMDB hot tier, configuration, and transport
  integration remain later, separately reviewed claims.

### C2-03 — Live probe metric workflow assertion

- **Status:** QUEUED; no file claim is active.
- **Start gate:** S2-02 has a pushed REVIEW handoff that emits at least one
  canonical core probe family through the real collector.
- **Scope:** extend the existing production-path workflow to configure a
  deterministic local probe, require its canonical metric through the
  authenticated bounded API with exact identity/target labels, and assert raw
  target data is absent. This is deliberately split from completed C2-02 so
  contract/API catalogue work is not held open by collector implementation.

### C1-02 — CI/CD checkpoint

- Commits `8417066` and `4a7cf25`: backend gofmt/vet/race/build,
  empty-PostgreSQL migration validation, corrected action versions, Go CodeQL.
- Passing runs: backend `30196549053`; CodeQL `30196596608`; collector/Pylint at
  `8417066`.
- Backend run `30198152790` additionally passed the production ingest container
  build and dev Compose validation at `45f8e65`.
- Commit `d9f07fc` added the ingest supply-chain workflow with immutable action
  pins. Run `30198390017` passed the local image build, fixed high/critical
  Grype gate, and SPDX JSON SBOM generation; the publish job correctly skipped
  on a main-branch push.
- Only an explicit `v*` tag authorizes GHCR publication. That path builds
  `linux/amd64` and `linux/arm64`, emits version and commit tags (never
  `latest`), signs the digest with Cosign/GitHub OIDC, and attaches GitHub
  provenance and SBOM attestations. The tag-only path remains unexecuted until
  the user intentionally creates a release tag.
- Aqua Trivy actions were deliberately excluded after verifying the March 2026
  credential-compromise advisory; Anchore actions are pinned to reviewed commit
  SHAs instead of mutable tags.
- The collector workflow now exercises the full Ruff/mypy/Pylint/pytest gate on
  both Ubuntu/Python 3.12 and Windows/Python 3.14. The Windows leg is expected
  to expose S1-02's currently assigned `ThreadPoolExecutor` Pylint issue until
  Sonnet pushes its corrected REVIEW handoff; it is intentionally a required
  gate rather than an allowed failure. Local Windows/Python 3.14.5 validation
  at 2026-07-26T10:38:14Z: Ruff passed, mypy passed (35 files), pytest passed
  (161 passed, 1 POSIX-only skip), and Pylint reproduced only
  `collector/utils/thread_pool.py:13 E0611`, rating 9.96/10.
- C1-03 automated the Phase 1 vertical-slice gate. GitHub run
  `30198940453` passed in 2m38s: disposable hub startup, migration and seed,
  production Go enrollment/mTLS ingest, real Python collector export, exact
  VictoriaMetrics identity query, diagnostics, and volume cleanup.
- Still gated: intentional tag-path verification, protected delivery, canary
  rollout, and rollback.

---

## Archive Procedure

When an item becomes `DONE`, the reviewer:

1. appends assignment, claim, handoff, review, results, decisions, and SHAs to
   `agent-coordination-history/YYYY-MM.md`;
2. removes its active claim and detailed exchange here;
3. updates the completed reference;
4. commits and pushes archive plus compact ledger together;
5. fetches and reads both files back from `origin/main`.

Git history is the lossless source for verbose earlier ledger states. Monthly
history is the readable durable index.
