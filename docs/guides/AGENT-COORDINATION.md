# Codex ↔ Sonnet 5 Coordination Ledger

> **Purpose:** Durable communication and file ownership for implementation of
> SENTINEL v2.
> **Required reading:** Both agents must read this file before planning, editing,
> reviewing, or starting a dependent phase.
> **Architecture guide:** `docs/guides/SONNET-5-IMPLEMENTATION-GUIDE.md`

---

## Protocol

Allowed owners:

- `CODEX`
- `SONNET5`
- `UNASSIGNED`

Allowed statuses:

- `READY` — owner may begin
- `IN_PROGRESS` — owner is editing the declared files
- `BLOCKED` — owner needs a recorded answer or dependency
- `REVIEW` — implementation is complete and awaits Codex review
- `DONE` — Codex verified the exit criteria

Rules:

1. Start every session with `git status`, `git fetch origin`, and a comparison of
   local `HEAD` to `origin/main`.
2. If the working tree is clean, run `git pull --ff-only origin main` before
   reading this ledger. If it is not clean, do not pull over local work: finish
   and push the owned change, or record/report the overlap.
3. Read the whole ledger from the newly pulled commit before touching code.
4. Claim exact files or narrow directories before editing.
5. A claim is not active until the ledger change is committed and pushed to
   `origin/main`. Re-read the pushed file from `origin/main` to confirm it.
6. Never edit a file currently claimed by the other agent.
7. Add architectural questions to the Questions section; do not make silent,
   system-wide decisions.
8. Sonnet 5 moves completed work to `REVIEW`. Only Codex moves it to `DONE`.
9. A dependent item cannot start until its prerequisite is `DONE`.
10. Record test commands and actual outcomes, not “tests should pass.”
11. Use UTC timestamps in ISO 8601 form.
12. Preserve unrelated user changes and report dirty-worktree overlap.
13. Every information exchange is a Git transaction. Claims, questions,
    decisions, handoffs, review results, and status changes must each be committed
    and pushed promptly; do not leave coordination state only in a local tree.
14. Before acting on information from the other agent, fetch/pull, read the
    committed ledger entry, and inspect the referenced commit/diff.
15. After pushing, run `git fetch origin` and verify local `HEAD` equals
    `origin/main`. If a push is rejected, pull with `--ff-only` when possible,
    resolve only owned-file conflicts, re-read the ledger, then retry.

### Required synchronization sequence

Use this sequence for a clean working tree:

```bash
git fetch origin
git pull --ff-only origin main
# read this ledger and the referenced commits
# update claim/question/handoff/status
git add <only-owned-files>
git commit -m "<scoped message>"
git push origin main
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
git show origin/main:docs/guides/AGENT-COORDINATION.md
```

The two revisions must match. The final `git show` is the required read-back of
the shared information as stored on the remote branch.

---

## Current Work Board

| ID | Phase | Work item | Owner | Status | Prerequisites | Write scope |
|---|---:|---|---|---|---|---|
| C0-01 | 0 | Repository audit and requirements traceability matrix | CODEX | DONE | None | `docs/architecture/`, traceability document |
| C0-02 | 0 | ADRs and canonical cross-service contracts | CODEX | IN_PROGRESS | C0-01 | `docs/architecture/decisions/`, contract specs |
| S0-01 | 0 | Run current collector quality suite and report implementation inventory | SONNET5 | IN_PROGRESS | None | No source edits; append results here |
| S1-01 | 1 | Collector heartbeat vertical slice | SONNET5 | BLOCKED | C0-02 | To be assigned after contracts |
| C1-01 | 1 | Hub skeleton, migrations, PKI and ingest contract foundation | CODEX | BLOCKED | C0-02 | To be assigned after audit |

The board is intentionally initialized only through Phase 1. Codex adds later
assignments after each phase gate so stale plans do not cause overlapping work.

---

## File Claims

Add a row before editing and remove the active claim only after handoff. Historical
claims may remain with status `RELEASED`.

| Timestamp (UTC) | Agent | Work ID | Files/directories | Claim status |
|---|---|---|---|---|
| 2026-07-26T09:11:04Z | CODEX | C0-01 | `docs/architecture/REQUIREMENTS-TRACEABILITY.md`, `docs/guides/AGENT-COORDINATION.md` | RELEASED |
| 2026-07-26T09:14:13Z | CODEX | C0-02 | `docs/architecture/decisions/`, `docs/contracts/`, `docs/guides/AGENT-COORDINATION.md` | ACTIVE |
| 2026-07-26T09:16:11Z | SONNET5 | S0-01 | `docs/guides/AGENT-COORDINATION.md` only — no source edits | ACTIVE |

---

## Questions and Decisions

Use one entry per issue.

### Q-000 — Example format

- **Status:** EXAMPLE
- **Raised by:** —
- **Work ID:** —
- **Question:** State the concrete ambiguity and affected files.
- **Evidence:** Cite exact document sections or code locations.
- **Proposed smallest reversible choice:** State a recommendation.
- **Answer/decision:** Codex records the accepted decision and ADR, if needed.

---

## Handoffs and Review Results

Use this template:

### H-<work-id>-<number>

- **Timestamp (UTC):**
- **From:**
- **To:**
- **Status requested:** REVIEW / READY / BLOCKED
- **Changed files:**
- **Behavior implemented:**
- **Commands run and results:**
- **Known limitations:**
- **Assumptions:**
- **Commit SHA:** none, or SHA
- **Reviewer result:** pending / accepted / changes requested
- **Reviewer notes:**

### H-C0-01-1

- **Timestamp (UTC):** 2026-07-26T09:14:13Z
- **From:** CODEX
- **To:** CODEX / SONNET5
- **Status requested:** READY
- **Changed files:** `docs/architecture/REQUIREMENTS-TRACEABILITY.md`,
  coordination and implementation guides
- **Behavior implemented:** Audited every extended-architecture feature against
  the current repository and established the implementation critical path.
- **Commands run and results:** Repository file/symbol inventory, clean diff
  check, remote synchronization and remote ledger read-back passed.
- **Known limitations:** Sonnet's independent quality-suite results are still
  pending under S0-01 and will be merged into the audit if they change evidence.
- **Assumptions:** Documentation/examples do not count as implementation.
- **Commit SHA:** `be6c04bb3f07c83a06b0b93e6ec7916dbc067fde`
- **Reviewer result:** accepted
- **Reviewer notes:** C0-02 may start; S1-01 remains blocked pending contracts.

---

## Initial Message to Sonnet 5

> Before doing anything else, read
> `docs/guides/SONNET-5-IMPLEMENTATION-GUIDE.md` and
> `docs/guides/AGENT-COORDINATION.md` completely. Your first assignment is
> `S0-01`: inspect the repository and run the current collector quality suite.
> Start by fetching and fast-forward pulling `origin/main`. Do not edit source
> files. Add a file claim indicating “no source edits,” set `S0-01` to
> `IN_PROGRESS`, commit and push that claim, then fetch and read the ledger back
> from `origin/main` before running the audit. Append a handoff with the exact
> inventory and command results, set `S0-01` to `REVIEW`, commit and push the
> handoff, and verify `HEAD == origin/main`. Do not start `S1-01`; Codex owns the
> architecture/contracts prerequisite and will assign its file scope after
> reviewing the pushed handoff.
