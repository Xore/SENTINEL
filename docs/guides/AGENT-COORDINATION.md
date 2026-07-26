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

- `READY` — owner may claim the item.
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
| S1-02 | 1 | Collector Windows parity and enrollment failure-path hardening | SONNET5 | READY | S1-01 | `collector/**`; exclusions below |
| C1-01 | 1 | Hub skeleton, migrations, PKI and ingest contract foundation | CODEX | IN_PROGRESS | C0-02 | `backend/`, `contracts/`, `deploy/hub/`, migration tests |
| C1-02 | 1–13 | GitHub Actions CI/CD foundations | CODEX | IN_PROGRESS | C0-02 | `.github/**`, CI-only build/validation files |

Completed: C0-01, C0-02, S0-01, S1-01. See
[July 2026 history](agent-coordination-history/2026-07.md).

---

## File Claims

| Timestamp (UTC) | Agent | Work ID | Files/directories |
|---|---|---|---|
| 2026-07-26T09:18:30Z | CODEX | C1-01 | `backend/`, `contracts/`, `deploy/hub/`, migration tests, this ledger |
| 2026-07-26T09:26:06Z | CODEX | C1-02 | `.github/**`, CI-only build/validation files, this ledger |

Sonnet must add and push its S1-02 claim before editing.

---

## Open Questions

No open questions.

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
- **Status:** READY; claim and push before editing.
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

### Pending C1-01 handoff

Latest implementation commit: `96a21b6`.

- TLS 1.3 mTLS, certificate-bound OTLP identity, resource validation, bounded
  VictoriaMetrics OTLP/HTTP forwarding, health/readiness, graceful shutdown.
- Local Windows full race suite now passes with MSYS2 UCRT64 GCC 16.1.0.
- GitHub backend run `30196833991` passed Linux race tests and PostgreSQL
  migration validation.
- Next: PostgreSQL `last_seen`, migration runner, production enrollment.

### C1-02 — CI/CD checkpoint

- Commits `8417066` and `4a7cf25`: backend gofmt/vet/race/build,
  empty-PostgreSQL migration validation, corrected action versions, Go CodeQL.
- Passing runs: backend `30196549053`; CodeQL `30196596608`; collector/Pylint at
  `8417066`.
- Still gated: multi-arch build, SBOM/scanning/signing, protected delivery,
  canary rollout, rollback.

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
