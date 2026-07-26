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
| S2-01 | 2 | Scheduler containment and canonical run telemetry | SONNET5 | READY after S1-02 REVIEW | pushed S1-02 REVIEW | exact scope in work queue |
| S2-02 | 2 | Core network probe activation and hardening | SONNET5 | QUEUED | S1-02, S2-01 DONE | planned scope in work queue |
| S3-01 | 3 | Linux host-health probes | SONNET5 | QUEUED | S2-02 DONE | planned scope in work queue |
| S4-01 | 4 | Crash-safe offline queue foundation | SONNET5 | QUEUED | S3-01 DONE, envelope decision | planned scope in work queue |
| C1-02 | 1–13 | GitHub Actions CI/CD foundations | CODEX | IN_PROGRESS | C0-02 | `.github/**`, CI-only build/validation files |

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
- **Status:** IN_PROGRESS — Codex review returned one Windows failure and
  resolved Q-1; Sonnet must push a new REVIEW handoff.
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
