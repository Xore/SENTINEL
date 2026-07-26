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
3. Read the newly pulled active ledger, then any referenced history or commits.
4. Claim exact files before editing. A claim is active only after commit, push,
   fetch, revision comparison, and remote read-back.
5. Never edit a file claimed by the other agent.
6. Record architecture questions instead of making silent system-wide decisions.
7. Sonnet moves finished work to `REVIEW`; only Codex moves it to `DONE`.
8. Every claim, question, decision, handoff, review, or status transition is a
   prompt Git transaction. Do not leave coordination information only locally.
9. Before acting on the other agent’s information, pull, read the remote entry,
   and inspect its referenced commit/diff.
10. Preserve unrelated user changes. If a push is rejected, fetch, inspect the
    remote change, rebase non-overlapping owned work, and re-read the ledger.
11. Use UTC ISO 8601 timestamps and actual command results.
12. Keep this file small:
    - active/blocked/review work only in the main board;
    - active claims only in File Claims;
    - open questions only in Questions;
    - current assignments and pending handoffs only in Active Exchanges;
    - archive completed work after review.

Required clean-tree synchronization:

```bash
git fetch origin
git pull --ff-only origin main
# read active ledger and referenced history/commits
# update one scoped coordination item
git add <only-owned-files>
git commit -m "<scoped message>"
git push origin main
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
git show origin/main:docs/guides/AGENT-COORDINATION.md
```

The revisions must match. The final command is the required remote read-back.

---

## Active Work Board

| ID | Phase | Work item | Owner | Status | Prerequisites | Write scope |
|---|---:|---|---|---|---|---|
| S1-01 | 1 | Collector contract and lifecycle hardening | SONNET5 | READY | C0-02, S0-01 | `collector/**`; exclusions in assignment |
| C1-01 | 1 | Hub skeleton, migrations, PKI and ingest contract foundation | CODEX | IN_PROGRESS | C0-02 | `backend/`, `contracts/`, `deploy/hub/`, migration tests |
| C1-02 | 1–13 | GitHub Actions CI/CD foundations | CODEX | IN_PROGRESS | C0-02 | `.github/**`, CI-only build/validation files |

Completed Phase 0: C0-01, C0-02, and S0-01. See
[July 2026 history](agent-coordination-history/2026-07.md).

---

## File Claims

| Timestamp (UTC) | Agent | Work ID | Files/directories |
|---|---|---|---|
| 2026-07-26T09:18:30Z | CODEX | C1-01 | `backend/`, `contracts/`, `deploy/hub/`, migration tests, this ledger |
| 2026-07-26T09:26:06Z | CODEX | C1-02 | `.github/**`, CI-only build/validation files, this ledger |

Sonnet must add and push its S1-01 claim before editing.

---

## Open Questions

No open questions.

Use this compact format:

```text
### Q-<number> — Title
- Raised/UTC/work ID:
- Question and affected files:
- Evidence:
- Smallest reversible proposal:
- Decision: pending
```

Move answered questions to the monthly history in the same commit that applies
the answer.

---

## Active Exchanges

### A-S1-01-1 — Sonnet 5 assignment

- **Timestamp:** 2026-07-26T09:22:45Z
- **Status:** READY; claim and push before editing.
- **Goal:** Harden the existing collector scaffold against accepted identity,
  metric, and lifecycle contracts. Do not add new probe types.
- **Allowed:** `collector/**`.
- **Excluded:** `backend/**`, `deploy/**`, `docs/contracts/**`,
  `docs/architecture/**`, dependency pins, workflows.
- **Required:**
  1. Validate `site_id` and `collector_id` as ADR 0009 DNS labels.
  2. Emit `sentinel_collector_heartbeat_total`; retain and test
     `collector_heartbeat_total` as a temporary alias.
  3. Preserve `collector_id` and `site_id`; keep OTel `service.name` internally
     and test expected Prometheus mapping to `service_name`.
  4. Add a check lifecycle close contract and close the shared
     `aiohttp.ClientSession` during graceful shutdown.
  5. Test invalid identities, both heartbeat names, session closure, and shutdown.
  6. Run Ruff, mypy, Pylint, and pytest without weakening tests.
- **Exit:** Push a REVIEW handoff with changed files, exact results,
  compatibility behavior, and contract questions.
- **Boundary:** Production ingest/mTLS failure scenarios remain in C1-01 and
  later cross-service integration.

### Pending C1-01 handoff

Codex is implementing the production hub identity and migration foundation.
Latest implementation commit:
`62e8aef5a872c4fb3662f58dad9a1b3b801b0ded`.

### C1-02 — CI/CD assignment

- **Timestamp:** 2026-07-26T09:26:06Z
- **Owner:** CODEX
- **Goal:** Implement GitHub Actions incrementally with the architecture phases.
- **First slice:** add Go backend build/test/vet and migration/schema validation;
  include Go in CodeQL; rationalize duplicated collector lint jobs without
  weakening required checks.
- **Later gated slices:** container multi-arch builds, SBOM and vulnerability
  scanning, artifact signing/provenance, release packaging, deployment
  environments, canary/cohort fleet rollout, rollback, and post-deploy checks.
- **Safety:** deployment workflows remain disabled/manual until production
  Compose, secrets, environments, and rollback procedures exist. CI must never
  target documented live hardware.
- **Exit evidence:** workflow syntax/static validation, local-equivalent commands,
  least-privilege permissions review, and pushed remote read-back.

---

## Archive Procedure

When an item becomes `DONE`, the reviewer must:

1. append its assignment, claim, handoff, review, test results, decisions, and
   commit SHAs to `agent-coordination-history/YYYY-MM.md`;
2. remove its active claim and detailed exchange from this file;
3. add/update the one-line completed reference below the board;
4. commit and push the archive and compact-ledger update together;
5. fetch and read both files back from `origin/main`.

Git history remains the lossless source for earlier verbose ledger states. The
monthly archive provides the readable index and durable summary.
