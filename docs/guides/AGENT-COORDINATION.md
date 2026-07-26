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

1. Read the whole ledger before touching code.
2. Claim exact files or narrow directories before editing.
3. Never edit a file currently claimed by the other agent.
4. Add architectural questions to the Questions section; do not make silent,
   system-wide decisions.
5. Sonnet 5 moves completed work to `REVIEW`. Only Codex moves it to `DONE`.
6. A dependent item cannot start until its prerequisite is `DONE`.
7. Record test commands and actual outcomes, not “tests should pass.”
8. Use UTC timestamps in ISO 8601 form.
9. Preserve unrelated user changes and report dirty-worktree overlap.

---

## Current Work Board

| ID | Phase | Work item | Owner | Status | Prerequisites | Write scope |
|---|---:|---|---|---|---|---|
| C0-01 | 0 | Repository audit and requirements traceability matrix | CODEX | READY | None | `docs/architecture/`, traceability document |
| C0-02 | 0 | ADRs and canonical cross-service contracts | CODEX | READY | C0-01 | `docs/architecture/decisions/`, contract specs |
| S0-01 | 0 | Run current collector quality suite and report implementation inventory | SONNET5 | READY | None | No source edits; append results here |
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
| — | — | — | — | — |

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

---

## Initial Message to Sonnet 5

> Before doing anything else, read
> `docs/guides/SONNET-5-IMPLEMENTATION-GUIDE.md` and
> `docs/guides/AGENT-COORDINATION.md` completely. Your first assignment is
> `S0-01`: inspect the repository and run the current collector quality suite.
> Do not edit source files. Add a file claim indicating “no source edits,” set
> `S0-01` to `IN_PROGRESS`, then append a handoff with the exact inventory and
> command results. Set `S0-01` to `REVIEW` when finished. Do not start `S1-01`;
> Codex owns the architecture/contracts prerequisite and will assign its file
> scope after review.
