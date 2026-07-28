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
| S2-02 | 2 | Core network probe activation and hardening | CODEX | REVIEW | S2-01 DONE | Codex takeover below |
| S3-01A | 3 | Linux host-health new-file foundation | SONNET5 | REVIEW | S2-02 REVIEW | exact new-file scope below |
| S4-01A | 4 | Envelope and SQLite cold queue foundation | SONNET5 | REVIEW | S3-01A REVIEW | exact new-file scope below |
| S5-01 | 5 | Signed updater verifier and installer foundation | SONNET5 | QUEUED | S2-02, S3-01A, S4-01A DONE; C5-01 DONE | exact scope in S5-01 gate |
| C1-02 | 1–13 | GitHub Actions CI/CD foundations | CODEX | IN_PROGRESS | C0-02 | `.github/**`, CI-only build/validation files |
| C2-03 | 2 | Live probe metric workflow assertion | CODEX | REVIEW | S2-02 REVIEW | handoff below |

Completed: C0-01, C0-02, S0-01, S1-01, S1-02, S2-01, S5-00, C1-01, C1-03, C1-04, C2-01, C2-02, C5-01. See
[July 2026 history](agent-coordination-history/2026-07.md).
Detailed Sonnet follow-on scopes and gates are in
[`SONNET-5-WORK-QUEUE.md`](SONNET-5-WORK-QUEUE.md).

---

## File Claims

| Timestamp (UTC) | Agent | Work ID | Files/directories |
|---|---|---|---|
| 2026-07-28T18:00:46Z | CODEX | C2-03 | `.github/workflows/integration-test.yml`, this ledger |
| 2026-07-26T09:26:06Z | CODEX | C1-02 | `.github/**`, CI-only build/validation files, this ledger |
| 2026-07-28T17:42:13Z | CODEX | S2-02 | takeover of Sonnet's frozen exact claim: `collector/checks/net_icmp.py`, `collector/checks/net_tcp.py`, `collector/checks/net_http.py`, `collector/checks/net_dns.py`, `collector/checks/net_latency.py`, `collector/checks/__init__.py`, `collector/config.py` (network + latency target sections only), `collector/__main__.py` (check-registration wiring only), `collector/tests/checks/test_net_icmp.py`, `collector/tests/checks/test_net_tcp.py`, `collector/tests/checks/test_net_http.py`, `collector/tests/checks/test_net_dns.py`, `collector/tests/checks/test_net_latency.py`, `collector/tests/checks/test_base.py`, `collector/tests/test_config.py` (target-validation portions only), `collector/tests/test_main.py` (registration portions only), this ledger |
| 2026-07-26T14:10:00Z | SONNET5 | S3-01A | new files only: `collector/checks/host_cpu.py`, `collector/checks/host_memory.py`, `collector/checks/host_disk.py`, `collector/checks/host_load.py`, `collector/checks/host_network.py`, `collector/checks/host_process.py`, `collector/checks/host_service.py`, `collector/tests/checks/test_host_cpu.py`, `collector/tests/checks/test_host_memory.py`, `collector/tests/checks/test_host_disk.py`, `collector/tests/checks/test_host_load.py`, `collector/tests/checks/test_host_network.py`, `collector/tests/checks/test_host_process.py`, `collector/tests/checks/test_host_service.py`, this ledger |
| 2026-07-26T15:05:00Z | SONNET5 | S4-01A | new files only: `collector/store/__init__.py`, `collector/store/envelope.py`, `collector/store/sqlite_queue.py`, `collector/tests/store/__init__.py`, `collector/tests/store/test_envelope.py`, `collector/tests/store/test_sqlite_queue.py`, this ledger |


---

## Next Sonnet Actions

Plan updated after the user assigned S2-02 corrections to Codex while Sonnet is
unavailable. Sonnet must keep every S2-02 file frozen until Codex publishes a
new REVIEW handoff.

1. Keep S1-02/S2-01 and every S3-01A/S4-01A file frozen. S5-00 is approved
   and archived; do not claim S5-01 before its explicit gate is satisfied.
2. Codex owns the still-active exact S2-02 claim and will address only the five
   correction groups in Codex review 1. Preserve accepted metric names, units,
   bounded attributes, target caps, separate latency configuration, and
   integration behavior.
3. Codex will push one focused S2-02 correction commit and a separate REVIEW
   handoff with exact Ruff, mypy, Pylint, pytest, Windows, and integration
   results. Sonnet must not amend S2-02 or later REVIEW scopes meanwhile.

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

## S5-01 Gate

S5-00 and C5-01 are `DONE`. The release-side authority is
[`COLLECTOR-UPDATE-MANIFEST-V1.md`](../contracts/COLLECTOR-UPDATE-MANIFEST-V1.md);
cross-language golden inputs are under
`backend/api/internal/updatemanifest/testdata/`. The approved preflight,
resolved Q-6 through Q-11 decisions, and exact future claim are indexed in
[July 2026 history](agent-coordination-history/2026-07.md).

S5-01 remains `QUEUED` until S2-02, S3-01A, and S4-01A are all `DONE`. Its later
claim may enumerate only: new `collector/updater/` modules; matching new
`collector/tests/updater/` tests; the three named collector/updater systemd
unit/timer files under `deploy/systemd/`; and this ledger. It must consume the
contract and fixtures without changing release-side schema, signing CLI,
workflows, backend runtime, or earlier collector scopes.

---

## Open Questions

None.

---

## Active Exchanges

### A-S2-02-1 — Sonnet 5 claim

- **Timestamp:** 2026-07-26T13:00:00Z
- **Status:** REVIEW — Codex review 1 returned focused corrections below.
  (S2-01's files —
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

#### S2-02 Codex review 1

- **Timestamp:** 2026-07-28T16:15:15Z.
- **Reviewed:** implementation `4ba26c2`, handoff `e208ef3`, exact claimed
  diff, S2-02 work queue, preflight `b6c2e81`, authoritative Metrics Contract
  decision `67f13e0`, focused tests, and GitHub runs.
- **Accepted and frozen:** canonical metric names/types/units; bounded OTel
  attributes; per-family target cap and unique `target_id`; separate
  disabled-by-default latency configuration; capped ICMP executor; production
  registration shape; real collector-to-storage/query integration.
- **Verification:** exact-commit Windows/Python 3.14 Ruff and mypy passed,
  Pylint rated 10.00/10, and pytest passed 259 tests with one POSIX-only skip.
  GitHub collector `30203065093`, Pylint `30203065150`, Phase 1 integration
  `30203065100`, and CodeQL `30203065205` all passed at `4ba26c2`.
- **Disposition:** not approved. Make only these corrections:
  1. `docs/contracts/METRICS.md` explicitly requires each family `enabled`
     flag to gate construction in the entry point. `_build_checks()` currently
     constructs disabled families and its tests deliberately assert the
     opposite contract. Skip construction for every disabled family; retain
     scan level as the independent scheduler gate and test enabled, disabled,
     empty, and latency-default cases.
  2. Enforce positive **finite** probe timeouts. Pydantic's current `gt=0`
     accepts `float("inf")` for ICMP, TCP, HTTP, DNS, and latency, contradicting
     the work queue's finite-timeout requirement. Reject zero, negative,
     `nan`, and both infinities for all five families with deterministic tests.
  3. Complete HTTP credential/query redaction. `HttpCheck.run()` currently
     places the raw URL in `CheckResult.labels` and the degraded log, so a URL
     such as `https://user:pass@host/path?token=secret` leaks credentials and
     query material outside the operational request. Use `target_id` in result
     labels/log context, sanitize exception text that can contain a URL, and
     add success plus failure assertions proving secrets do not appear in
     metrics, results, errors, or captured logs.
  4. Make the ICMP target contract match runtime behavior and isolate replies.
     Configuration explicitly accepts IPv6 while `_ping_once_blocking()` is
     IPv4-only (`AF_INET` plus an IPv4 header parser); either reject IPv6 for
     ICMP/latency with a clear validation error or implement ICMPv6. Also
     validate the reply source: the current code ignores `recvfrom()`'s address,
     so two checks with a 16-bit identifier/sequence collision can accept the
     other target's reply. Add wrong-source and supported-address tests.
  5. Complete the preflight's cancellation/no-leak matrix. DNS and latency have
     external-cancellation tests, but ICMP, TCP, and HTTP do not. Add
     deterministic cancellation propagation and cleanup assertions for all
     five probes; for the bounded ICMP worker, demonstrate that cancellation
     cannot create unbounded or permanently occupied pool work beyond the now
     finite configured timeout.
- **Exit:** push one correction implementation commit and a separate REVIEW
  handoff with the exact changed files and all gates. Do not change metric
  contracts, workflows, architecture documents, dependencies, or later
  S3/S4/S5 implementation files.

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

#### S4-01A handoff

Implementation commit: `d9bef65`.

- **Files:** exactly the claimed new-file scope — `collector/store/__init__.py`,
  `collector/store/envelope.py`, `collector/store/sqlite_queue.py`, and three
  matching new test modules. No existing file was edited; S1-02/S2-01/S2-02/
  S3-01A remain untouched.
- **`envelope.py`:** frozen `Envelope` dataclass, version `1` (rejected at
  both construction and `from_bytes` for any other value). `event_id` is
  canonicalized via `uuid.UUID`; `site_id`/`collector_id` reuse the ADR 0009
  DNS-label rule, duplicated locally as a 1-line regex since `config.py` is
  frozen/out of scope this claim (not imported from there). `observed_at`/
  `created_at`/`expires_at` must be aware UTC; `expires_at` must be strictly
  after both `observed_at` and `created_at` — this is enforced at
  construction, so an already-expired envelope cannot be built in the first
  place. `checksum` is a SHA-256 digest of `payload` computed automatically
  in `__post_init__` (any caller-supplied value is ignored). `to_bytes`/
  `from_bytes` use deterministic sorted-key, no-whitespace JSON with
  base64-encoded payload bytes; `from_bytes` re-verifies the stored checksum
  against a fresh digest of the decoded payload, so a bit-flip in either the
  payload or the checksum field itself is caught as corruption, not silently
  accepted. `with_attempt_incremented()` returns a copy (`dataclasses.replace`)
  since the envelope is frozen.
- **`sqlite_queue.py`:** stdlib `sqlite3` only (no async — this is a
  synchronous foundation module; wrapping its blocking calls in
  `collector.utils.thread_pool.run_in_thread` for the async collector loop is
  explicitly a later transport-integration claim). WAL journal mode plus a
  busy-timeout pragma set from a validated positive `busy_timeout_ms`
  constructor argument (PRAGMA doesn't accept bound parameters, so the value
  is int-coerced and range-checked before formatting into the statement, not
  passed through as arbitrary SQL). `queue` table keyed by `event_id`
  (`INSERT OR IGNORE` after an existence check gives idempotent duplicate
  enqueue); index and `ORDER BY (created_at, event_id)` give deterministic
  oldest-first retrieval. `_evict_for_capacity` evicts oldest-first before
  every insert until both `max_records`/`max_bytes` are satisfied or the
  queue is empty — a single incoming record larger than `max_bytes` is still
  inserted rather than rejected, since there's nothing left to evict. A row
  that fails `Envelope.from_bytes` (checksum mismatch, malformed JSON, future
  version) is moved to a separate `quarantine` table and skipped rather than
  raised, in `peek()` and `mark_attempt()` alike, so one corrupted record
  can't wedge the queue. `acknowledge`/`mark_attempt` on an unknown
  `event_id` are safe no-ops (`None`/no deletion) rather than errors. An
  internal `threading.Lock` serializes access from multiple threads sharing
  one instance; WAL mode plus the busy-timeout pragma handle multiple
  separate `SqliteQueue` instances (or processes) against the same file.
- **Tests:** round-trip/determinism (`to_bytes` is stable, `from_bytes`
  round-trips exactly); every validation rule rejected (bad `site_id`/
  `collector_id`, non-UUID `event_id`, naive/non-UTC datetimes, `expires_at`
  ordering, negative `attempt_count`, empty `content_type`, non-bytes
  `payload`, unsupported `version`); checksum corruption via a tampered
  `payload_b64` and via a tampered `checksum` field, both at the envelope
  layer and via direct SQLite row corruption (quarantined, not returned, not
  raised); unknown/future version rejected at both layers; duplicate
  `event_id` enqueue is a no-op; crash/reopen durability (an abandoned
  connection with no explicit `close()`, then a fresh instance against the
  same file); concurrent producer/consumer via both many threads sharing one
  instance and two separate instances against the same file; busy/locked
  database (a real held `BEGIN IMMEDIATE` transaction from a second
  connection, both the raises-after-a-short-timeout and succeeds-after-
  waiting-within-timeout cases); byte-cap and record-cap oldest-first
  eviction, including the oversize-single-record case; expiry removal
  (only past-expiry rows removed) and its naive-datetime rejection;
  `(created_at, event_id)` retry order proven by enqueuing out of order;
  acknowledgement (exactly one row removed, double-ack and unknown-id are
  safe no-ops); attempt increment (persisted, and on a corrupted row
  quarantines and returns `None`); a simulated 24-hour backlog of 288
  envelopes (5-minute spacing) drained via repeated `peek`+`acknowledge`
  entirely in chronological order with nothing left in the queue or
  quarantine — built from fake spread-out timestamps, not real wall-clock
  waiting.
- **Gates, run from `collector/` with the repo's `.venv` (Python 3.12.3 /
  pylint 3.3.7 / ruff 0.16.0 / mypy 1.20.2 / pytest 9.1.1):**
  - `ruff check .` → all checks passed.
  - `mypy .` → `Success: no issues found in 55 source files` (pre-existing
    `annotation-unchecked` notes on untyped test bodies only).
  - `pylint collector tests` (exact CI invocation) → 10.00/10. Two scoped
    `# pylint: disable=` comments were added in the new files themselves —
    `too-many-instance-attributes` on `Envelope` (11 fields, all individually
    meaningful per the published envelope decision; not consolidable the way
    S2-02's `LatencyCheck` gauges were) and `too-many-arguments` on the test
    helper `_make()` (mirrors all 11 fields for validation-rejection tests).
    Neither touches `pyproject.toml`, which remains out of scope for this
    claim.
  - `pytest -q` → 406 passed, 1 skipped (`test_sighup_noop_without_signal`,
    `non-POSIX only` — pre-existing). The 66 new store tests were re-run
    three times in isolation to confirm no timing flakiness in the
    busy-timeout/concurrency tests.
  - Windows Ruff/mypy/Pylint/pytest: **not run** — no Windows environment
    available to this session.
- **Remaining risk:** none identified against the current claim scope. LMDB
  hot tier, `CollectorSettings` wiring, and transport integration (including
  routing `SqliteQueue`'s blocking calls through `run_in_thread`) remain open
  for later, separately reviewed claims, as the work queue anticipates.

### C2-03 — Live probe metric workflow assertion

- **Status:** REVIEW; claim published 2026-07-28T18:00:46Z.
- **Start gate:** S2-02 has a pushed REVIEW handoff that emits at least one
  canonical core probe family through the real collector.
- **Scope:** extend the existing production-path workflow to configure a
  deterministic local probe, require its canonical metric through the
  authenticated bounded API with exact identity/target labels, and assert raw
  target data is absent. This is deliberately split from completed C2-02 so
  contract/API catalogue work is not held open by collector implementation.
- **Exact claim:** `.github/workflows/integration-test.yml` and this ledger
  only. Configure a deterministic local HTTP target served inside the runner,
  wait for `sentinel_collector_http_response_seconds` through the existing
  production collector-to-VictoriaMetrics path, query it through the
  authenticated bounded metrics API, require exact `site_id`,
  `collector_id`, `target_id`, and `state` labels, and prove the configured
  URL/query secret is absent from stored series and collector logs. Preserve
  the heartbeat, site-isolation, diagnostics, and cleanup assertions.

#### C2-03 Codex review handoff

- **Timestamp:** 2026-07-28T18:11:49Z.
- **Implementation:** `de67fe4`; exported-histogram query correction
  `dc571f8`.
- **Files:** exactly `.github/workflows/integration-test.yml`; this separate
  handoff edits only the ledger.
- **Behavior:** the disposable production-path job starts a loopback HTTP
  target whose URL contains a query secret, configures `ci-http` through the
  real nested collector environment, enrolls the collector, and requires both
  heartbeat and `sentinel_collector_http_response_seconds_count` in
  VictoriaMetrics. It then requires the same HTTP histogram count through the
  authenticated bounded range API with exact `site_id=site-a`,
  `collector_id=dev-node-1`, `target_id=ci-http`, and `state=ok`. Storage,
  API, and collector-log assertions reject the raw URL, raw-target labels, and
  query secret. Existing site-isolation, last-seen, diagnostics, and
  volume/process cleanup remain active.
- **Why `_count`:** OpenTelemetry exports the logical histogram
  `sentinel_collector_http_response_seconds` to VictoriaMetrics as catalogued
  Prometheus-compatible `_bucket`, `_sum`, and `_count` series. The first run
  `30385692408` intentionally exposed that the logical base name has no stored
  vector; correction `dc571f8` queries the bounded `_count` series through
  both storage and API without changing collector or backend code.
- **Validation:** `actionlint` passed using
  `go run github.com/rhysd/actionlint/cmd/actionlint@latest`; local
  Python/Pydantic parsing confirmed the workflow's nested target, interval,
  and timeout environment values. GitHub phase-1 integration run
  `30386119783` passed every step in 1m59s at exact `dc571f8`, including the
  live probe and API assertions. CodeQL run `30386123418` also passed.
- **Review request:** independently inspect `278e49f..dc571f8` against the
  exact C2-03 claim. Keep the workflow frozen until review; do not mark this
  implementer's handoff DONE without independent verification.

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

### A-S2-02-2 — Codex takeover

- **Timestamp:** 2026-07-28T17:42:13Z.
- **Authority:** the user assigned Sonnet's S2-02 correction work to Codex
  while Sonnet is unavailable until Friday.
- **Scope:** exactly the replacement File Claims row above. The takeover
  preserves Sonnet's original implementation and handoff attribution; Codex
  owns only the five focused correction groups from review 1.
- **Frozen:** S1/S2-01 and every S3-01A/S4-01A/S5 file, contracts,
  dependencies, workflows, and architecture documents.
- **Exit:** one correction implementation commit, full Windows and Ubuntu
  collector gates, production-path integration verification, and a separate
  pushed REVIEW handoff. Sonnet must not edit the active scope before that
  handoff.

#### S2-02 Codex correction handoff

- **Timestamp:** 2026-07-28T17:51:27Z.
- **Status:** REVIEW. Implementation commit `0e254b0`.
- **Files changed:** `collector/config.py`, `collector/__main__.py`,
  `collector/checks/net_http.py`, `collector/checks/net_icmp.py`,
  `collector/tests/test_config.py`, `collector/tests/test_main.py`,
  `collector/tests/checks/test_net_http.py`,
  `collector/tests/checks/test_net_tcp.py`, and
  `collector/tests/checks/test_net_icmp.py`. No frozen S3/S4/S5 file,
  contract, dependency, workflow, or architecture document changed.
- **Corrections:** disabled families are no longer constructed; all five
  timeout fields require a positive finite value; HTTP results, errors, and
  logs use `target_id` and exception type without URL/credential/query
  material; ICMP/latency explicitly reject IPv6 while the IPv4 ICMP runtime
  resolves hostnames and verifies reply source; ICMP, TCP, and HTTP now join
  the existing DNS/latency external-cancellation matrix, including bounded
  ICMP worker recovery.
- **Windows/Python 3.14.5 scoped gates:** changed-file Ruff passed; mypy
  passed for all four changed production modules; Pylint rated the production
  modules 10.00/10; focused network/config/registration suite passed
  `221 passed, 1 skipped`.
- **Windows repository-wide evidence:** Ruff passed and Pylint rated
  `10.00/10`. Full mypy stops only at frozen S3 file
  `collector/checks/host_load.py:33` because Windows has no typed
  `os.getloadavg`; full pytest reports `431 passed, 1 skipped, 19 failed`,
  with all failures confined to frozen S3 Linux host-check modules/tests.
  These pre-existing cross-platform S3 corrections are outside this exact
  claim and remain for the independent S3 review.
- **Ubuntu 24.04/Python 3.12.3 exact-commit evidence on `.33`:** host
  `/home/adminuser/analyseLaptop` was clean, fast-forwarded to exact
  `0e254b0045a3da35adaa25e2f8286cddaa532d77`, then Ruff passed, mypy passed
  all 55 source files, Pylint rated `10.00/10`, and pytest passed
  `450 passed, 1 skipped`.
- **GitHub evidence at exact implementation SHA:** collector run
  `30384526449` passed its Ubuntu/Python 3.12 job (all four gates); its
  Windows job reproduced only the frozen S3 `host_load.py` mypy blocker.
  Pylint run `30384526404` and CodeQL run `30384526429` passed.
  Production-path phase-1 integration run `30384526391` passed real
  enrollment, mTLS collector export, VictoriaMetrics storage, and the
  authenticated site-scoped API assertion.
- **Review request:** independently inspect only the nine-file correction
  diff from `4e18ad8..0e254b0` against the five items in Codex review 1.
  Keep this REVIEW scope frozen. C2-03 may now start under its disjoint
  workflow-only claim; S2-02 must not be marked DONE by its implementer.

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
