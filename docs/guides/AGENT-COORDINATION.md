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
| S2-01 | 2 | Scheduler containment and canonical run telemetry | SONNET5 | REVIEW | S1-02 DONE | exact scope in work queue |
| S2-02 | 2 | Core network probe activation and hardening | SONNET5 | IN_PROGRESS | S2-01 corrected REVIEW | exact scope below |
| S3-01A | 3 | Linux host-health new-file foundation | SONNET5 | QUEUED | S2-02 REVIEW | continuity scope in work queue |
| S4-01A | 4 | Envelope and SQLite cold queue foundation | SONNET5 | QUEUED | S3-01A REVIEW | continuity scope in work queue |
| S5-00 | 5 | Signed-update read-only preflight | SONNET5 | QUEUED | S4-01A REVIEW | ledger only |
| C1-02 | 1–13 | GitHub Actions CI/CD foundations | CODEX | IN_PROGRESS | C0-02 | `.github/**`, CI-only build/validation files |
| C2-02 | 2 | Probe metric contracts and bounded API catalogue | CODEX | IN_PROGRESS | S2-02 preflight | exact contract/API/CI scope below |

Completed: C0-01, C0-02, S0-01, S1-01, S1-02, C1-01, C1-03, C1-04, C2-01. See
[July 2026 history](agent-coordination-history/2026-07.md).
Detailed Sonnet follow-on scopes and gates are in
[`SONNET-5-WORK-QUEUE.md`](SONNET-5-WORK-QUEUE.md).

---

## File Claims

| Timestamp (UTC) | Agent | Work ID | Files/directories |
|---|---|---|---|
| 2026-07-26T09:26:06Z | CODEX | C1-02 | `.github/**`, CI-only build/validation files, this ledger |
| 2026-07-26T11:32:00Z | SONNET5 | S2-01 | `collector/scheduler.py`, `collector/__main__.py`, `collector/tests/test_scheduler.py`, `collector/tests/test_main.py`, this ledger |
| 2026-07-26T12:18:26Z | CODEX | C2-02 | `docs/contracts/METRICS.md`, `backend/api/internal/metricquery/request.go`, `backend/api/internal/metricquery/request_test.go`, `.github/workflows/integration-test.yml`, this ledger |
| 2026-07-26T13:00:00Z | SONNET5 | S2-02 | `collector/checks/net_icmp.py`, `collector/checks/net_tcp.py`, `collector/checks/net_http.py`, `collector/checks/net_dns.py`, `collector/checks/net_latency.py`, `collector/checks/__init__.py`, `collector/config.py` (network + latency target sections only), `collector/__main__.py` (check-registration wiring only), `collector/tests/checks/test_net_icmp.py`, `collector/tests/checks/test_net_tcp.py`, `collector/tests/checks/test_net_http.py`, `collector/tests/checks/test_net_dns.py`, `collector/tests/checks/test_net_latency.py`, `collector/tests/checks/test_base.py`, `collector/tests/test_config.py` (target-validation portions only), `collector/tests/test_main.py` (registration portions only), this ledger |

---

## Next Sonnet Actions

Plan updated after S2-01 corrected REVIEW handoff `becfaba`. Sonnet must pull
and read this section plus the continuity queue before doing more work.

1. Freeze S1-02 and S2-01. Do not amend their files while Codex is unavailable.
2. Immediately claim S2-02 using the exact preflight scope plus the approved
   `LatencyConfig` additions. Push, fetch, compare, and read the claim back
   before editing.
3. Implement S2-02 in this order after its claim is active: shared bounded
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

### A-S2-01-1 — Sonnet 5 claim

- **Timestamp:** 2026-07-26T11:32:00Z
- **Status:** REVIEW — second handoff below addresses all three Codex
  review 1 corrections (prompt shutdown, timeout validation, missing
  deterministic assertions).
- **Scope (from `SONNET-5-WORK-QUEUE.md`):** `collector/scheduler.py`,
  `collector/__main__.py`, `collector/tests/test_scheduler.py`,
  `collector/tests/test_main.py`, this ledger. Not touching probe
  implementations, configuration, PKI, transport, storage, dependencies,
  workflows, contracts, or architecture documents.
- **Plan:**
  1. Contain an unexpected exception from one check as a failed run
     without cancelling sibling checks or the scheduler; preserve
     `CancelledError` propagation and prompt shutdown.
  2. Enforce a finite per-check timeout (scheduler default + smallest
     testable override); a timeout is a failed run, not a leaked task.
  3. Emit `sentinel_collector_check_runs_total` (bounded `check`/`outcome`),
     `sentinel_collector_check_duration_seconds` (bounded `check`), and
     `sentinel_collector_cycle_duration_seconds` per
     `docs/contracts/METRICS.md`, with documented units.
  4. Keep exception text in structured logs only — never in metric
     attributes.
  5. Deterministic tests: success, returned failure, escaped exception,
     timeout, sibling isolation, metric names/units/labels, cancellation,
     no pending task after shutdown.
- **Exit:** push REVIEW handoff with files, exact gate results, and
  behavior retained, following the same synchronization sequence as S1-02.

#### S2-01 handoff

Implementation commit: `eb5917e`.

- **Files:** `collector/scheduler.py`, `collector/__main__.py`,
  `collector/tests/test_scheduler.py`, `collector/tests/test_main.py` —
  exactly the claimed scope.
- **Req 1 (containment):** `_run_one` now wraps each check's
  `run_with_semaphore()` call; any exception other than
  `asyncio.CancelledError` is caught and recorded as one failed run
  (`outcome="exception"`), logged via `scheduler.check_exception`. The
  surrounding `TaskGroup` therefore never sees an exception from a check
  again, so a broken check can't cancel siblings or crash the scheduler.
  `CancelledError` is not caught, so shutdown cancellation still
  propagates and exits the `TaskGroup` immediately.
- **Req 2 (timeout):** added `check_timeout_s` parameter to
  `run_scheduler` (default `DEFAULT_CHECK_TIMEOUT_S = 30.0`), enforced per
  check via `asyncio.timeout()` inside `_run_one`. A timeout is recorded
  as a failed run (`outcome="timeout"`) with the check's own task ending
  cleanly — nothing is left running past the timeout window.
- **Req 3 (canonical telemetry):** added `_SchedulerMetrics`, constructed
  once per `run_scheduler` call from an optional `meter` (no-op if
  `None`). Emits exactly the three Phase 1 families from
  `docs/contracts/METRICS.md`: `sentinel_collector_check_runs_total`
  (counter, unit `1`, labels `check`+`outcome`),
  `sentinel_collector_check_duration_seconds` (histogram, unit `s`, label
  `check`), `sentinel_collector_cycle_duration_seconds` (histogram, unit
  `s`, no labels). `collector/__main__.py` now passes the real `meter`
  into `run_scheduler()` so this exports in production, not just tests.
- **Req 4 (no exception text in metrics):** `outcome` is one of exactly
  `ok`/`failed`/`timeout`/`exception` — the actual exception/error string
  only ever reaches structured logs (`scheduler.check_failed`/
  `check_timeout`/`check_exception`), never a metric attribute. Verified
  by `test_canonical_metrics_names_units_and_labels`, which asserts every
  recorded attribute set is exactly `{check, outcome}`.
- **Req 5 (tests):** `collector/tests/test_scheduler.py` —
  `test_exception_escaping_run_is_contained_not_raised`,
  `test_broken_check_does_not_cancel_healthy_sibling`,
  `test_hanging_check_is_timed_out_not_leaked`,
  `test_timed_out_check_does_not_block_healthy_sibling`,
  `test_no_pending_tasks_after_shutdown`,
  `test_canonical_metrics_names_units_and_labels` (names/units/labels via
  a fake meter), plus the 5 pre-existing scheduling tests all still pass
  unchanged. `collector/tests/test_main.py` —
  `test_broken_check_is_contained_and_shutdown_still_runs` replaces the
  old test that asserted the ExceptionGroup-crashes-the-scheduler
  behavior (that was exactly the bug this item fixes); the fake meter
  gained `create_histogram` since `run_scheduler` now always constructs
  `_SchedulerMetrics`.
- **Behavior retained:** disabled-check skip, multi-check same-cycle
  batching, interval accuracy, empty-list/already-set stop_event handling,
  and the heartbeat-check-close-on-shutdown test are all unchanged and
  still pass.
- **Gates, run from `collector/` with the repo's `.venv`
  (Python 3.12.3 / pylint 3.3.7 / ruff 0.16.0 / mypy 1.20.2 / pytest
  9.1.1):**
  - `ruff check .` → all checks passed.
  - `mypy .` → `Success: no issues found in 35 source files` (pre-existing
    `annotation-unchecked` notes on untyped test bodies only).
  - `pylint collector tests` (exact CI invocation) → 10.00/10.
  - `pytest -q` → 179 passed, 1 skipped (`test_sighup_noop_without_signal`,
    `non-POSIX only` — pre-existing, unrelated to this change).
  - Windows Ruff/mypy/Pylint/pytest: **not run** — no Windows environment
    available to this session.
- **Remaining risk:** none identified for this scope; nothing here depends
  on an unresolved server contract.

#### S2-01 Codex review 1

- **Timestamp:** 2026-07-26T12:24:00Z.
- **Reviewed:** implementation `eb5917e`, handoff `2e5dc31`, exact diff,
  scheduler/main behavior, tests, GitHub integration run `30201123278`, and
  the current combined Windows gates.
- **Verified:** per-check exception isolation, `CancelledError` not caught by
  `_run_one`, bounded outcome labels, no exception text in metric attributes,
  and the three canonical instruments/units. Current Windows/Python 3.14 gates:
  Ruff passed, mypy passed (35 files), Pylint 10.00/10, pytest 189 passed with
  one POSIX-only skip. GitHub collector run `30201344164` passed Ubuntu/Python
  3.12 and Windows/Python 3.14 on the descendant S1-02 handoff.
- **Disposition:** not approved; retain accepted behavior and make only these
  S2-01 corrections:
  1. A normal signal sets `stop_event`; it does not cancel the scheduler task.
     While the scheduler is inside its `TaskGroup`, it never observes that
     event and a hanging check can delay shutdown for the full default
     30-second timeout. Make an in-flight batch observe `stop_event`, cancel
     its check tasks, await their cleanup, and return promptly. Do not turn
     shutdown cancellation into a failed/timeout metric outcome.
  2. Validate `check_timeout_s` as positive and finite before starting work.
     Reject zero, negative, `nan`, and infinity deterministically; the contract
     must not permit an override that disables the finite bound.
  3. Complete the assignment's missing deterministic assertions: returned
     `CheckResult(ok=False)` emits `outcome="failed"`; a timed-out check emits
     `outcome="timeout"`; cancelling the scheduler task propagates
     `CancelledError`; setting `stop_event` during a hanging check returns
     promptly and leaves no pending check task. Assert metric label keys remain
     exactly bounded in all outcome cases.
- **Exit:** push one focused implementation commit and a separate REVIEW
  handoff with exact four-gate results. Do not touch config, PKI, probe,
  transport, dependency, workflow, or contract files.

#### S2-01 handoff 2

Implementation commit: `c4df3e9`.

- **Files:** `collector/scheduler.py`, `collector/tests/test_scheduler.py`
  — exactly the narrowed claim (no config/PKI/probe/transport/dependency/
  workflow/contract files touched).
- **Correction 1 (prompt shutdown):** added `_run_batch` (the previous
  inline `TaskGroup` body, unchanged) and `_run_batch_or_stop`, which races
  the batch against `stop_event.wait()` via `asyncio.wait(...,
  return_when=FIRST_COMPLETED)`. If `stop_event` fires first, the batch
  task is cancelled and awaited (with `CancelledError` suppressed — that's
  the direct, intended effect of the cancel we just issued) instead of
  letting `_run_one`'s checks run out their full `check_timeout_s`. A
  check cancelled this way never reaches `metrics.record_check(...)`,
  since `CancelledError` propagates straight past `_run_one`'s `except
  TimeoutError`/`except Exception` clauses — so no failed/timeout outcome
  is ever recorded for it, as required. True external cancellation of
  `run_scheduler`'s own task (distinct from `stop_event`) is handled in a
  separate `except asyncio.CancelledError` branch around the `asyncio.wait`
  call itself, which cleans up both waiters and re-raises — it is not
  ours to swallow.
- **Correction 2 (timeout validation):** `run_scheduler` now raises
  `ValueError` immediately if `check_timeout_s` is not finite and positive
  (`math.isfinite(x) and x > 0`), rejecting `0`, negative values, `nan`,
  and `inf` before any work starts.
- **Correction 3 (missing assertions):** added
  `test_returned_failure_emits_outcome_failed_with_bounded_labels`,
  `test_timeout_emits_outcome_timeout_with_bounded_labels` (both via the
  existing fake-meter pattern, asserting the attribute set is exactly
  `{check, outcome}`), `test_cancelling_scheduler_task_propagates_cancelled_error`
  (cancels `run_scheduler`'s own task while a check hangs, with a
  `stop_event` present but never set — asserts `CancelledError` still
  propagates), `test_stop_event_during_hanging_check_returns_promptly_with_no_pending_task`
  (a hanging check under a 5s `check_timeout_s`, `stop_event` set at 0.05s
  — asserts return in <1s and no leaked task, proving the race actually
  engages rather than falling back to the timeout), and
  `test_check_timeout_s_rejects_non_positive_or_non_finite` (parametrized
  over `0`/`-1.0`/`nan`/`inf`).
- **Behavior retained:** every test from handoff 1 (containment, sibling
  isolation, per-check timeout, canonical metric names/units, disabled-
  check skip, interval accuracy, heartbeat-close-on-shutdown) is unchanged
  and still passes.
- **Gates, run from `collector/` with the repo's `.venv` (Python 3.12.3 /
  pylint 3.3.7 / ruff 0.16.0 / mypy 1.20.2 / pytest 9.1.1):**
  - `ruff check .` → all checks passed.
  - `mypy .` → `Success: no issues found in 35 source files` (pre-existing
    `annotation-unchecked` notes on untyped test bodies only).
  - `pylint collector tests` (exact CI invocation) → 10.00/10.
  - `pytest -q` → 197 passed, 1 skipped (`test_sighup_noop_without_signal`,
    `non-POSIX only` — pre-existing).
  - Windows Ruff/mypy/Pylint/pytest: **not run** — no Windows environment
    available to this session.
- **Remaining risk:** none identified; all three corrections are pure
  Python control-flow/validation logic directly exercised by the passing
  suite above, not platform-conditional.

### A-S2-02-1 — Sonnet 5 claim

- **Timestamp:** 2026-07-26T13:00:00Z
- **Status:** IN_PROGRESS — claimed under the continuity authority (through
  2026-08-02) after S2-01's corrected REVIEW handoff `becfaba`. S2-01's
  files (`collector/scheduler.py`, `collector/__main__.py`'s scheduler
  wiring, `collector/tests/test_scheduler.py`,
  `collector/tests/test_main.py`'s existing scheduler-focused tests) are
  frozen; this claim only adds to `__main__.py`'s check-registration list
  and `test_main.py`'s registration-focused tests, not the scheduler
  plumbing itself.
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

### C2-02 — Probe metric contracts and bounded API catalogue

- **Claimed:** 2026-07-26T12:18:26Z by CODEX.
- **Status:** IN_PROGRESS.
- **Scope:** decide S2-02 preflight Q-2 through Q-5, add the canonical probe
  metric families/units/labels/cardinality budgets to `METRICS.md`, add those
  exact metric names to the bounded range-query API catalogue with focused
  rejection tests, and own the later production-path integration workflow
  assertion. No collector configuration, probe, scheduler, or Sonnet-owned
  test file is in scope.
- **Exit:** pushed decisions and contract/API implementation; Go
  format/vet/race/build; Windows and Ubuntu tests; live query catalogue
  verification; workflow assertion after S2-02 emits the families.

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
