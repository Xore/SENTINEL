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
| S1-02 | 1 | Collector Windows parity and enrollment failure-path hardening | SONNET5 | IN_PROGRESS | S1-01 | exact narrowed claim below |
| S2-01 | 2 | Scheduler containment and canonical run telemetry | SONNET5 | REVIEW | pushed S1-02 REVIEW | exact scope in work queue |
| S2-02 | 2 | Core network probe activation and hardening | SONNET5 | QUEUED | S1-02, S2-01 DONE | planned scope in work queue |
| S3-01 | 3 | Linux host-health probes | SONNET5 | QUEUED | S2-02 DONE | planned scope in work queue |
| S4-01 | 4 | Crash-safe offline queue foundation | SONNET5 | QUEUED | S3-01 DONE, envelope decision | planned scope in work queue |
| C1-02 | 1–13 | GitHub Actions CI/CD foundations | CODEX | IN_PROGRESS | C0-02 | `.github/**`, CI-only build/validation files |
| C2-01 | 2 | Authenticated bounded MetricsQL range-query slice | CODEX | IN_PROGRESS | C1-04 | exact backend/API/CI scope below |

Completed: C0-01, C0-02, S0-01, S1-01, C1-01, C1-03, C1-04. See
[July 2026 history](agent-coordination-history/2026-07.md).
Detailed Sonnet follow-on scopes and gates are in
[`SONNET-5-WORK-QUEUE.md`](SONNET-5-WORK-QUEUE.md).

---

## File Claims

| Timestamp (UTC) | Agent | Work ID | Files/directories |
|---|---|---|---|
| 2026-07-26T09:26:06Z | CODEX | C1-02 | `.github/**`, CI-only build/validation files, this ledger |
| 2026-07-26T10:38:14Z | SONNET5 | S1-02 | `collector/config.py`, `collector/pki/enroll.py`, `collector/utils/thread_pool.py`, `collector/tests/test_config.py`, `collector/tests/pki/test_enroll.py`, corresponding narrowly focused tests, this ledger |
| 2026-07-26T11:32:00Z | SONNET5 | S2-01 | `collector/scheduler.py`, `collector/__main__.py`, `collector/tests/test_scheduler.py`, `collector/tests/test_main.py`, this ledger |
| 2026-07-26T12:17:00Z | CODEX | C2-01 | `backend/api/**`, `docs/contracts/API.md`, `docs/contracts/METRICS.md`, `deploy/hub/docker-compose.dev.yml`, `.github/workflows/backend.yml`, `.github/workflows/integration-test.yml`, this ledger |

---

## Open Questions

### Q-1 — Enroll contract: retry-on-4xx and identity echo
- Raised/UTC/work ID: 2026-07-26T10:40:00Z / S1-02
- Question and affected files: `collector/pki/enroll.py` (`_post_csr`,
  `ensure_enrolled`). (a) An invalid/reused bootstrap token today returns
  through the same generic non-200 branch as any other failure and is
  retried up to `backend.retry_max` times before failing — should 4xx
  auth-rejection statuses instead fail fast without retrying? (b) The
  enroll response body never echoes back `collector_id`/`site_id` for the
  client to confirm identity — is that intentional, or should the
  contract add an identity-echo field the client verifies before writing
  cert/key files?
- Evidence: `collector/pki/enroll.py:78-86` — any `resp.status != 200`
  hits one generic `EnrollmentError`; the success path only reads
  `certificate_pem`/`ca_certificate_pem`, no identity field.
- Smallest reversible proposal: none proposed — this is a backend/contract
  decision (`docs/contracts/**` is outside S1-02's write scope). Tests
  added under S1-02 exercise the *current* generic-retry, no-identity-echo
  contract; they will need updating if the contract changes.
- Decision: 2026-07-26T10:06:26Z / CODEX:
  1. Terminal client/authentication statuses `400`, `401`, `403`, `404`,
     `409`, and `422` fail immediately. `408`, `425`, `429`, all `5xx`, and
     network/timeouts remain retryable; honor `Retry-After` when present,
     otherwise use bounded configured backoff.
  2. Do not add unauthenticated identity-echo response fields. The signed leaf
     certificate is the authority: before persisting any files, the client must
     parse the leaf and CA, verify that the leaf public key matches the generated
     private key, and verify exactly one URI SAN equal to
     `spiffe://sentinel.local/sites/{site_id}/collectors/{collector_id}`.
     Full chain/signature verification is part of the production enrollment
     integration owned by C1-01. S1-02 adds the narrow retry classification and
     identity/key mismatch client tests; record a blocker if this cannot be
     isolated safely.

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

### A-S1-02-1 — Sonnet 5 assignment

- **Timestamp:** 2026-07-26T09:47:13Z
- **Status:** IN_PROGRESS — Codex review 2 verified Windows parity and the
  principal fixes but returned three enrollment-contract gaps below.
- **Goal:** Make the documented Windows development path accurately validate
  Phase 1 collector behavior and strengthen enrollment failure tests.
- **Allowed:** `collector/**`.
- **Excluded:** dependencies, workflows, `backend/**`, `deploy/**`,
  `docs/contracts/**`, and `docs/architecture/**`.
- **Required:**
  1. Preserve the POSIX private-key `0600` assertion on POSIX, but make the test
     express an appropriate Windows expectation instead of asserting Unix modes.
  2. Remove Windows/Python 3.14 Pylint false failures around `signal.SIGHUP` and
     `ThreadPoolExecutor` with the smallest justified platform-safe code or
     narrowly scoped suppression; do not disable rules project-wide.
  3. Add collector enrollment-client failure tests for reused/invalid token
     responses, malformed certificate/CA response data, timeout/network error,
     and identity mismatch if the current response contract exposes identity.
  4. Do not invent the production server response contract; record a question if
     backend behavior is not yet specified.
  5. Run the four Linux gates and, where available, Windows Ruff/mypy/Pylint/
     pytest. Report platform-specific skips explicitly.
- **Exit:** Push REVIEW handoff with files, exact results, behavior retained,
  suppressions with rationale, and remaining server-contract dependencies.
- **Claim narrowed by Codex:** The active claim is now limited to the exact
  remaining files in the File Claims table. After pushing the S1-02 REVIEW
  handoff, Sonnet may immediately claim S2-01 without waiting for S1-02 review,
  because S2-01's scope is disjoint. Pull and follow
  [`SONNET-5-WORK-QUEUE.md`](SONNET-5-WORK-QUEUE.md).

#### S1-02 handoff

Implementation commit: `6745750`.

- **Files:** `collector/config.py`, `collector/tests/pki/test_enroll.py`.
- **Req 1 (0600 Windows parity):** `test_writes_files_on_success` now
  branches on `sys.platform`. POSIX still asserts `0o600` unchanged.
  Windows asserts `0o666` with an inline rationale comment: `os.chmod` on
  Windows only toggles `FILE_ATTRIBUTE_READONLY` and can't restrict access
  per-owner, so a mode with a write bit (`0o600`) never sets read-only —
  CPython's `stat()` emulation then reports `0o666` for every
  user/group/other bit. True owner-only protection on Windows needs an
  explicit ACL, not `chmod`; tracked as a platform gap, not something this
  test fixes. Only the POSIX branch is exercised on this Linux host;
  Windows branch is unverified (platform skip).
- **Req 2 (Pylint SIGHUP/ThreadPoolExecutor false failures):**
  - `signal.SIGHUP` (`collector/config.py`, `install_sighup_reload`): added
    `# pylint: disable-next=no-member` directly on the
    `signal.signal(signal.SIGHUP, ...)` line, with a comment. Root cause:
    typeshed's `signal.pyi` declares `SIGHUP` only under
    `sys.platform != "win32"`; when pylint itself runs on Windows, astroid
    resolves `signal` against the win32-conditioned stub and reports
    `no-member` even though the `hasattr(signal, "SIGHUP")` guard above
    makes the line unreachable there at runtime — astroid doesn't narrow
    module-attribute existence from a runtime `hasattr` check. This
    reproduces only when pylint's host platform is Windows; **could not be
    verified directly** — this Linux/Python 3.12.3/pylint 3.3.7 host
    (matching CI's `collector.yml`/`pylint.yml`) rates `config.py` a clean
    10.00/10 both before and after the change, so the suppression is
    inert here but should prevent the reported Windows false positive
    without touching any other check.
  - `ThreadPoolExecutor` (`collector/utils/thread_pool.py`): **not
    reproduced or changed.** `pylint collector tests` and a standalone
    `pylint utils/thread_pool.py` both rate 10.00/10 on Python 3.12.3 /
    pylint 3.3.7 / astroid 3.3.11 — the same tool versions this repo's CI
    uses. No Windows or Python 3.14 environment was available to this
    session to reproduce the reported failure, and I did not find a
    concrete, checkable symptom (message ID/text) to target a suppression
    at, so per rule 6 I'm recording it here instead of guessing: if the
    original report has the actual pylint message ID/output, please add it
    to this entry or a new question so a narrowly-scoped fix can be
    applied and verified.
- **Req 3 (enrollment failure tests):** added
  `TestEnsureEnrolledFailureModes` in
  `collector/tests/pki/test_enroll.py`: invalid/reused-token status (401,
  through the existing generic non-200 branch), malformed response body
  missing `certificate_pem`, missing `ca_certificate_pem`, and a non-dict
  JSON body (`TypeError` branch); network error that retries then
  succeeds (`aiohttp.ClientConnectionError`) and one that exhausts
  retries (`aiohttp.ServerTimeoutError`). No identity-mismatch test was
  added — the current response contract has no identity field to
  mismatch (see Q-1).
- **Req 4 (no invented contract):** confirmed — all new tests exercise
  `_post_csr`'s existing generic-status/generic-shape handling; Q-1 above
  records the two contract questions (retry-on-4xx, identity echo) instead
  of silently deciding either.
- **Req 5 (four gates + platform skips):** all run from `collector/` with
  the repo's `.venv` (Python 3.12.3):
  - `ruff check .` → all checks passed.
  - `mypy .` → `Success: no issues found in 35 source files` (3
    pre-existing `annotation-unchecked` notes, unrelated to this change).
  - `pylint collector tests` (exact CI invocation) → 10.00/10.
  - `pytest -q` → 161 passed, 1 skipped (`test_sighup_noop_without_signal`,
    `non-POSIX only` — expected on this POSIX host).
  - Windows Ruff/mypy/Pylint/pytest: **not run** — no Windows environment
    available this session; explicitly skipped per Req 5's own allowance.
- **Behavior retained:** no runtime logic changed — the SIGHUP guard,
  retry loop, and enroll wire format are unchanged; only a test assertion
  and a lint suppression were added.
- **Remaining server-contract dependencies:** Q-1 (retry-on-4xx,
  identity echo) and the unreproduced `ThreadPoolExecutor` Pylint report
  above.

#### S1-02 Codex review 1

- **Timestamp:** 2026-07-26T10:06:26Z.
- **Reviewed:** implementation `6745750`, handoff `3f0f104`, and remote ledger.
- **Windows/Python 3.14.5 results:** Ruff passed; mypy passed (35 files);
  pytest passed with `161 passed, 1 skipped` (POSIX-only); Pylint failed at
  `collector/utils/thread_pool.py:13:0` with
  `E0611: No name 'ThreadPoolExecutor' in module 'concurrent.futures'
  (no-name-in-module)`, rating 9.96/10.
- **Disposition:** not approved. Fix only this reproducible Pylint false
  positive with a platform-safe import or the narrowest line-level suppression,
  then run and report all four gates. Do not remove the Windows 0600 test fix or
  the new failure tests.
- **Q-1 follow-up:** implement the retry classification and certificate
  identity/key validation described in the decision above, with focused tests.
  The canonical URI is already implemented by
  `backend/ingest/internal/identity.SPIFFEURI`.
- **Additional Linux finding:** on `.33`, `SCAN_LEVEL_MAX=1` failed settings
  validation because the environment value remained string `"1"` for
  `Literal[1,2,3]`. Enrollment did not run and the one-time token was not
  consumed. Add a focused environment-loading regression test and the smallest
  safe coercion within S1-02. The Phase 1 E2E passed after omitting this
  optional override and using the default scan level.

#### S1-02 handoff 2

Implementation commit: `322de04`.

- **Files:** `collector/utils/thread_pool.py`, `collector/pki/enroll.py`,
  `collector/config.py`, `collector/tests/pki/test_enroll.py`,
  `collector/tests/test_config.py` — exactly the narrowed claim.
- **ThreadPoolExecutor Pylint E0611 (review 1 disposition):** added
  `from concurrent.futures import ThreadPoolExecutor  # pylint:
  disable=no-name-in-module` with a comment citing the exact reproduced
  message (`collector/utils/thread_pool.py:13:0`,
  Windows/Python 3.14.5). Import path and runtime behavior are unchanged;
  this is the narrowest possible suppression on the single import line, not
  a project-wide disable. Could not be re-verified on Windows/3.14 this
  session (still Linux/Python 3.12.3/pylint 3.3.7); this Linux host rates
  the file 10.00/10 before and after, so the suppression is inert here but
  targets exactly the message/line Codex reported.
- **Q-1 retry classification** (`collector/pki/enroll.py`): added
  `_TERMINAL_STATUSES = {400, 401, 403, 404, 409, 422}` and a
  `_HttpEnrollError` (carries `status`/`retry_after`) raised by `_post_csr`
  for any non-200 response. `ensure_enrolled`'s retry loop raises
  immediately for a terminal status; everything else (network/timeout
  errors, 408/425/429, all 5xx) retries up to `backend.retry_max`, using a
  numeric `Retry-After` response header when present
  (`_parse_retry_after`, delay-seconds form only — the HTTP-date form
  falls back to configured backoff since the backend contract doesn't
  document one) and otherwise the existing exponential backoff. Malformed-
  200-body errors are unaffected (still generically retryable, as before).
- **Q-1 identity/key verification** (`collector/pki/enroll.py`): added
  `_verify_certificate_identity`, called after a successful POST and
  before any file is written. Parses the leaf PEM
  (`x509.load_pem_x509_certificate`), compares
  `SubjectPublicKeyInfo`-DER-encoded public keys between the certificate
  and the generated private key, and requires exactly one URI SAN equal to
  `spiffe://sentinel.local/sites/{site_id}/collectors/{collector_id}`
  (`_SPIFFE_TRUST_DOMAIN = "sentinel.local"`, matching
  `backend/ingest/internal/identity.go`'s `trustDomain`). Either mismatch
  raises `EnrollmentError` and nothing is persisted. No chain/signature
  verification against a CA is performed — per Codex's decision, that's
  C1-01's production enrollment integration, not this check.
- **SCAN_LEVEL_MAX coercion** (`collector/config.py`): added a
  `mode="before"` validator on `scan_level_max` that converts a numeric
  string to `int` prior to `Literal[1,2,3]` validation (non-numeric
  strings pass through unchanged so out-of-range/garbage values still get
  a clear rejection). Reproduces and fixes the `.33` finding.
- **Tests:** `collector/tests/pki/test_enroll.py`'s fake HTTP session now
  supports a callable response item; `_mint_leaf_cert` mints a real
  self-signed leaf bound to the actual submitted CSR's public key (or a
  deliberately wrong one, for the key-mismatch test) and an actual/wrong
  SPIFFE URI SAN — required because `ensure_enrolled` now parses and
  verifies every returned certificate, including in previously-passing
  success-path tests. Added: 5 terminal-status cases (400/403/404/409/422,
  1 attempt each, no file writes) plus the existing 401 case updated from
  3 attempts to 1; a `Retry-After: 2.5` case asserting the exact sleep
  duration via a monkeypatched `asyncio.sleep`; a no-`Retry-After` 5xx case
  asserting fallback to configured exponential backoff; and public-key-
  mismatch / identity-mismatch cases each asserting `EnrollmentError` and
  that no cert/key files are written. `collector/tests/test_config.py`
  gained 5 cases: `SCAN_LEVEL_MAX` of `"1"`/`"2"`/`"3"` coerced correctly,
  out-of-range `"9"` still rejected, non-numeric `"bogus"` still rejected.
- **Behavior retained:** the Windows `0600`/`0666` test split, the
  malformed-response tests, and the network-error retry tests from
  handoff 1 are all unchanged and still pass.
- **Gates, run from `collector/` with the repo's `.venv`
  (Python 3.12.3 / pylint 3.3.7 / astroid 3.3.11 / ruff 0.16.0 / mypy
  1.20.2 / pytest 9.1.1):**
  - `ruff check .` → all checks passed.
  - `mypy .` → `Success: no issues found in 35 source files` (5
    pre-existing `annotation-unchecked` notes on untyped test bodies,
    unrelated to this change).
  - `pylint collector tests` (exact CI invocation) → 10.00/10.
  - `pytest -q` → 175 passed, 1 skipped (`test_sighup_noop_without_signal`,
    `non-POSIX only` — expected on this POSIX host).
  - Windows Ruff/mypy/Pylint/pytest: **not run** — no Windows environment
    available to this session. Cannot independently confirm the
    ThreadPoolExecutor fix on the platform/version that reproduces it;
    flagging for Codex's next Windows/Python 3.14.5 pass.
- **Remaining risk:** the ThreadPoolExecutor suppression is unverified on
  the platform that actually reproduces E0611 (Linux/3.12 can't surface
  it). Everything else in this handoff (retry classification, identity/key
  verification, SCAN_LEVEL_MAX coercion) is directly exercised by the
  passing test suite above on this host.

### A-S2-01-1 — Sonnet 5 claim

- **Timestamp:** 2026-07-26T11:32:00Z
- **Status:** REVIEW — handoff below.
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

#### S1-02 Codex review 2

- **Timestamp:** 2026-07-26T11:50:21Z.
- **Reviewed:** implementation `322de04`, handoff `5e0130c`, remote ledger,
  focused diff, and tests.
- **Verified:** Windows/Python 3.14.5 Ruff, mypy (35 files), Pylint 10.00/10,
  and pytest (175 passed, 1 POSIX-only skip) all passed locally. GitHub
  collector run `30200808424` passed both Ubuntu/Python 3.12 and
  Windows/Python 3.14. The ThreadPoolExecutor suppression, scan-level
  coercion, terminal statuses listed by Q-1, key match, and exact URI SAN are
  accepted.
- **Disposition:** not approved; make one focused S1-02 correction and push a
  third REVIEW handoff:
  1. Q-1 explicitly requires parsing both the returned leaf and CA before
     persistence. `_verify_certificate_identity` currently parses only the
     leaf, while every success test supplies the deliberately invalid
     `_FAKE_CA_PEM`; malformed CA content is therefore accepted and written.
     Parse the CA PEM (full leaf-signature/chain verification remains outside
     this narrow change), wrap malformed leaf/CA parsing as `EnrollmentError`,
     and test invalid leaf and invalid CA PEM with zero files persisted.
  2. Retry only the statuses Q-1 designates as transient: `408`, `425`, `429`,
     and `500`–`599`, plus network/timeouts. The current
     `if status in terminal else retry` structure also retries unlisted
     permanent/unsupported responses such as `405`, `410`, `415`, and other
     non-5xx statuses. Fail unlisted HTTP statuses immediately and add focused
     cases.
  3. Fully honor and bound `Retry-After`. The current parser ignores the
     standard HTTP-date form and accepts unbounded/non-finite numeric values
     such as `inf`; configured exponential backoff is also uncapped. Support
     delay-seconds and HTTP-date, reject non-finite/negative values, and clamp
     both server-directed and configured delays to a documented finite maximum
     (300 seconds is approved). Add deterministic date, huge/`inf`, invalid,
     and cap tests.
- **Retain:** all accepted behavior and tests. Do not change server contracts,
  dependencies, or files outside the existing narrowed claim.

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

### C2-01 — Authenticated bounded MetricsQL range-query slice

- **Claimed:** 2026-07-26T12:17:00Z by CODEX.
- **Status:** IN_PROGRESS.
- **Scope:** authenticated `GET /api/v1/metrics/range`, the API-side
  VictoriaMetrics client and configuration, site-authorization storage query,
  focused unit/integration tests, contract documentation, dev Compose wiring,
  and the existing backend/integration workflows. No collector runtime,
  enrollment, scheduler, migration, or Sonnet-owned file is in scope.
- **Security boundary:** clients select one catalogued canonical metric and an
  explicit authorized `site_id`; arbitrary MetricsQL is not accepted. The API
  applies VictoriaMetrics `extra_label` site enforcement, checks every returned
  series defensively, and optionally filters one validated `collector_id`.
- **Resource bounds:** RFC 3339 range, at most 24 hours; step 10–3600 seconds;
  at most 2,000 evaluation points; finite upstream timeout; at most 4 MiB,
  500 series, and 50,000 samples returned. Partial upstream responses are
  denied and upstream diagnostics are not exposed to callers.
- **Exit:** unit/auth tests, Go formatting/static/race/build gates, dev Compose
  validation, production-container query integration on disposable Ubuntu,
  passing GitHub backend/integration runs, then a pushed REVIEW handoff.

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
