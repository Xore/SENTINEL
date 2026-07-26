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
| S2-02 | 2 | Core network probe activation and hardening | SONNET5 | IN_PROGRESS | S2-01 DONE | exact scope below |
| S3-01A | 3 | Linux host-health new-file foundation | SONNET5 | QUEUED | S2-02 REVIEW | continuity scope in work queue |
| S4-01A | 4 | Envelope and SQLite cold queue foundation | SONNET5 | QUEUED | S3-01A REVIEW | continuity scope in work queue |
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
