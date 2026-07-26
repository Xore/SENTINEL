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
| C0-02 | 0 | ADRs and canonical cross-service contracts | CODEX | DONE | C0-01 | `docs/architecture/decisions/`, contract specs |
| S0-01 | 0 | Run current collector quality suite and report implementation inventory | SONNET5 | DONE | None | No source edits; append results here |
| S1-01 | 1 | Collector contract and lifecycle hardening | SONNET5 | READY | C0-02, S0-01 | `collector/**` only; exclusions below |
| C1-01 | 1 | Hub skeleton, migrations, PKI and ingest contract foundation | CODEX | IN_PROGRESS | C0-02 | `backend/`, `contracts/`, `deploy/hub/`, migration tests |

The board is intentionally initialized only through Phase 1. Codex adds later
assignments after each phase gate so stale plans do not cause overlapping work.

---

## File Claims

Add a row before editing and remove the active claim only after handoff. Historical
claims may remain with status `RELEASED`.

| Timestamp (UTC) | Agent | Work ID | Files/directories | Claim status |
|---|---|---|---|---|
| 2026-07-26T09:11:04Z | CODEX | C0-01 | `docs/architecture/REQUIREMENTS-TRACEABILITY.md`, `docs/guides/AGENT-COORDINATION.md` | RELEASED |
| 2026-07-26T09:14:13Z | CODEX | C0-02 | `docs/architecture/decisions/`, `docs/contracts/`, `docs/guides/AGENT-COORDINATION.md` | RELEASED |
| 2026-07-26T09:16:11Z | SONNET5 | S0-01 | `docs/guides/AGENT-COORDINATION.md` only — no source edits | RELEASED |
| 2026-07-26T09:18:30Z | CODEX | C1-01 | `backend/`, `contracts/`, `deploy/hub/`, migration tests, `docs/guides/AGENT-COORDINATION.md` | ACTIVE |

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

### H-C0-02-1

- **Timestamp (UTC):** 2026-07-26T09:18:30Z
- **From:** CODEX
- **To:** SONNET5
- **Status requested:** READY
- **Changed files:** `docs/architecture/decisions/*`, `docs/contracts/*`
- **Behavior implemented:** Accepted canonical source layout, OTLP ingest path,
  metric names/cardinality, durable event/idempotency envelope, federation
  replication, federated privacy boundary, passive Modbus metadata boundary,
  updater authority, HA/versioning, measured scale, identity/time, migrations,
  and service failure invariants.
- **Commands run and results:** Markdown diff check passed; event JSON Schema
  parsed successfully; remote push/read-back verified at `origin/main`.
- **Known limitations:** Concrete protobuf/OpenAPI bindings will be generated
  inside the relevant service work item; contracts intentionally precede code.
- **Assumptions:** New metrics use `sentinel_`; the old heartbeat metric is a
  temporary compatibility alias.
- **Commit SHA:** `569c19e784c43a1e3ceda41ba1fa01addd2e005b`
- **Reviewer result:** accepted
- **Reviewer notes:** Contract prerequisite is complete. Sonnet must finish
  S0-01 review before claiming S1-01. Codex is starting C1-01.

### H-S0-01-1

- **Timestamp (UTC):** 2026-07-26T09:24:00Z
- **From:** SONNET5
- **To:** CODEX
- **Status requested:** REVIEW
- **Changed files:** `docs/guides/AGENT-COORDINATION.md` only. No source files
  touched, per assignment scope.

- **Repository inventory (read-only, base commit `85e7fc5`):**
  - `collector/`: 34 non-test Python files (`config.py`, `__main__.py`,
    `scheduler.py`, `checks/` [`__init__.py` + 5 probes:
    `net_icmp`/`net_tcp`/`net_http`/`net_dns`/`net_latency`], `pki/enroll.py`,
    `transport/` [`mtls.py`, `otlp.py`], `health/loop_watchdog.py`,
    `utils/thread_pool.py`) plus 14 test files, 126 collected tests.
  - No `pki/renew.py`, `transport/retry.py`, `health/score.py`, `os_health/`,
    `store/`, `checks/net_wifi_*`, `checks/net_mtr.py`, `net_snmp.py`,
    `net_arp_watch.py`, `net_modbus.py`, `net_bcast.py`, `net_wireguard.py`,
    `checks/ebpf/`, or `collector/Dockerfile`. Matches
    `REQUIREMENTS-TRACEABILITY.md`'s C0-01 finding; independently confirmed by
    directory listing rather than by re-reading that document alone.
  - `deploy/hub/`: dev-only Compose (`docker-compose.dev.yml`), a Python
    aiohttp stub PKI service (`stub-pki/`, unauthenticated — signs any
    syntactically valid CSR, no bootstrap-token consumption, no revocation),
    an off-the-shelf OpenTelemetry Collector config standing in for ingest,
    VictoriaMetrics, and Postgres with a hand-written `init.sql`
    (`sites`/`collectors`/`events`) — not a migration framework. Note for
    Codex's C1-01 (claims `deploy/hub/`): these files already exist on
    `main` from a prior session, predating this ledger; not created under
    S0-01, and not touched during this assignment.
  - No `hub/`, `backend/`, or `frontend/` source tree exists anywhere in the
    repository. `dashboard/` and a root-level `.venv/` are untracked,
    `.gitignore`d local artifacts from earlier v1 work, not repository
    content (`git ls-files` returns nothing for either).
  - Dependency pins: `collector/requirements.txt` (16 runtime packages) and
    `requirements-dev.txt` (10 dev packages), all exact `==` pins;
    `pip check` reports no broken requirements.
  - CI: `.github/workflows/collector.yml` runs exactly `ruff check .` →
    `mypy .` → `pytest -q` from `working-directory: collector`;
    `pylint.yml` runs `pylint collector tests` separately. Both matched
    verbatim by the commands below.

- **Commands run and results (clean-room venv rebuild, `collector/`,
  Python 3.12.3):**
  ```
  rm -rf .venv .mypy_cache .pytest_cache .ruff_cache __pycache__
  python3 -m venv .venv && . .venv/bin/activate
  pip install -r requirements-dev.txt && pip check
  → No broken requirements found.

  ruff 0.16.0 check .
  → All checks passed!                                    (exit 0)

  mypy 1.20.2 .
  → Success: no issues found in 35 source files            (exit 0)
    (3 informational "annotation-unchecked" notes on untyped test fns;
    not errors)

  pylint 3.3.7 collector tests
  → Your code has been rated at 10.00/10                   (exit 0)

  pytest 9.1.1 -q
  → 125 passed, 1 skipped in 1.07s                         (exit 0)
    (skip: tests/test_config.py:167, SIGHUP test, non-POSIX-only guard;
     correct on this Linux host — it is the *other* SIGHUP branch that's
     skipped)
  ```
  Zero failures across all four tools. Per-file test counts sum to 126 and
  were cross-checked against `pytest --collect-only -q`.

- **Known limitations / implementation gaps** (supplementing
  `REQUIREMENTS-TRACEABILITY.md`, not duplicating its matrix):
  1. **No automated coverage for Phase 1's own exit-gate failure scenarios.**
     The guide requires tests for "untrusted CA, expired certificate,
     mismatched identity, reused token, hub outage, and recovery." None
     exist. The only end-to-end verification of the collector-to-hub path
     to date is a manual, non-repeatable run from a prior session (real
     `python -m collector` against the dev Compose stack, confirmed via a
     live `curl` query against VictoriaMetrics) — not part of `pytest -q`
     and not CI-enforced.
  2. **Collector resource gates are entirely unmeasured.** RSS/CPU on
     Raspberry Pi 3B, PyInstaller binary size, full-cycle wall time, and
     LMDB buffer size (Section 1 table, `SONNET-5-IMPLEMENTATION-GUIDE.md`)
     have zero test or benchmark evidence in the repository. No
     `collector/Dockerfile` and no PyInstaller spec exist to even produce
     the artifact that would be measured.
  3. **Metric-naming ambiguity (Section 4, item 1; now resolved by ADR
     0002/`docs/contracts/METRICS.md`'s `sentinel_` prefix) already caused
     a real bug in a prior session, evidence worth keeping attached to the
     decision:** `transport/otlp.py` originally set OTel-style dotted
     resource attributes (`collector.id`, `site.id`). Prometheus/
     VictoriaMetrics label names cannot contain dots; the remote-write
     exporter silently dropped both attributes instead of sanitizing them
     — no error, no warning, the labels were simply absent from stored
     series. Fixed by renaming to `collector_id`/`site_id` (commit
     `600c716`, predates this ledger). `METRICS.md`'s required-attributes
     table already specifies underscored `collector_id`/`site_id`, so this
     is consistent with the accepted contract; flagging only because the
     failure mode (silent label drop, not an error) is easy to reintroduce
     if a future metric name/attribute uses dots again.
  4. **`checks/net_http.py`'s shared `aiohttp.ClientSession` has no
     shutdown hook.** `HttpCheck` reuses one class-level session across
     instances (correct per `ASYNCIO-OPTIMIZATION.md` §5), but
     `collector/__main__.py`'s shutdown path only calls
     `shutdown_meter_provider()` — nothing closes `HttpCheck._session`.
     Currently dormant (only `_HeartbeatCheck` is wired into the
     scheduler; no `HttpCheck` instance is constructed in `__main__.py`
     yet), so no observable leak today, but it will need a shutdown hook
     (or a registry of check-owned resources to close) before Phase 2
     checks are actually wired into the running collector.
  5. **Docker on this host was reinstalled from the official `docker-ce`
     apt repository**, replacing an earlier Ubuntu-packaged `docker.io`
     install from a prior session, to keep any future bootstrap scripts
     consistent with one real installation procedure. Documented for
     awareness; host-local, not a repository file, not part of this
     assignment's scope.

- **Assumptions:**
  - "Current collector quality suite" means exactly the four commands
    listed in `SONNET-5-IMPLEMENTATION-GUIDE.md` §5 Phase 0 step 2 and
    mirrored in `.github/workflows/collector.yml` / `pylint.yml`; no
    additional tools were run.
  - Per protocol rule 12, the working tree was clean (only this ledger
    file touched) for the entire assignment; no unrelated user changes
    were found to report.
  - `REQUIREMENTS-TRACEABILITY.md`'s per-requirement statuses are treated
    as authoritative for architecture-level tracking; this handoff adds
    quality-suite evidence and a small number of independently-verified
    technical details rather than re-deriving that matrix.
  - This entry was rebased once, in place, on top of `origin/main` after
    Codex pushed `569c19e` and `5a588a2` (C0-02 DONE, C1-01 claimed) while
    this handoff was being drafted; only the S0-01 status cell, the S0-01
    claim-release cell, and this handoff section were changed — no other
    part of Codex's pushed content was altered.

- **Commit SHA:** none (no source changed; ledger-only commit).
- **Reviewer result:** accepted
- **Reviewer notes:** Quality evidence is complete and reproducible. The five
  recorded gaps agree with C0-01 and directly inform S1-01/C1-01.

### A-S1-01-1 — Sonnet 5 assignment

- **Timestamp (UTC):** 2026-07-26T09:22:45Z
- **Owner:** SONNET5
- **Status:** READY; Sonnet must claim and push before editing.
- **Goal:** Harden the existing collector scaffold against the accepted identity,
  metric, and lifecycle contracts. Do not build new probe types in this item.
- **Allowed write scope:** `collector/**`.
- **Excluded files/scopes:** `backend/**`, `deploy/**`, `docs/contracts/**`,
  `docs/architecture/**`, dependency pins, and workflow files. Ask through a
  ledger question if one must change.
- **Required behavior:**
  1. Validate `site_id` and `collector_id` as ADR 0009 lower-case DNS labels.
  2. Emit canonical `sentinel_collector_heartbeat_total`; retain
     `collector_heartbeat_total` as a temporary compatibility alias and test both.
  3. Ensure exported resource identity retains `collector_id` and `site_id`.
     Keep OTel `service.name` internally; document/test its expected Prometheus
     label mapping as `service_name` rather than changing it blindly.
  4. Add a collector/check lifecycle close contract and close the shared
     `aiohttp.ClientSession` during graceful shutdown.
  5. Add focused tests for invalid identities, canonical/compatibility heartbeat,
     session closure, and shutdown behavior.
  6. Run Ruff, mypy, Pylint, and pytest. Do not weaken existing tests.
- **Exit evidence:** Changed-file list, exact commands/results, compatibility
  behavior, and any contract mismatch recorded in a pushed REVIEW handoff.
- **Integration boundary:** Production ingest/mTLS failure scenarios stay with
  C1-01 and later cross-service integration; mock only external boundaries, not
  the collector behavior being tested.

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
