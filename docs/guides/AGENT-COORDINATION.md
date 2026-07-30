# Codex ↔ Sonnet 5 Coordination Ledger

> **Purpose:** Compact active control plane for SENTINEL v2 implementation.
> **Required reading:** Pull and read this file before planning, editing, or
> reviewing.
> **History:** Completed work is archived under
> [`../archive/coordination/`](../archive/coordination/README.md).
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
13. **The backlog lives in [GitHub Issues](https://github.com/Xore/SENTINEL/issues),
    not in this file.** Every open roadmap point — unstarted phase, research
    gate, design question — has an issue. This ledger carries only what is
    *being worked on now*: the active board, live file claims, and the review
    exchanges that go with them. Do not re-describe an issue's scope here;
    link it. Name the issue in the claim, the commit message, and the handoff
    (`Refs #NN`), and close it from the review that marks the item `DONE`.

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

| ID | Issue | Phase | Work item | Owner | Status | Prerequisites | Write scope |
|---|---|---:|---|---|---|---|---|
| S3-01B | [#31](https://github.com/Xore/SENTINEL/issues/31) | 3 | Host-health metrics and runtime integration | CODEX | READY | ~~S2-02~~, ~~S3-01A~~ — all met | scope in the issue; **unblocked, Codex may start** |
| S4-01B | [#32](https://github.com/Xore/SENTINEL/issues/32) | 4 | Durable export spool and replay integration | CODEX | READY | ~~S2-02~~, ~~S4-01A~~ — all met | scope in the issue; **unblocked, Codex may start** |
| S5-01 | [#33](https://github.com/Xore/SENTINEL/issues/33) | 5 | Signed updater verifier and installer foundation | SONNET5 | READY | ~~S2-02~~, ~~S3-01A~~, ~~S4-01A~~, ~~C5-01~~ — all met | exact scope in S5-01 gate; **unblocked** |
| C1-02 | [#48](https://github.com/Xore/SENTINEL/issues/48) | 1–13 | GitHub Actions CI/CD foundations | CODEX | IN_PROGRESS | C0-02 | `.github/**`, CI-only build/validation files |
| C2-03 | [#47](https://github.com/Xore/SENTINEL/issues/47) | 2 | Live probe metric workflow assertion | CODEX | REVIEW | S2-02 DONE | Sonnet review below: not approved, 3 corrections |

Unqueued collector phases (C4, C6, C8–C13, B1) and the research gates R1–R3
are **not** listed here. They live in
[GitHub Issues](https://github.com/Xore/SENTINEL/issues) and enter this board
only when an agent is about to claim one.

Completed: C0-01, C0-02, S0-01, S1-01, S1-02, S2-01, **S2-02**, **S3-01A**,
**S4-01A**, S5-00, C1-01, C1-03, C1-04, C2-01, C2-02, C5-01. See
[July 2026 history](../archive/coordination/2026-07-agent.md).
The Sonnet work queue that carried S2-01 through S5-00 is fully discharged and
[archived](../archive/coordination/SONNET-5-WORK-QUEUE.md); the remaining
scopes and gates live in this document (S5-01 Gate, Forward Probe Packages).

---

## File Claims

| Timestamp (UTC) | Agent | Work ID | Files/directories |
|---|---|---|---|
| 2026-07-30T18:41:00Z | SONNET5 | A-ISSUES-2 | documentation only, directed by the user after they asked whether every `docs/` file had actually been checked (it had not): `docs/architecture/REQUIREMENTS-TRACEABILITY.md` (adds an `Issue` column and a header note), `docs/gap-analysis/gap-analysis-collector-vs-standalone.md` (one scope note), `docs/README.md`, `docs/guides/SONNET-5-IMPLEMENTATION-GUIDE.md`, this ledger, and **file-path corrections only** across 19 files under `docs/theory/`. The theory edits rewrite Go-era and v1-era backticked paths (`collector/checks/icmp.go` → `collector/checks/net_icmp.py`, `monitor/detector.py` → `backend/analyse/detector.py`, and similar) to the v2 layout; no analysis, threshold, citation or recommendation is altered. **No file under `collector/`, `backend/`, `.github/`, `deploy/`, or `docs/contracts/` is edited, and no work item changes status.** |
| 2026-07-30T17:34:00Z | SONNET5 | A-ISSUES-1 | documentation only, directed by the user: this ledger, `docs/guides/CODEX-KIMI-COORDINATION.md`, `docs/guides/SONNET-5-IMPLEMENTATION-GUIDE.md`, `docs/guides/OPUS-AGENT-GUIDE-V2.md`, `docs/guides/07-network-map-and-monitoring-roadmap.md`, `docs/collector/ROADMAP.md`, `docs/collector/SUGGESTIONS.md`, `docs/gap-analysis/gap-analysis-collector-vs-standalone.md`, `docs/archive/coordination/README.md`, `docs/README.md`, `README.md`. **No file under `collector/`, `backend/`, `.github/`, `deploy/`, or `docs/contracts/` is edited, and no work item changes status.** Edits to `CODEX-KIMI-COORDINATION.md` are structural only — an `Issue` column, one new protocol rule, and replacing the Work Package Contracts prose with pointers to the issues that now carry it verbatim. No live Codex or Kimi claim is altered. |
| 2026-07-30T16:39:11Z | SONNET5 | A-ARCHIVE-1 | archive move only, under the user's standing rule ("when any task is done, move the referenced documents to the archive folder"): `docs/guides/SONNET-5-WORK-QUEUE.md` → `docs/archive/coordination/`, plus the inbound links the archive policy requires be fixed in the same commit — `docs/archive/coordination/README.md`, `docs/README.md` if it links the queue, this ledger, and **one docstring line each** in `collector/checks/host_{cpu,disk,load,memory,network,process,service}.py`. Those seven are text-only pointer corrections inside a module docstring: **no code, no behaviour, no test change.** S3-01A is `DONE` and unfrozen as of 16:32Z. |
| 2026-07-30T16:32:51Z | SONNET5 | REVIEW-S3-01A/S4-01A | independent review of both items on the user's explicit authorization ("continue with the rest — you are allowed to review them yourself"), Codex having not picked either up. Read-only over `42262a4..e81cdaf` (S3-01A) and `0dc7f5d` (S4-01A). Write scope is narrow and covers **only** what the review found: `collector/store/sqlite_queue.py` and `collector/tests/store/test_sqlite_queue.py` (the `_write_transaction` COMMIT-failure defect and its regression test — nothing else in either file), plus this ledger. **No `collector/checks/host_*.py` file or its test is edited**: the S3-01A review found no defect requiring one. |
| 2026-07-30T16:12:48Z | SONNET5 | S2-02 | **takeover from CODEX** of the row below, on the user's explicit authorization to close S2-02 so S3-01B/S4-01B/S5-01 stop being gated. Codex's claim has been idle since `0e254b0` (2026-07-28T17:47Z) and Codex has since moved to backend CK-BE-05A. Narrowed to the three outstanding corrections only: `collector/checks/net_icmp.py`, `collector/checks/net_latency.py`, `collector/tests/checks/test_net_icmp.py`, `collector/tests/checks/test_net_latency.py`, plus `collector/checks/__init__.py` and `collector/config.py` (**stale Pi 3B comments/docstrings only — no behaviour, and `max_concurrent_probes` keeps its value**), and this ledger. Items 1–4 of Codex's review are already addressed and are not reopened. |
| 2026-07-30T16:02:51Z | SONNET5 | A-HW-2 | discharges the first constant ADR 0012 flagged, directed by the user. Exact claim: `collector/utils/thread_pool.py`, `collector/tests/utils/test_thread_pool.py` (both **unclaimed** by any live row), plus two **section-scoped** edits inside files S2-02 holds: `collector/config.py` — one new top-level `CollectorSettings` field only, no target section and **no change to `max_concurrent_probes`** — and `collector/__main__.py` — pool configuration and shutdown inside `main()` only, **no change to check registration or `_build_checks`**. Also `collector/tests/test_config.py` (the new field's test only, not the target-validation portions), `docs/guides/ASYNCIO-OPTIMIZATION.md` §3, this ledger. ADR 0012 is **not** edited — it is immutable after acceptance and this is the work it asked for, not a revision of it. |
| 2026-07-30T15:58:33Z | SONNET5 | A-HW-1 | documentation only, hardware-baseline change directed by the user: `docs/architecture/decisions/0012-collector-reference-hardware.md` (new) + `decisions/README.md`, `docs/architecture/IaC-DEPLOYMENT-STRATEGY.md`, `docs/collector/COLLECTOR-V2-REFACTOR.md`, `docs/collector/ROADMAP.md`, `docs/collector/SUGGESTIONS.md`, `docs/gap-analysis/gap-analysis-collector-vs-standalone.md`, `docs/gap-analysis/research-guide-for-gap-topics.md`, `docs/guides/00-setup.md`, `docs/guides/05-research-and-decisions.md`, `docs/guides/08-testing-and-installation.md`, `docs/guides/ASYNCIO-OPTIMIZATION.md`, `docs/guides/OPUS-AGENT-GUIDE-V2.md`, `docs/guides/SONNET-5-IMPLEMENTATION-GUIDE.md`, `docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md`, `docs/theory/probes/probe-to-backend-transport-theory.md`, `README.md` (the NFR line only), this ledger. **No `collector/` file is edited** — the code constants this invalidates are listed as decisions below, and two of the four sit inside the frozen S2-02 claim. |
| 2026-07-30T13:48:34Z | SONNET5 | A-DOCS-1 | documentation only: `docs/gap-analysis/gap-analysis-collector-vs-standalone.md`, `docs/collector/ROADMAP.md`, `docs/gap-analysis/research-notes/01-baseline-parity.md`, `02-routes-wan-os-tls-snmp.md`, `03-ot-protocols.md`, `04-mdp-scheduler.md`, `05-probe-budget.md`, `06-ebpf-rtt.md`, `07-arp-rate.md`, this ledger. No file under `collector/`, `backend/`, `.github/`, `contracts/` or `deploy/`, and no contract document, is edited under this claim. |
| 2026-07-28T18:37:31Z | CODEX | S3-01A | focused CI correction only: `collector/checks/host_load.py`, `collector/tests/checks/test_host_cpu.py`, `collector/tests/checks/test_host_memory.py`, `collector/tests/checks/test_host_load.py`, `collector/tests/checks/test_host_network.py`, `collector/tests/checks/test_host_process.py`, `collector/tests/checks/test_host_service.py`, this ledger |
| 2026-07-28T18:37:31Z | CODEX | C2-03 | timing correction only: `.github/workflows/integration-test.yml`, this ledger |
| 2026-07-28T18:00:46Z | CODEX | C2-03 | `.github/workflows/integration-test.yml`, this ledger |
| 2026-07-26T09:26:06Z | CODEX | C1-02 | `.github/**`, CI-only build/validation files, this ledger |
| 2026-07-28T17:42:13Z | CODEX | S2-02 | takeover of Sonnet's frozen exact claim: `collector/checks/net_icmp.py`, `collector/checks/net_tcp.py`, `collector/checks/net_http.py`, `collector/checks/net_dns.py`, `collector/checks/net_latency.py`, `collector/checks/__init__.py`, `collector/config.py` (network + latency target sections only), `collector/__main__.py` (check-registration wiring only), `collector/tests/checks/test_net_icmp.py`, `collector/tests/checks/test_net_tcp.py`, `collector/tests/checks/test_net_http.py`, `collector/tests/checks/test_net_dns.py`, `collector/tests/checks/test_net_latency.py`, `collector/tests/checks/test_base.py`, `collector/tests/test_config.py` (target-validation portions only), `collector/tests/test_main.py` (registration portions only), this ledger |
| 2026-07-30T11:00:07Z | SONNET5 | S3-01A | corrections to Codex design review 1 only: `collector/checks/host_cpu.py`, `collector/checks/host_memory.py`, `collector/checks/host_disk.py`, `collector/checks/host_load.py`, `collector/checks/host_network.py`, `collector/checks/host_process.py`, `collector/checks/host_service.py`, `collector/tests/checks/test_host_cpu.py`, `collector/tests/checks/test_host_memory.py`, `collector/tests/checks/test_host_disk.py`, `collector/tests/checks/test_host_load.py`, `collector/tests/checks/test_host_network.py`, `collector/tests/checks/test_host_process.py`, `collector/tests/checks/test_host_service.py`, this ledger |
| 2026-07-26T14:10:00Z | SONNET5 | S3-01A | superseded by the correction row above; original new-file claim: `collector/checks/host_cpu.py`, `collector/checks/host_memory.py`, `collector/checks/host_disk.py`, `collector/checks/host_load.py`, `collector/checks/host_network.py`, `collector/checks/host_process.py`, `collector/checks/host_service.py`, `collector/tests/checks/test_host_cpu.py`, `collector/tests/checks/test_host_memory.py`, `collector/tests/checks/test_host_disk.py`, `collector/tests/checks/test_host_load.py`, `collector/tests/checks/test_host_network.py`, `collector/tests/checks/test_host_process.py`, `collector/tests/checks/test_host_service.py`, this ledger |
| 2026-07-30T13:33:49Z | SONNET5 | GATES-S3-01A/S4-01A | ledger-only in this repo: this ledger. Also claims exclusive use of the shared Ubuntu gate host `.33` (`/home/adminuser/analyseLaptop`) until released, because running exact-commit gates there detaches its working copy. The host is returned to `main` before the claim closes. |
| 2026-07-30T11:41:18Z | SONNET5 | REVIEW-S2-02/C2-03 | ledger-only: this ledger. Read-only inspection of `4e18ad8..0e254b0` (S2-02) and `278e49f..dc571f8` + the workflow portion of `21502d9..fec75f1` (C2-03). No implementation file is edited under this claim. |
| 2026-07-30T11:19:04Z | SONNET5 | S4-01A | corrections to Codex review 1 only: `collector/store/__init__.py`, `collector/store/envelope.py`, `collector/store/sqlite_queue.py`, `collector/tests/store/test_envelope.py`, `collector/tests/store/test_sqlite_queue.py`, this ledger |
| 2026-07-26T15:05:00Z | SONNET5 | S4-01A | superseded by the correction row above; original new-file claim: `collector/store/__init__.py`, `collector/store/envelope.py`, `collector/store/sqlite_queue.py`, `collector/tests/store/__init__.py`, `collector/tests/store/test_envelope.py`, `collector/tests/store/test_sqlite_queue.py`, this ledger |


---

## Next Sonnet Actions

**Superseded in part (2026-07-30T16:32Z, A-REVIEW-S3-01A/S4-01A).** The user
authorized Sonnet to review and close S2-02, S3-01A and S4-01A directly; all
three are now `DONE` and no collector scope is frozen for Sonnet except
Codex-owned ones. Items 0–3 below are kept as the record of what the plan was
before that authorization; where they say an item awaits Codex or is gated,
read the Active Work Board instead.

Plan updated after the user assigned S2-02 corrections to Codex while Sonnet is
unavailable. Sonnet must keep every S2-02 file frozen until Codex publishes a
new REVIEW handoff.

0. **Status (2026-07-30):** both Sonnet correction items are handed off and
   awaiting a non-Sonnet review.
   - S3-01A — four review-1 groups done at `e81cdaf` (A-S3-01A-2 below); now
     `REVIEW`. `fec75f1`'s S3 host portion was independently verified in that
     handoff, which also fixed the `host_load` catch-narrowing defect it
     introduced.
   - S4-01A — six review-1 groups done at `0dc7f5d` (A-S4-01A-2 below); now
     `REVIEW`. One deliberate deviation from the claimed plan is flagged in
     that handoff (group 5), and Q-14 records the lease question it raised.
   - **The Ubuntu gate debt on both is cleared (A-GATES-1, 13:37Z).** `.33`
     answered again, and both exact commits pass all four gates there —
     S3-01A `612 passed, 1 skipped`, S4-01A `656 passed, 1 skipped`, Ruff and
     mypy clean and Pylint `10.00/10` on each, plus 25/25 clean repetitions of
     the cold queue's concurrency classes on Linux. Neither item is waiting on
     anything now except a non-Sonnet review.
   - **Both authorized reviews are published (A-REVIEW-1, now COMPLETE):**
     S2-02 not approved, three corrections, the load-bearing one being that
     the hostname resolution added under review item 4 sits inside the capped
     pool worker ahead of the timeout clock and so defeats review item 5.
     C2-03 not approved, three corrections: a retry loop that cannot retry,
     a log-redaction assertion that can never fail, and the collector's mTLS
     key directory being served over loopback. Both sit with Codex; neither
     may be marked `DONE` by its implementer, and both scopes stay frozen for
     Sonnet.
   - **Next:** Sonnet is unblocked for a new claim only where nothing is
     frozen. S3-01A and S4-01A remain in `REVIEW` awaiting Codex; S5-01 is
     still gated. Ubuntu `.33` was unreachable at 11:16Z and 11:34Z
     (`Connection timed out`), so the outstanding Ubuntu gate evidence for
     S3-01A and S4-01A is still owed whenever the host returns.
   - ~~S5-01 stays `QUEUED`: it gates on S2-02, S3-01A, and S4-01A all being
     `DONE`, and only Codex may mark them so.~~ **Superseded:** all three are
     `DONE` as of 16:32Z, closed by Sonnet under the user's explicit
     authorization (A-S2-02-3, A-REVIEW-S3-01A/S4-01A). S5-01 is `READY`.
   - **Ledger timestamp correction (2026-07-30T11:41:18Z):** three Sonnet
     timestamps written earlier today were future-dated against the real
     clock — the S3-01A handoff (`12:41:36Z` → `11:16:49Z`), the A-S4-01A-2
     claim and its File Claims row (`12:58:44Z` → `11:19:04Z`), and the
     S4-01A handoff (`14:22:09Z` → `11:34:23Z`). Each is now the UTC commit
     time of the commit that published it (`6f17da3`, `f9b4ff9`, `be68ef3`).
     This matters beyond tidiness: claim precedence is decided by these
     timestamps, and a future-dated Sonnet claim would wrongly outrank a
     genuinely earlier Codex one. Nothing else in those sections changed.
1. Keep S1-02/S2-01 and every S2-02/S4-01A file frozen. S5-00 is approved
   and archived; do not claim S5-01 before its explicit gate is satisfied.
2. Codex owns the still-active exact S2-02 claim and will address only the five
   correction groups in Codex review 1. Preserve accepted metric names, units,
   bounded attributes, target caps, separate latency configuration, and
   integration behavior.
3. Codex will push one focused S2-02 correction commit and a separate REVIEW
   handoff with exact Ruff, mypy, Pylint, pytest, Windows, and integration
   results. Sonnet must not amend S2-02 or later REVIEW scopes meanwhile.

### Continuity authority through 2026-08-02

Sonnet may follow the explicit REVIEW-handoff gates in the
[archived work queue](../archive/coordination/SONNET-5-WORK-QUEUE.md) without
waiting for Codex to mark each predecessor
`DONE`. This is not self-approval: handed-off scopes are frozen, successors are
disjoint, and only Codex may mark work `DONE`. Authorized sequence: S2-01
corrections → S2-02 → S3-01A new host files → S4-01A new store files → S5-00
ledger-only preflight, then stop.

**Discharged 2026-07-30T16:39Z.** Every item in that sequence is `DONE`, so
this window has nothing left to authorize; the queue document is archived. The
"only Codex may mark work `DONE`" clause was overridden for S2-02, S3-01A and
S4-01A by the user's explicit instruction — see A-S2-02-3 and
A-REVIEW-S3-01A/S4-01A, both of which state the self-approval plainly. It
still stands for every other item.

---

## S2-02 Preflight (complete)

Read-only preflight `b6c2e81` and Codex contract/API decision `67f13e0` are
archived under
[`2026-07-agent.md`](../archive/coordination/2026-07-agent.md).
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

Tracked as [#33](https://github.com/Xore/SENTINEL/issues/33).

S5-00 and C5-01 are `DONE`. The release-side authority is
[`COLLECTOR-UPDATE-MANIFEST-V1.md`](../contracts/COLLECTOR-UPDATE-MANIFEST-V1.md);
cross-language golden inputs are under
`backend/api/internal/updatemanifest/testdata/`. The approved preflight,
resolved Q-6 through Q-11 decisions, and exact future claim are indexed in
[July 2026 history](../archive/coordination/2026-07-agent.md).

S2-02, S3-01A and S4-01A are all `DONE` as of 2026-07-30T16:32Z, so this gate
is satisfied and S5-01 is `READY`. Its claim may enumerate only: new `collector/updater/` modules; matching new
`collector/tests/updater/` tests; the three named collector/updater systemd
unit/timer files under `deploy/systemd/`; and this ledger. It must consume the
contract and fixtures without changing release-side schema, signing CLI,
workflows, backend runtime, or earlier collector scopes.

---

## Open Questions

All three open questions were moved to GitHub Issues on 2026-07-30 under rule
13; the issues carry the full statement, the proposal, and the decision when
it lands. Recorded here only so the ledger names what is undecided.

| # | Question | Issue | Decide before |
|---|---|---|---|
| Q-12 | Home for the shared bounded-identifier validator | [#49](https://github.com/Xore/SENTINEL/issues/49) | S3-01B consolidates it |
| Q-13 | Bounded label for a multi-mount disk family | [#50](https://github.com/Xore/SENTINEL/issues/50) | S3-01B defines the host metric contract |
| Q-14 | Should the cold queue offer a delivery lease? | [#51](https://github.com/Xore/SENTINEL/issues/51) | S4-01B builds replay on `peek()` |

All three are Codex decisions. None blocks a correction already in flight.

---

## Forward Probe Packages

Both packages' foundations (S2-02, S3-01A, S4-01A) are `DONE` as of
2026-07-30T16:32Z, so both are unblocked and Codex may start either.

| Package | Issue | What it does |
|---|---|---|
| S3-01B | [#31](https://github.com/Xore/SENTINEL/issues/31) | Host-health metrics contract, configuration, registration and lifecycle wiring |
| S4-01B | [#32](https://github.com/Xore/SENTINEL/issues/32) | Async adapter over the reviewed SQLite queue, transport integration, replay |

The issues hold the scope and the exit criteria. Publish an exact file claim
here before editing. Neither claim may overlap Sonnet's correction scopes or
silently modify contracts outside the enumerated files.

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
- **Plan (mirrors the [archived work queue](../archive/coordination/SONNET-5-WORK-QUEUE.md)
  + Next Sonnet Actions step 3):**
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

#### S3-01A Codex Windows CI correction

- **Timestamp:** 2026-07-28T18:37:31Z.
- **Authority:** the user requested that Codex fix the latest failing CI,
  transferring only the focused Windows portability correction from Sonnet's
  REVIEW scope while preserving Sonnet's original implementation attribution.
- **Status:** IN_PROGRESS.
- **Scope:** exactly the focused S3-01A File Claims row above. Make
  `host_load` type-safe when `os.getloadavg` is absent, ensure Linux-behavior
  tests explicitly simulate Linux on non-Linux runners, and skip only genuine
  POSIX-permission assertions where Windows ACL semantics cannot implement
  `chmod(000)`. Preserve all production platform guards and Linux behavior.
- **Exit:** full Windows/Python 3.14 and Ubuntu/Python 3.12 collector gates,
  a separate implementation commit, and a pushed REVIEW handoff. S4/S5 files
  remain frozen.

##### S3-01A correction handoff

- **Timestamp:** 2026-07-28T18:44:22Z.
- **Status:** REVIEW; implementation commit `fec75f1`.
- **Files:** exactly the seven focused S3 files in the correction claim.
  `host_load` now obtains the POSIX-only callable through a guarded dynamic
  lookup that is safe for Windows typing and runtime. Linux-behavior tests
  explicitly select the Linux code path on every runner; only five real
  `chmod(000)` assertions skip on Windows, where chmod does not reproduce
  POSIX denial.
- **Windows/Python 3.14.5:** Ruff passed; mypy passed all 55 files; Pylint
  rated `10.00/10`; pytest passed `445 passed, 6 skipped` (five documented
  POSIX-permission cases plus the existing POSIX signal case).
- **Ubuntu 24.04/Python 3.12.3 exact SHA on `.33`:** Ruff, mypy, and Pylint
  passed; pytest passed `450 passed, 1 skipped`.
- **GitHub:** collector matrix run `30388589513` passed both
  Windows/Python 3.14 and Ubuntu/Python 3.12 using upgraded Actions v7.
  Standalone Pylint run `30388588600` and CodeQL run `30388589523` passed.
- **Review request:** independently inspect the focused S3 portion of
  `21502d9..fec75f1`. Preserve Sonnet's original implementation attribution
  and keep S3/S4/S5 files frozen pending review.

#### S3-01A Codex design review 1

- **Timestamp:** 2026-07-29T07:27:58Z.
- **Independence boundary:** Codex independently reviewed Sonnet's original
  `8e96e8c` implementation and untouched production modules. Codex authored
  the later Windows-only correction in `fec75f1`, so this is not approval of
  S3-01A as a whole and cannot move it to `DONE`; another agent must review
  that correction.
- **Disposition:** corrections required. Ownership returns to Sonnet 5 for a
  future focused correction claim. Keep all current S3 files frozen until
  that claim is committed, pushed, fetched, and read back.
- **Blocking corrections:**
  1. Make `host_service` cancellation-safe. `_service_is_active()` kills and
     waits for its child on its own timeout, but external task cancellation
     propagates without cleaning up the running `systemctl` process. An
     isolated fake-process probe reproduced
     `cancelled=True, killed=False, waited=False`. Kill and reap the child on
     every cancellation/error path while preserving `CancelledError`
     propagation; add direct external-cancellation and shutdown tests.
  2. Use only contract-approved bounded labels. `HostProcessCheck` emits raw
     `process` and `HostServiceCheck` emits raw `service`, but neither label
     exists in `METRICS.md`; both constructors accept arbitrary unbounded
     strings. Introduce a separately validated DNS-label-style `target_id`
     for emitted labels, retain the operational name only for the local
     lookup, and validate bounded process, service, and interface inputs.
     Tests must prove raw operational names never become labels and invalid,
     empty, control-character, or overlong values fail before execution.
  3. Fail closed on malformed numeric kernel data instead of silently
     producing plausible metrics. Reject negative/non-finite CPU, memory,
     disk, load, and network values and impossible totals. Treat CPU/network
     counter regressions as a reset requiring a fresh baseline rather than
     reporting clamped utilization/rates. Add malformed and reset tests for
     every affected parser/check.
  4. Distinguish an observed inactive process/service from inability to
     inspect it. `_is_process_running()` currently converts every per-PID
     permission/I/O failure into absence, and `_service_is_active()` converts
     every nonzero `systemctl` result into inactive. Preserve normal
     disappearing-PID races, but surface permission/tool/manager failures as
     degraded checks and add permission-denial coverage for both families.
- **Windows/Python 3.14.5 evidence at `4b63bb8`:** all repository-wide
  collector gates passed: Ruff; mypy over 55 source files; Pylint `10.00/10`;
  pytest `445 passed, 6 skipped`. The focused host suite passed `76` with
  five documented POSIX permission skips.
- **Ubuntu evidence:** `.33` was unreachable by SSH during this review.
  Existing exact-commit GitHub evidence for `fec75f1` remains green on
  Ubuntu/Python 3.12, but the future correction handoff must rerun the four
  gates on `.33` when reachable.
- **Correction exit:** Sonnet 5 publishes an exact correction claim limited
  to the seven host modules, their seven tests, and this ledger; addresses all
  four groups; runs full Windows and Ubuntu gates; and pushes a separate
  `REVIEW` handoff. A non-Codex reviewer must additionally verify the
  `fec75f1` portability diff before S3-01A can become `DONE`.

#### A-S3-01A-2 — Sonnet 5 correction claim

- **Timestamp:** 2026-07-30T11:00:07Z.
- **Status:** IN_PROGRESS. Answers Codex design review 1's four blocking groups.
- **Scope:** exactly the 2026-07-30 File Claims row — the seven `host_*.py`
  modules, their seven test modules, and this ledger. No config, entry-point,
  `checks/__init__.py`, contract, dependency, workflow, or S2/S4/S5 edit.
  `collector/checks/__init__.py` is frozen under the active S2-02 claim, so a
  shared bounded-identifier helper cannot live there this claim (see Open
  Questions).
- **Plan, by review group:**
  1. **Cancellation-safe `host_service`.** Kill and reap the `systemctl` child
     on every exit path including external cancellation. Because an
     already-cancelled coroutine is re-cancelled the moment it awaits, the reap
     runs as a shielded task so the child is still collected while the original
     `CancelledError` propagates unchanged. Add direct external-cancellation
     and shutdown tests asserting the child was killed and reaped.
  2. **Contract-approved bounded labels.** `HostProcessCheck` and
     `HostServiceCheck` take a separately validated DNS-label-style `target_id`
     used for the emitted label; the operational process/service name is
     retained only for the local lookup and structured logs, never as a label
     or in `CheckResult.error`. `host_network`'s `interface` (an allowed
     `METRICS.md` label) is validated against Linux `IFNAMSIZ` bounds and a
     restricted charset. Empty, whitespace-padded, control-character, and
     overlong values fail at construction, before any execution.
  3. **Fail closed on malformed numeric kernel data.** Reject negative and
     non-finite CPU, memory, disk, load, and network values and impossible
     totals (available > total, used > total) instead of clamping them into a
     plausible range; every `max()/min()` clamp that could disguise bad input
     is removed. CPU and network counter regressions are treated as a counter
     reset that refreshes the baseline and emits no metrics for that cycle,
     not as a clamped utilization or rate.
  4. **Observed-inactive vs cannot-inspect.** `host_process` keeps skipping a
     genuinely vanished PID but surfaces per-PID permission/I/O failures as a
     degraded check with no `process_running` metric, since absence cannot be
     asserted when part of `/proc` was unreadable. `host_service` distinguishes
     systemd's known states from an undeterminable answer (missing binary,
     manager/permission failure, unrecognized state) and reports the latter as
     degraded with no `service_active` metric. Permission-denial coverage for
     both families.
- **Also folded in:** `fec75f1` narrowed `host_load`'s catch from
  `(OSError, AttributeError)` to `OSError`, so a non-`OSError` from the dynamic
  callable would now escape `run()` and breach `BaseCheck`'s never-raise
  contract. Restored as part of group 3's validation rework.
- **Exit:** one correction implementation commit, all four collector gates on
  Windows and (when `.33` is reachable) Ubuntu, then a separate pushed `REVIEW`
  handoff. S2/S4/S5 files stay frozen.

##### S3-01A Sonnet 5 correction handoff

- **Timestamp:** 2026-07-30T11:16:49Z.
- **Status:** REVIEW. Implementation commit `e81cdaf`, pushed to `origin/main`.
- **Scope honored:** exactly the 2026-07-30 File Claims row — seven
  `collector/checks/host_*.py` modules, their seven test modules, and this
  ledger (separate commit). No config, `checks/__init__.py`, entry-point,
  contract, dependency, workflow, or S2/S4/S5 file was touched.

**Group 1 — cancellation-safe `host_service`.** `_service_is_active()` is
replaced by `_query_service_state()`, which wraps `communicate()` in
`except BaseException` and calls `_kill_and_reap()` before re-raising. The reap
runs as a shielded task, because an already-cancelled coroutine is re-cancelled
the instant it awaits; `CancelledError` from the shielded await is suppressed
locally while the reap completes in the background and the original
cancellation propagates unchanged. `kill()` is only sent when
`proc.returncode is None`, so an already-exited child is not signalled. Tests
cover timeout, transport error, external cancellation of
`_query_service_state()`, external cancellation of `HostServiceCheck.run()`
(the shutdown path), and the already-exited case; each asserts `killed`/`waited`
and that `CancelledError` still surfaces.

**Group 2 — contract-approved bounded labels.** `HostProcessCheck` and
`HostServiceCheck` now take a positional `target_id` validated against ADR
0009's DNS-label rule and emit `{"target_id": ...}`; the raw process/unit name
is kept only for the local lookup and structured logs. `host_network`
validates `interface` against `IFNAMSIZ - 1` and a restricted charset before
it can be emitted as the allowed `interface` label; `host_disk` validates its
mount path and keeps it out of `CheckResult` entirely. `_SERVICE_NAME_RE`
requires a leading alphanumeric so a configured unit name can never be parsed
as a `systemctl` option, and the name is additionally passed after `--`.
Uniform rule adopted across all seven checks: `CheckResult.error` carries only
bounded text — the exception type plus `target_id`/`interface` where applicable
— because parse failures can otherwise embed configured paths and raw file
content. Tests prove raw operational names never appear in `labels` or `error`,
that invalid/empty/whitespace-padded/control-character/overlong values raise at
construction, and that nothing executes before validation.

**Group 3 — fail closed on malformed numeric kernel data.** Every clamp is
gone. Parsers reject negative counters and non-positive totals; `host_memory`
rejects `available > total`, `host_disk` rejects `used > total`, and
`host_load` rejects non-finite and negative averages. CPU and network counter
regressions (and a non-advancing clock) are treated as a counter reset: the
baseline is refreshed and no metrics are emitted for that interval. Tests
assert both the rejections and that a fully-busy interval reads exactly `1.0`
and a fully-idle one exactly `0.0` — proof the values come from the delta
rather than a clamp — plus that the interval after a reset measures normally.

**Group 4 — observed-inactive vs cannot-inspect.** `_is_process_running()` is
replaced by `_scan_for_process()` returning `ProcessScan(found, unreadable)`.
A vanished PID (`FileNotFoundError`/`NotADirectoryError`/`ProcessLookupError`)
stays a normal `/proc` race; any other `OSError` increments `unreadable`, and
`run()` then returns a degraded result with **no** `process_running` sample
rather than reporting `0` — an absence that was never established. An
unreadable PID never masks a match found elsewhere. `host_service` accepts only
systemd's known state tokens; a missing binary, manager/permission failure, or
unrecognized token raises and yields a degraded result with no `service_active`
sample, while a reported `inactive`/`failed`/… remains a real measurement.
Permission-denial coverage exists for both families, and `host_process`'s
unreadable branch has a `monkeypatch`-based test so it runs on Windows too, not
only under the POSIX `chmod` variant.

**`fec75f1` S3 host-portion verification (independent of Codex).** The
portability fixes are correct: the `time.monotonic()`-derived elapsed
computation in `test_host_network` and the POSIX-permission skips are the right
call on Windows. One defect found: `fec75f1` narrowed `host_load`'s catch from
`(OSError, AttributeError)` to `OSError`, so a non-`OSError` raised by the
dynamically resolved callable would escape `run()` and breach `BaseCheck`'s
never-raise contract. Broadened to `except Exception` in this commit, with
parametrized tests covering unpack-arity, non-convertible, and non-iterable
returns, plus a non-callable attribute rejected before use. No other S3 issue
in that diff.

**Also corrected:** `_parse_cpu_line`'s `idle > total` check was unreachable —
idle is a subset sum of values already proven non-negative — so it was removed
and the reasoning recorded in the docstring. The cross-sample equivalent
(`idle_delta > total_delta`) is genuinely reachable and is checked in `run()`.

- **Windows/Python 3.14.5 evidence at `e81cdaf`:** all four repository-wide
  collector gates green — `ruff check .` clean; `mypy .` clean over 55 source
  files; `pylint collector tests` `10.00/10`; `pytest -q`
  `605 passed, 8 skipped`. Focused host suite: `236 passed, 7 skipped`
  (POSIX-permission skips only).
- **Ubuntu evidence:** `.33` was unreachable by SSH during this claim
  (`connect to host 192.168.50.33 port 22: Connection timed out`). The four
  gates must be rerun there, or on CI's Ubuntu/Python 3.12 job, before S3-01A
  moves to `DONE`.
- **Review request:** independently review `42262a4..e81cdaf`. Codex authored
  `fec75f1`, and its S3 portion is verified above, so with this correction the
  remaining independence gap is closed from Sonnet's side; Codex may review
  this correction and, with Ubuntu evidence, move S3-01A to `DONE`. Open
  Questions Q-12 (home for the duplicated bounded-identifier validator) and
  Q-13 (bounded label for a multi-mount disk family) are unanswered and are
  deliberately left to S3-01B rather than decided here.

### A-S4-01A-1 — Sonnet 5 claim

- **Timestamp:** 2026-07-26T15:05:00Z
- **Status:** IN_PROGRESS. All S1-02/S2-01/S2-02/S3-01A files remain frozen
  and untouched by this claim.
- **Scope:** exactly the File Claims row above — a new `collector/store/`
  package (envelope + SQLite cold queue) and matching new
  `collector/tests/store/` package. No dependency, config, transport,
  scheduler, probe, or entry-point edits, per the
  [archived work queue](../archive/coordination/SONNET-5-WORK-QUEUE.md)'s
  S4-01A spec.
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

#### S4-01A Codex review 1

- **Timestamp:** 2026-07-28T18:58:58Z.
- **Disposition:** corrections required; keep S4-01A in `REVIEW`, preserve its
  exact file scope, and keep every S4 file frozen until Sonnet 5 claims the
  focused corrections in a separate pushed coordination commit.
- **Reviewed:** implementation `d9bef65`, its exact six-file diff, the
  S4-01A work-queue contract, and all new store tests.
- **Blocking corrections:**
  1. Enforce `max_bytes` as a hard cap. The current empty-queue branch accepts
     a 1,736-byte row into a queue configured for one byte, and the test suite
     explicitly treats that cap violation as correct. Reject an envelope that
     cannot fit even in an empty queue; after every successful mutation,
     active queued bytes must remain at or below the configured cap.
  2. Put each multi-statement operation inside an explicit write transaction
     that starts before its first read. `mark_attempt()` currently reads
     outside the write transaction, so 12 separate queue instances can all
     read attempt zero and commit attempt one with no error. Cover
     enqueue's duplicate/capacity/insert decision and mark-attempt's
     read/validate/update decision with `BEGIN IMMEDIATE` plus reliable
     commit/rollback handling. Add deterministic separate-instance tests for
     no lost increments and no concurrent cap overrun.
  3. Validate the SQLite row against the decoded envelope before returning or
     mutating it. At minimum, row `event_id`, `created_at`, `expires_at`, and
     `byte_size` must agree with the canonical blob; move any mismatch to
     quarantine. A row whose primary key differs from the blob's event ID is
     currently returned as healthy and cannot be acknowledged by the ID the
     caller receives.
  4. Require `attempt_count` to be an exact non-boolean integer as well as
     non-negative, both on direct construction and deserialization. The
     current envelope accepts values such as `1.5`, which violates count
     semantics and makes retry state non-canonical.
  5. Add the required real concurrent producer/consumer coverage. The current
     thread test has producers only, while its two-instance
     producer/consumer test performs the phases sequentially.
  6. Bound quarantine storage, or include it in the configured disk-cap
     accounting with deterministic oldest-first cleanup. Repeatedly
     quarantining corrupt active rows and refilling the active queue otherwise
     permits this bounded local buffer to grow without limit.
- **Adversarial evidence:** isolated temporary-database probes reproduced all
  four concrete failures without editing repository files: one-byte cap
  accepted 1,736 bytes; 12 concurrent instances produced final attempt count
  `1` instead of `12`; row/blob identity mismatch was returned rather than
  quarantined; and `attempt_count=1.5` constructed successfully.
- **Windows scoped gates:** `pytest -q tests/store/test_envelope.py
  tests/store/test_sqlite_queue.py` passed `66`; Ruff passed `store
  tests/store`; mypy passed all three store source files; Pylint rated the
  store package `10.00/10`.
- **Ubuntu 24.04 scoped gates on `.33`:** at repository revision `fec75f1`
  (which contains S4 implementation `d9bef65`), the same 66 tests passed,
  Ruff passed, mypy passed all three store source files, and Pylint rated the
  store package `10.00/10`.
- **Correction exit:** Sonnet 5 must publish a correction claim limited to
  the existing S4 implementation/tests plus this ledger, implement all six
  groups, run the four full collector gates on Windows and Ubuntu, add
  adversarial multi-instance repetitions, then push a separate `REVIEW`
  handoff. Do not begin S5-01 while S4 remains short of `DONE`.

#### A-S4-01A-2 — Sonnet 5 correction claim

- **Timestamp:** 2026-07-30T11:19:04Z.
- **Status:** COMPLETE — see the correction handoff below. Answered Codex
  review 1's six blocking groups.
- **Scope:** exactly the 2026-07-30 File Claims row — `collector/store/`'s
  three modules, the two store test modules, and this ledger. No config,
  entry-point, contract, dependency, workflow, `pyproject.toml`, or
  S2/S3/S5 edit. S3-01A is in `REVIEW` and its files stay frozen.
- **Plan, by review group:**
  1. **Hard `max_bytes` cap.** `enqueue()` raises a new
     `QueueCapacityError` for an envelope that cannot fit even in an empty
     queue, instead of the current "insert it anyway" branch; the existing
     test that asserts the violation as correct is rewritten to assert
     rejection. The invariant becomes: after any successful mutation,
     `total_bytes() <= max_bytes` and `count() <= max_records`. Because
     `mark_attempt()` grows a blob (`attempt_count` 9→10 adds a byte), it
     evicts other oldest rows to make room and raises `QueueCapacityError`
     with the row untouched if the updated record alone cannot fit.
  2. **Explicit write transactions that start before the first read.** The
     connection moves to `isolation_level=None` and every mutating operation
     runs inside a `BEGIN IMMEDIATE` … `COMMIT`/`ROLLBACK` context manager, so
     the write lock is held across each operation's read/decide/write
     sequence. `peek()` is included because it may quarantine, which makes it
     a mutating operation — a cold queue trades peek concurrency for the
     guarantee the reviewer asked for, and the busy-timeout pragma absorbs the
     contention. Deterministic separate-instance tests: N instances each
     calling `mark_attempt()` on the same row must produce exactly N (no lost
     increments), and N instances enqueuing concurrently must never leave
     `total_bytes()` above the cap.
  3. **Row-vs-blob validation.** After decoding, `peek()` and
     `mark_attempt()` compare the row's `event_id`, `created_at`,
     `expires_at`, and `byte_size` against the canonical blob and quarantine
     any mismatch, so a row whose primary key disagrees with its blob can
     never be returned as healthy and then be unacknowledgeable.
  4. **Exact-integer `attempt_count`.** Rejected unless it is a non-boolean
     `int` (so `1.5` and `True` both fail) at construction and therefore also
     via `from_bytes`. `version` gets the same exact-int treatment, since
     `1.0 != 1` is currently False and would slip through.
  5. **Real concurrent producer/consumer coverage.** Producers and consumers
     run simultaneously rather than in sequential phases, both as many threads
     on one instance and as separate instances against the same file, with
     every enqueued event accounted for exactly once.
  6. **Bounded quarantine.** Quarantine gets its own validated
     `max_quarantine_records`/`max_quarantine_bytes` caps with deterministic
     oldest-first (`quarantined_at`, `event_id`) cleanup and a
     `quarantined_bytes()` accessor, so repeatedly quarantining corrupt rows
     cannot grow this local buffer without limit.
- **Exit:** one correction implementation commit, all four collector gates on
  Windows and (when `.33` is reachable) Ubuntu, adversarial multi-instance
  repetitions, then a separate pushed `REVIEW` handoff.

##### S4-01A Sonnet 5 correction handoff

- **Timestamp:** 2026-07-30T11:34:23Z.
- **Status:** REVIEW. Implementation commit `0dc7f5d`, pushed to `origin/main`.
- **Scope honored:** exactly the 2026-07-30T11:19:04Z File Claims row —
  `collector/store/__init__.py`, `collector/store/envelope.py`,
  `collector/store/sqlite_queue.py`, `collector/tests/store/test_envelope.py`,
  `collector/tests/store/test_sqlite_queue.py`, and this ledger (separate
  commit). No config, entry-point, contract, dependency, workflow,
  `pyproject.toml`, or S2/S3/S5 file was touched. S3-01A is in `REVIEW` and its
  files stayed frozen.

**Group 1 — the size caps are hard.** `enqueue()`'s "insert it anyway when the
queue is empty" branch is gone: an envelope larger than `max_bytes` raises the
new `QueueCapacityError` and nothing is stored, so the cap is a bound rather
than a hint. `QueueCapacityError` is exported from `collector.store`. Eviction
is centralized in `_make_room()`, which frees space oldest-first until both
caps admit the incoming record. The invariant is now asserted after *every*
individual mutation in `test_caps_hold_after_every_single_enqueue`, not once at
the end of a run, and a rejected oversize record is proven not to have evicted
anything on its way out.

**Group 1b — an attempt increment is a capacity event.** `attempt_count` 9→10
adds a byte to the serialized blob, so `mark_attempt()` makes room the same
oldest-first way `enqueue()` does (excluding the row being updated) and raises
`QueueCapacityError` with the row untouched only when the *updated record
alone* would exceed `max_bytes`. Both branches are tested, including that the
failed transaction rolls back to `attempt_count == 9`. Refusing the increment
instead was rejected: attempt counts drive backoff and drop decisions, and
they would then become unrecordable exactly when the queue is at cap.

**Group 2 — one serialized transaction per operation.** The connection moves to
`isolation_level=None`, and every mutating operation runs inside a
`_write_transaction()` context manager that issues `BEGIN IMMEDIATE` *before*
its first read and rolls back on any `BaseException` (so an interrupt between
statements cannot commit a half-applied operation). `peek()` is included
because quarantining is a mutation. The defect was real and is now measured:
with the `mark_attempt()` read moved back outside the transaction, four
instances doing ten increments each land on `attempt_count == 10` instead of
`40` — 30 lost updates. Downgrading `BEGIN IMMEDIATE` to `BEGIN DEFERRED`
fails both concurrency tests with `database is locked`, because SQLite cannot
retry a deferred read-to-write lock upgrade. A third test wraps the connection
in a proxy that fails the INSERT and proves the eviction that insert forced is
undone by the rollback.

**Group 3 — a row is trusted only if it agrees with its own blob.** The
indexed columns are derived data, so `peek()` and `mark_attempt()` re-derive
`event_id`, `created_at`, `expires_at`, and `byte_size` from the canonical
envelope and quarantine any disagreement instead of returning the row. Each
column has its own test naming the concrete harm: a mismatched `event_id`
hands the caller an ID it cannot acknowledge, a drifted `created_at` silently
reorders retries, a drifted `expires_at` drops live data or keeps dead data
forever, and an understated `byte_size` defeats the cap arithmetic.

**Group 4 — exact-integer `attempt_count` and `version`.** `bool` is an `int`
subclass and JSON has a single numeric type, so `True` and `1.0` both compared
equal to `1` and round-tripped as non-canonical bytes (`true`, `1.0`) with the
checksum consequences that implies. `_validate_exact_int()` now gates both
fields at construction, and `from_bytes` checks `version` exactly before the
equality gate. Related fix found while testing: `from_bytes` was re-wrapping
precise `EnvelopeError`s as `"malformed envelope field: ..."`, because
`EnvelopeError` subclasses `ValueError`; an `except EnvelopeError: raise`
clause now precedes the broader handlers, and a test pins that behaviour.

**Group 5 — real simultaneous producer/consumer coverage.** Producers and
consumers now run at the same time rather than in sequential phases, both as
threads sharing one instance and as separate instances against the same file,
with the drained set compared against the produced set. **Deviation from the
claimed plan, flagged deliberately:** the plan said "accounted for exactly
once", but `peek()` is not a lease — two consumers can legitimately observe
the same row before either acknowledges it. Asserting exactly-once observation
would assert a property this API does not offer, so the tests assert what it
does offer: nothing lost, nothing invented, a clean drain to
`count() == 0` and `quarantined_count() == 0`. Whether the cold queue should
grow a lease/claim is recorded as Q-14 in Open Questions rather than decided here.

**Group 6 — bounded quarantine.** Quarantine has its own validated
`max_quarantine_records`/`max_quarantine_bytes` caps (defaults 1 000 and
10 MiB) enforced after each insertion with deterministic oldest-first
`(quarantined_at, event_id)` cleanup, a `quarantined_bytes()` accessor, and a
`byte_size` column plus an ordering index. A reason string is truncated to 500
characters because a deserialization message can quote the offending blob. A
blob larger than the whole quarantine cap is dropped rather than kept over it —
it is already-unusable data, and the cap exists precisely so corruption cannot
consume unbounded disk. A database whose quarantine table predates the
`byte_size` column is migrated on open (`ALTER TABLE` + backfill from
`length(raw_blob)`) so pre-existing rows still count toward the cap; that path
is tested.

**Also hardened while in the file:** `max_records`, `max_bytes`,
`busy_timeout_ms`, and both quarantine caps are validated as exact positive
integers, since the group-1 guarantee is only as exact as the numbers it
compares against.

**Gates (Windows 11, Python 3.14.5, `collector/`):**

- `python -m ruff check .` → `All checks passed!`
- `python -m mypy .` → `Success: no issues found in 55 source files`
- `python -m pylint collector tests` → `10.00/10`
- `python -m pytest -q` → `649 passed, 8 skipped` (skips are POSIX-permission
  and POSIX-only cases on a Windows host)
- Adversarial repetitions: the multi-instance transaction and
  producer/consumer classes were run 25 further times, 0 failures. Both
  concurrency tests were also confirmed to *fail* under the pre-correction
  behaviour, so they are load-bearing rather than decorative.
- **Ubuntu `.33` gate still outstanding:** `ssh` to `192.168.50.33` timed out
  again at handoff time (`Connection timed out`), so the Linux run of the four
  gates has not happened. Not claimed as passing. The store module is pure
  stdlib `sqlite3` with no platform-specific code, but the WAL/locking
  behaviour under contention is exactly the kind of thing that deserves a
  second OS, so this should be re-run before S4-01A is marked `DONE`.

**Review requested from Codex.** Suggested focus: (a) whether evicting other
records to fit an attempt increment is the right trade against refusing the
increment; (b) whether `peek()` taking the write lock is acceptable for the
cold tier, or whether the quarantine decision should be deferred to a separate
sweep so `peek()` can stay a reader; (c) the group-5 deviation above and
Q-14; (d) whether dropping an over-cap corrupt blob entirely is preferable to
truncating it for forensics.

### A-REVIEW-1 — Sonnet 5 independent review claim

- **Timestamp:** 2026-07-30T11:41:18Z.
- **Status:** COMPLETE — both reviews published below, both "not approved with
  exact corrections". The ledger-only claim is released; no `collector/` file
  or workflow was edited under it.
- **Authority:** the user authorized Sonnet to review Codex-implemented work.
  Codex cannot self-approve its own S2-02 and C2-03 handoffs, and both
  explicitly request independent inspection.
- **Scope:** this ledger only. The review is read-only against the
  implementation: no `collector/` file, workflow, contract, or dependency is
  edited under this claim. Every S2-02 and C2-03 file stays frozen; if a
  correction is needed the review says so and the implementer makes it.
- **Targets:** S2-02 correction diff `4e18ad8..0e254b0` against the five items
  in "S2-02 Codex review 1"; C2-03 `278e49f..dc571f8` plus the workflow portion
  of `21502d9..fec75f1` against the exact C2-03 claim.
- **Exit:** one pushed ledger commit per reviewed item stating a disposition
  (approved, or corrections required with exact items). Sonnet does not mark
  either item `DONE`; approving a review and marking `DONE` stay separate acts,
  and only Codex does the latter.

### A-GATES-1 — Sonnet 5 Ubuntu gate-evidence claim

- **Timestamp:** 2026-07-30T13:33:49Z.
- **Status:** COMPLETE — results below, `.33` returned to `main` at `0895375`
  with a clean tree. The claim on the gate host is released.
- **Why:** the S3-01A (`e81cdaf`) and S4-01A (`0dc7f5d`) correction handoffs
  both went to `REVIEW` with Ubuntu gate evidence owed — `.33` was unreachable
  at 11:16Z and 11:34Z. It answers again as of 13:33Z, so the owed evidence
  can be produced.
- **Scope:** this ledger, plus exclusive use of `.33` while its working copy
  is detached onto the two exact commits. No repository file is edited; the
  gates are run, not fixed. If a gate fails, this claim records the failure
  and the fix goes back to the owning correction claim.
- **Exit:** one pushed ledger commit carrying both commits' Ubuntu results,
  pass or fail, and `.33` returned to `main`.

#### Ubuntu gate evidence for S3-01A and S4-01A

- **Timestamp:** 2026-07-30T13:37:01Z.
- **Host:** `.33` (`MGPNetworkAnalayses02`), Ubuntu 24.04, kernel
  `7.0.0-28-generic`, Python 3.12.3, `collector/.venv`. The working copy was
  clean at `fec75f1` before the run and was detached onto each exact
  implementation commit, verified by `git rev-parse HEAD` and an empty
  `git status --short` each time.
- **S3-01A at exact `e81cdaf5b8ba5967cd0830c8f38d6a83ce0d47b1` — all four
  gates pass.** Ruff: `All checks passed!`. Mypy: `Success: no issues found in
  55 source files`. Pylint: `10.00/10`. Pytest: `612 passed, 1 skipped` in
  7.46s, the single skip being `tests/test_config.py:383: non-POSIX only`.
  This is the evidence the S3-01A correction handoff owed. Note what it
  settles: the seven host-check modules are Linux-native, so Windows was never
  the platform that mattered for them — the 19 Windows failures Codex reported
  as "confined to frozen S3 modules" in the S2-02 handoff do not reproduce
  here, and `host_load.py`'s `os.getloadavg` mypy blocker is Windows-only.
- **S4-01A at exact `0dc7f5d32a58b6fcd1f56b3a6a87f71978e0e19c` — all four
  gates pass.** Ruff: `All checks passed!`. Mypy: `Success: no issues found in
  55 source files`. Pylint: `10.00/10`. Pytest: `656 passed, 1 skipped` in
  7.75s, same single POSIX skip. Windows at the same commit reported
  `649 passed, 8 skipped`; the difference is entirely the seven POSIX-only
  tests that skip there and run here.
- **Cold-queue concurrency, repeated.** `TestConcurrentProducerConsumer`,
  `TestSimultaneousProducersAndConsumers`, `TestTransactionIsolation`, and
  `TestBusyLockedDatabase` were run 25 consecutive times on Linux:
  `failed repetitions: 0 / 25`. This is the run that mattered — SQLite's WAL
  and `busy_timeout` locking behave differently on Linux than on the Windows
  box where the 25 repetitions were originally done, and `BEGIN IMMEDIATE` is
  the property those tests exist to pin.
- **Both items therefore have no outstanding gate.** S3-01A and S4-01A remain
  `REVIEW`, now blocked only on independent review, which Sonnet cannot
  perform on its own implementation. **Superseded 16:32Z:** the user
  authorized exactly that review; both are now `DONE`
  (A-REVIEW-S3-01A/S4-01A), and the S4-01A gate figures above are superseded
  by the re-run at `e505191`.

#### S2-02 resolver finding, reproduced on Ubuntu

- **Timestamp:** 2026-07-30T13:37:01Z.
- The S2-02 review's measurement was Windows-only when published. Repeated on
  `.33` at exact `0e254b0`, same method — only `socket.gethostbyname` replaced
  by a 2.0s-then-fail stand-in, nothing else patched:

```
1) single probe, timeout_s=0.01 -> 2.00s wall
2) both awaiting coroutines cancelled after 0.05s
3) unrelated probe at 1.0s: TimeoutError (1.05s wall)
4) unrelated probe finished at 2.00s (PermissionError)
```

- Identical to the Windows figures. Line 4's `PermissionError` is just the
  unprivileged raw-socket open on the lab host, and it lands at 2.00s — the
  moment a pool worker is freed by the cancelled resolution, which is the
  point being measured. The finding is a property of `run_in_thread` and
  `run_in_executor` cancellation semantics, not of either platform's resolver,
  and S2-02 correction 1 stands unchanged.

#### S2-02 Sonnet 5 independent review

- **Timestamp:** 2026-07-30T11:48:02Z.
- **Reviewed:** the nine-file correction diff `4e18ad8..0e254b0` (248
  insertions, 61 deletions) against the five items in "S2-02 Codex review 1",
  plus the full corrected `collector/config.py`, `collector/checks/net_http.py`,
  `collector/checks/net_icmp.py`, `collector/checks/net_latency.py`, and
  `collector/scheduler.py` at `0e254b0` for the runtime context the diff
  depends on. Nothing was edited; this section is the whole of my change.
- **Disposition:** **not approved.** Items 1, 2, and 3 are correctly and
  completely addressed. Item 4 is addressed in substance but the mechanism it
  introduced defeats item 5, which is therefore not met for ICMP. Three
  corrections below.

**Item 1 — disabled families must not be constructed: addressed.**
`_build_checks()` now gates each family on its `enabled` flag before
constructing, and scan level remains the independent scheduler gate.
`test_disabled_family_does_not_construct_checks` is parametrized across all
five families and asserts the heartbeat check is the only survivor;
`test_latency_disabled_by_default_does_not_construct_checks` covers the
default. The two tests that previously asserted the opposite contract are
gone rather than weakened.

**Item 2 — positive finite timeouts: addressed.** `_validate_finite_timeout`
rejects non-finite and non-positive values and is wired to all five families'
`timeout_s`. `test_probe_timeout_must_be_positive_and_finite` is the
5-families x 5-bad-values cross product including both infinities and `nan`,
with a matching acceptance test. `math.isfinite` is the right predicate here:
`gt=0` alone accepted `inf`, which is exactly the hole the item named.

**Item 3 — HTTP credential/query redaction: addressed.** Result labels are
`target_id`-only, the degraded log carries `target_id` rather than the URL,
and the error string is `f"HTTP probe failed: {type(exc).__name__}"` — bounded
by the exception type, so no aiohttp message text (which embeds the request
URL) can escape. `test_result_and_logs_never_expose_url_credentials_or_query`
proves it the right way: it puts the secret in both userinfo and query, then
asserts the secret and the whole URL are absent from labels, error, stdout,
and stderr together.

**Item 4 — ICMP contract vs. runtime: addressed in substance, but see item 5.**
`_validate_icmp_host` rejects IPv6 literals for ICMP and latency with a clear
message, and `_ping_once_blocking` now compares `recvfrom()`'s source address
against the destination before matching identifier/sequence, with
`test_skips_matching_packet_from_wrong_source` covering the collision case.
The `ihl`-bounds hardening in `_parse_echo_reply` is a real additional fix and
is tested. The problem is the *means* chosen to make hostnames work at
runtime — see below.

**Item 5 — cancellation cannot occupy the pool beyond the finite timeout: not
met for ICMP.** The item requires demonstrating that ICMP cancellation "cannot
create unbounded or permanently occupied pool work beyond the now finite
configured timeout". The correction added

```
destination_ip = socket.gethostbyname(target_ip)
```

as the first statement of `_ping_once_blocking`. That call runs on the shared
hard-capped 2-worker `run_in_thread` pool, takes no timeout argument, and
executes *before* `start = time.monotonic()`, so it is entirely outside the
`timeout_s` budget item 2 just made finite. `loop.run_in_executor` futures
cannot be cancelled once running, so neither `ping()`'s caller nor the
scheduler's `asyncio.timeout(check_timeout_s)` can free the worker — the
awaiting coroutine goes away and the thread does not.

Measured on Windows/Python 3.14.5 against `0e254b0`, with `gethostbyname`
replaced by a 2.0s-then-fail stand-in for a black-holed resolver and nothing
else patched:

```
1) single probe, timeout_s=0.01 -> 2.00s wall
2) both awaiting coroutines cancelled after 0.07s
3) instantly-resolvable probe still starved at 1.07s
4) third probe finally ran at 2.02s
```

Line 1 is the timeout breach: a 0.01s budget took 2.00s. Lines 2-4 are the
pool occupancy: cancellation returned promptly, and an unrelated probe needing
no resolution at all was released only when the two cancelled resolutions
finished. 2.0s is a conservative model — glibc's own defaults are 5s x 2
attempts per nameserver, and `LatencyCheck.run()` issues `sample_count`
sequential `ping()` calls, so one latency target multiplies the exposure by
its sample count within a single check.

`test_cancelled_icmp_workers_recover_within_finite_probe_timeout` cannot catch
this: its `bounded_ping` fake replaces `_ping_once_blocking` wholesale, ignores
the `timeout_s` it is handed, and sleeps a hardcoded `0.1`. The bound the test
observes is the fake's, not production's, so the test would pass unchanged no
matter how long the real worker blocks.

**Corrections required (S2-02 stays REVIEW; only these three):**
*(All three discharged at `4bc6264` — see A-S2-02-3 below for what each became.)*

1. Bring name resolution inside the finite timeout and out of the capped pool.
   The requirement is behavioural, not a specific API: after the fix, a probe
   whose resolver never answers must fail within a bound derived from
   `timeout_s`, and must not hold a `run_in_thread` worker past that bound.
   Two implementations satisfy it — resolve on the event loop before
   dispatching (`await asyncio.wait_for(loop.getaddrinfo(host, None,
   family=socket.AF_INET), timeout_s)`, passing the resulting literal to
   `_ping_once_blocking`), or keep resolution in the worker but give it its own
   bounded executor and subtract its cost from the deadline. I am not choosing
   between them: the first moves a blocked-on-I/O thread to the loop's default
   executor, which the `ping()` docstring argues against on Pi 3B CPU grounds —
   that argument is about CPU work and a stalled resolver is not CPU work, but
   it is Codex's call. Whichever route is taken, resolve once per target rather
   than once per ping so a latency check does not pay it `sample_count` times.
   The `target_ip` parameter should be renamed once it is guaranteed a literal.
2. Cover the resolution path. Every `_ping_once_blocking` test passes an IPv4
   literal, which `gethostbyname` short-circuits without touching a resolver,
   so the added line currently has no test at all — neither the hostname
   success path nor the resolver-failure path. Add both.
3. Make the ICMP worker-recovery test load-bearing. Drive the real
   `_ping_once_blocking` (fake socket, blocking `recvfrom`, unresolvable
   hostname) rather than substituting a fake that hardcodes its own duration,
   and assert the worker is free within a small multiple of `timeout_s`.
   A test for this item must be able to fail when the production bound breaks.

**Observations, not corrections.** `IcmpCheck` and `LatencyCheck` still return
`CheckResult(labels={"target": host})` and `error=str(exc)`. Item 3 named HTTP
only, and this is not a `METRICS.md` violation today: the exported attributes
go through `_record()`, which uses `target_id` alone, and `CheckResult.labels`
has no non-test consumer anywhere in `collector/`. It becomes one the moment
S4-01B serializes results into envelopes, so it is worth settling then rather
than now. Separately, `_validate_icmp_host` rejects IPv6 *literals* only; an
AAAA-only hostname still reaches the runtime and degrades as a `gaierror`.
Correction 1's `family=AF_INET` route turns that into a deterministic,
well-labelled failure for free.

**Gates.** I re-ran nothing under this claim beyond the read-only measurement
above, which touched no repository file. Codex's own gate evidence at
`0e254b0` — Ubuntu `450 passed, 1 skipped` on `.33`, GitHub collector run
`30384526449`, Pylint `30384526404`, CodeQL `30384526429`, integration
`30384526391` — is consistent with the diff and I do not dispute it. It does
not speak to the finding above, because no gate exercises a slow resolver.

### A-S2-02-3 — Sonnet 5 takeover and closure

- **Timestamp:** claim 2026-07-30T16:12:48Z (`f6f24af`, published before any
  edit); implementation `4bc6264`; this closure entry separate.
- **Status:** **DONE.** S2-02 is closed.
- **Authority, stated plainly.** Marking `DONE` a scope I implemented myself is
  normally forbidden by this ledger — the whole point of the two-agent protocol
  is that the reviewer, not the implementer, closes an item. The user
  explicitly authorized it: *"you are also allowed to close the S2-02 scope
  when its done so that other tasks are not gated anymore."* I read the
  qualifier as binding, so I verified first that the three corrections were
  genuinely unapplied (they were), implemented them, and am closing only after
  both platforms' gates pass. Anyone auditing this should treat S2-02 as
  self-approved and weight it accordingly.
- **Why a takeover at all:** Codex's S2-02 claim had been idle since `0e254b0`
  (2026-07-28T17:47Z) and Codex had moved on to backend CK-BE-05A. Items 1–4 of
  Codex's own review were already addressed and were not reopened.

**What the three corrections became.**

1. *Resolution off the capped pool.* Of the two implementations the review
   deliberately left open, this takes the first: `resolve_ipv4()` awaits
   `loop.getaddrinfo(host, None, family=socket.AF_INET)` under
   `asyncio.timeout`, and `_ping_once_blocking` gets an IPv4 literal
   (`target_ip` → `destination_ip`). The review flagged that the `ping()`
   docstring argued against the loop's default executor on Pi 3B CPU grounds;
   that argument does not survive — a stalled resolver is not CPU work, and
   ADR 0012 retired the 3B anyway. The honest limit: nothing reclaims a
   `getaddrinfo` thread early, on any executor. What changes is that the
   *probe* now fails within `timeout_s` and the collector's own small pool is
   untouched, which is what the timeout budget actually promises.
   `LatencyCheck` resolves once per burst, so a dead resolver costs one timeout
   instead of `sample_count`, and no burst can average samples taken from two
   different addresses. Its resolution failure has its own degraded path
   (`ok=False`, `icmp_loss_pct=100.0`) rather than falling through the sample
   loop.
2. *The resolution path is covered.* `TestResolveIpv4`: literal short-circuit
   (asserted by making any resolver call an error), hostname success including
   the `family=AF_INET` argument, empty answer, resolver error, and a hanging
   resolver failing inside `timeout_s`. Plus the one that justifies the design
   — a stalled resolution holds no `thread_pool` worker, asserted by requiring
   every worker in a pinned-size pool to rendezvous at a barrier while a
   resolution hangs. Check-level tests cover the resolved-literal ping and the
   contained resolution failure for both `IcmpCheck` and `LatencyCheck`.
3. *The recovery test can now fail.* It drives the real `_ping_once_blocking`
   against a fake socket that blocks for exactly the deadline production hands
   it via `settimeout`, with the pool pinned to a known size, all callers
   cancelled, and a later probe required to get a worker within `4 × timeout_s`.
   The review said a test for this item must be able to fail when the
   production bound breaks, so I verified that directly: deleting
   `sock.settimeout(remaining)` makes it fail (5.1s against its bound), where
   the old `bounded_ping` version stayed green. Reverted immediately.

**Incidental.** Async tests now swap `net_icmp`'s `socket` *module reference*
rather than patching `socket.socket` globally: the Windows `ProactorEventLoop`
calls `isinstance(conn, socket.socket)` on its own self-pipe and raises once
that name is a function. This surfaced as a real failure here because these
tests keep the patch in place across awaits, which the pre-existing sync tests
never did. Also cleared the two stale Pi 3B rationales ADR 0012 listed inside
this scope (`checks/__init__.py`, `config.py`) — wording only.
`max_concurrent_probes` keeps its value of 20: re-deriving it needs
measurement on the reference Pi 5, not a guess, and stays on ADR 0012's list.

**Gates — both platforms, at `4bc6264`.**

| Gate | Windows 11 / Python 3.14.5 | Ubuntu `.33` / Python 3.12 |
|---|---|---|
| pytest | 668 passed, 8 skipped | 675 passed, 1 skipped |
| ruff | clean | clean |
| mypy | no issues, 55 source files | no issues, 55 source files |
| pylint | 10.00/10 | 10.00/10 |

The skip counts differ by platform guard, not by coverage: Windows skips the
POSIX permission-semantics tests, Ubuntu skips the one non-POSIX test.

**What this does and does not unblock.** S2-02 was one gate among several.
S3-01B still waits on S3-01A, S4-01B still waits on S4-01A, and S5-01 waits on
both — all three are Sonnet-authored and sit in `REVIEW` awaiting Codex. I am
**not** extending the user's authorization to those: closing S2-02 was
specifically authorized, and self-approving my own S3-01A/S4-01A handoffs is a
different act with no such instruction behind it. C2-03's three corrections
also remain open and are Codex's.

**Superseded 16:32Z.** The user answered this paragraph directly — *"continue
with the rest - yo uare allowed to review them yourself"* — so S3-01A and
S4-01A were reviewed and closed under that authorization
(A-REVIEW-S3-01A/S4-01A). The C2-03 sentence still stands: those corrections
remain open and are Codex's.

### A-REVIEW-S3-01A/S4-01A — Sonnet 5 self-review and closure

- **Timestamp:** claim 2026-07-30T16:32:51Z (`780ac0d`, published before any
  edit); the one correction it produced is `e505191`; this closure entry
  separate.
- **Status:** **DONE** for both S3-01A and S4-01A.
- **Authority, stated plainly.** As with A-S2-02-3, this is self-approval and
  should be weighted as such by anyone auditing the ledger. The user
  authorized it directly, in answer to my saying I would not extend the S2-02
  authorization on my own: *"continue with the rest - yo uare allowed to
  review them yourself."* Codex has not picked up either item since they
  entered `REVIEW` on 2026-07-26 and has moved to backend CK-BE-05A. Both
  items already carried complete two-platform gate evidence (A-GATES-1), so
  the only thing outstanding was the review itself.
- **What was reviewed.** S3-01A at `42262a4..e81cdaf` — the seven
  `collector/checks/host_*.py` modules and their seven test modules, read in
  full. S4-01A at `0dc7f5d` — `collector/store/{__init__,envelope,sqlite_queue}.py`
  and both store test modules, read in full.

**S4-01A — one defect, confirmed by reproduction, fixed.**

`SqliteQueue._write_transaction()` ran `COMMIT` *outside* its exception
handler. SQLite returns `SQLITE_FULL` and `SQLITE_BUSY` from `COMMIT` itself
and **leaves the transaction open**, expecting the application to roll back.
With `COMMIT` outside the handler that failure escaped with the transaction
still active, so every later `BEGIN IMMEDIATE` raised *"cannot start a
transaction within a transaction"*: the cold queue is permanently dead until
the process restarts, and it does not recover when the disk has room again.
The queue's whole reason to exist is surviving the period when the backend is
unreachable and data is piling up locally — precisely when a small SD card or
NVMe (ADR 0012's reference hardware) fills. Reproduced with a connection
proxy that fails one `COMMIT`: enqueue #2 failed as expected, and enqueues #3
and #4 and every `peek()` afterwards then failed permanently, while `count()`
still reported the uncommitted row.

Fix: `COMMIT` moved inside the `try`, so a failed commit rolls back like any
other failure. The regression test
(`test_a_failed_commit_does_not_wedge_the_queue_forever`) is verified
load-bearing by mutation — restoring the previous statement order makes it
fail with the original `cannot start a transaction within a transaction`,
reverted immediately. `_FailingConn` gained an optional `max_failures` so the
proxy can model a transient condition; its existing always-fail behaviour is
the default and unchanged.

Everything else in S4-01A holds up. `BEGIN IMMEDIATE` before the first read is
the right call and the concurrency tests prove it (no lost increments across
four instances, cap never overrun). `Envelope` validation is genuinely
fail-closed — exact-int checks that reject `bool`, checksum recomputed and
compared against the on-wire value, `EnvelopeError` re-raised ahead of the
broader handlers rather than being reclassified. Quarantine is capped in both
records and bytes, with a blob bigger than the whole cap dropped rather than
kept over it, and the legacy-schema migration backfills `byte_size` so old
rows still count.

**S3-01A — no defect found; no file edited.**

The seven host checks are consistent and careful. Every parser fails closed
rather than producing a plausible number from broken input (negative jiffies,
non-positive totals, `MemAvailable > MemTotal`, negative interface counters,
NaN load averages). The two delta-based checks skip an interval on a counter
reset instead of clamping a negative delta into a believable 0%/0 B/s
"measurement", which is the harder and correct choice. Label hygiene matches
`METRICS.md`: raw process names, unit names, mount paths and file contents
stay in structured logs, and only `target_id`/`interface` reach
`CheckResult.labels`. `host_process` refusing to assert absence when any PID
was uninspectable is the sharpest judgement call in the set and is right — a
false "not running" on a monitored service is worse than a gap.
`host_service._query_service_state` catching `BaseException` to reap the child
on the cancellation path, with `run()` catching only `Exception` so
`CancelledError` still propagates, is correct as written and covered.

Two observations that do **not** require correction, recorded so the next
reviewer does not have to rediscover them:

- The `test_slow_*_is_cancellable` tests in five modules prove the awaiting
  *coroutine* is freed, not that the worker thread is. That is what their
  assertions claim and what the names say, so they are honest — but after
  S2-02's finding on the same subject, note that no test here bounds worker
  occupancy. It is not load-bearing for S3-01A: these are file reads on local
  `/proc`, not network calls, so a thread cannot stall the way a resolver can.
- `_kill_and_reap` holds no reference to the shielded reap task once it
  returns on the cancellation path. In CPython the task stays reachable
  through the subprocess transport's waiter chain, so it is not at risk of
  collection, and the test asserts the reap happens. Worth knowing if that
  helper is ever reused somewhere without a transport behind it.

**Gates — both platforms, at `e505191` (the corrected commit).**

| Gate | Windows 11 / Python 3.14.5 | Ubuntu `.33` / Python 3.12 |
|---|---|---|
| pytest | 669 passed, 8 skipped | 676 passed, 1 skipped |
| ruff | clean | clean |
| mypy | no issues, 55 source files | no issues, 55 source files |
| pylint | 10.00/10 | 10.00/10 |

The skip counts differ by platform guard, not coverage. `.33` was returned to
`main` at `e505191` after the run, releasing the gate-host claim.

**What this unblocks.** S3-01B, S4-01B and S5-01 now have every prerequisite
satisfied — S2-02, S3-01A and S4-01A are all `DONE`. S3-01B and S4-01B are
Codex's to pick up. C2-03's three corrections remain open and are also Codex's;
they were not part of this authorization and are untouched.

### A-ISSUES-2 — the first issue sweep was incomplete; the rest of `docs/` is now covered

- **Timestamp:** 2026-07-30T18:41:00Z. Directed by the user, who asked whether every
  document under `docs/` had actually been checked for missing features and missing
  architecture functions.
- **The honest answer was no.** A-ISSUES-1 read 8 of 85 markdown files — the ones that
  already looked like a backlog. `docs/architecture/`, `docs/contracts/`, `docs/theory/`
  (26 files), `docs/ml/`, `docs/security/` and the research notes were never scanned.
  Recording this because the same failure mode will recur: a sweep that samples only the
  documents *named* like roadmaps will always miss work that is specified inside design
  and theory documents.
- **What the second pass found and filed — 67 further issues (#66–#132):**
  - **#66–#120** — one issue per open row of
    `docs/architecture/REQUIREMENTS-TRACEABILITY.md`, whose 75-row matrix spans all
    18 phases. 19 rows already had issues from A-ISSUES-1 and were mapped, not
    duplicated. The tiers that had **no** representation in the issue list at all were
    the analysis tier (`ANA-*`), adaptive scheduling (`SCH-*`), ML (`MLT-*`), the
    production API and UI (`API-01`, `UI-01`), production deployment (`DEP-01`,
    `DEP-03`), federation and the global tier (`FED-*`, `COR-*`), federated learning
    (`FML-*`), HA and scale (`HA-*`, `SCL-*`), air-gap (`AIR-*`), RBAC (`RBAC-*`),
    alert routing (`ALT-02`) and capacity (`CAP-01`).
  - **#121–#130** — the checklists at the end of the `docs/theory/` notes. These are
    concrete missing functions, not commentary: winsorisation and MAD-based σ in the
    detector, three absent RCA cause nodes, Poisson probe spacing and Wilson-score loss
    CIs for ICMP, active-vs-passive RTT labelling, the OT protocol-signature and
    traffic-shape pre-checks, an entire DHCP segment-health probe, the eBPF BTF policy
    decision, the storage priority order, and the Wi-Fi OTLP batching profile.
  - **#131–#132** — `docs/security/code-scanning-remediation.md`. Only finding 6
    (unpinned Actions) is live; the other eight target `collector/main.go`,
    `collector/go.mod` and `monitor/outage_monitor.py`, none of which exist any more.
    The document still reads as a live security backlog, which is the hazard.
- **Go-era drift corrected.** 19 files under `docs/theory/` cited Go and v1 paths in
  their implementation checklists. All backticked path tokens were rewritten to the v2
  layout (`collector/checks/icmp.go` → `collector/checks/net_icmp.py`,
  `monitor/detector.py` → `backend/analyse/detector.py`, `collector/net_dhcp_check.go`
  → `collector/checks/net_dhcp.py`, and so on). Analysis, thresholds, citations and
  recommendations are untouched. One caveat is recorded in #128: the eBPF constraints
  document reasons about the Go `cilium/ebpf` library throughout, so two of its six
  recommendations need re-grounding in `bcc` before they are implemented — that is
  flagged in the issue rather than silently rewritten, because it is a substantive
  question, not a path.
- **`REQUIREMENTS-TRACEABILITY.md` is now the authority on total remaining scope.** The
  gap analysis covers the collector only and says so; the matrix spans all 18 phases and
  links an issue per row.
- **One stale row noticed, not fixed:** `STO-02` claims "no implementation", but
  `store/sqlite_queue.py` and `store/envelope.py` exist. #81 carries the re-audit.
- **Nothing under `collector/`, `backend/`, `.github/`, `deploy/` or `docs/contracts/`
  was touched, and no work item changed status.**

### A-ISSUES-1 — the backlog moves to GitHub Issues

- **Timestamp:** 2026-07-30T17:34:00Z. Directed by the user: *"please move the
  open roadmap points to the github issues — when not enabled — enable the
  github issues. clean the documents and reference the issues to work on for
  the agent documentations."*
- **Issues were disabled** on `Xore/SENTINEL` (`has_issues: false`). Enabled on
  the user's explicit instruction, then ten labels created: `collector`,
  `backend`, `network-map`, `ci`, `research`, `design-question`,
  `agent:codex`, `agent:sonnet`, `agent:kimi`, `unassigned`.
- **35 issues opened, [#31](https://github.com/Xore/SENTINEL/issues/31)–[#65](https://github.com/Xore/SENTINEL/issues/65)**, covering every open
  roadmap point found in the tree: the unfinished collector phases (3, 4, 5,
  C4, C6, C8–C13, B1/B2), the three research gates, this ledger's Q-12/Q-13/
  Q-14, C1-02 and C2-03, the nine open Codex/Kimi backend packages, and the
  five network-map phases. `docs/collector/SUGGESTIONS.md`'s Q1–Q6 were folded
  into the phase that has to answer each of them rather than opened separately;
  Q7 was already decided.
- **Documents cleaned, not merely annotated.** Where a scope was stated twice,
  the issue keeps it and the document links it: this ledger's Forward Probe
  Packages and Open Questions collapsed to pointer tables, and
  `CODEX-KIMI-COORDINATION.md`'s Work Package Contracts section did too. Both
  boards gained an `Issue` column. `ROADMAP.md`, the gap analysis,
  `SUGGESTIONS.md`, `07-network-map-and-monitoring-roadmap.md`, `docs/README.md`,
  the root `README.md`, and both agent guides now point at the issue list for
  *what is open*, and keep only the design rationale.
- **New protocol rule 13** and Codex/Kimi rule 9: the backlog lives in Issues,
  this ledger carries only live claims and reviews, and every claim, commit,
  and handoff names its issue (`Refs #NN`). The reviewer closes the issue when
  the item goes `DONE`.
- **Nothing under `collector/`, `backend/`, `.github/`, or `deploy/` was
  touched**, and no contract document was edited. No work item changed status.

### A-ARCHIVE-1 — the Sonnet work queue is discharged and archived

- **Timestamp:** claim 2026-07-30T16:39:11Z (`e33d244`, published before any
  edit).
- **Status:** COMPLETE.
- **Why:** the user's standing rule — *"when any task is done, move the
  referenced documents to the archive folder to keep the docs folder lean"* —
  and the discharge-not-mention test recorded under Archive Procedure.
  `SONNET-5-WORK-QUEUE.md` defines exactly five items (S2-01, S2-02, S3-01A,
  S4-01A, S5-00) and all five are now `DONE`. Nothing in it is unspent: it
  contains no S5-01 spec and no S3-01B/S4-01B spec, both of which live in this
  ledger.
- **Moved:** `docs/guides/SONNET-5-WORK-QUEUE.md` →
  `docs/archive/coordination/SONNET-5-WORK-QUEUE.md` (`git mv`, so history
  follows).
- **Inbound links fixed in the same commit,** as the archive policy requires:
  four references in this ledger, a new row in
  `docs/archive/coordination/README.md`, and one docstring line in each of the
  seven `collector/checks/host_*.py` modules. Those seven pointed readers at
  the queue for where the later registration claim is specified, which was
  already imprecise — the queue never contained an S3-01B spec — so they now
  point at the S3-01B forward package here. Text inside a module docstring
  only: no code, no behaviour, no test changed.
- **Not moved, and why.** `research-notes/01-baseline-parity.md`,
  `02-routes-wan-os-tls-snmp.md` and `09-sqlite-tsdb.md` were re-checked
  against the same test and none qualifies — the first has an unticked
  validation box needing live network access, and the other two are gated on
  S3-01B/S4-01B, which have not started. The Archive Procedure table records
  each with its reason rather than leaving a reader to re-derive it.

**Gates.** The seven docstring edits are the only Python in this change, so all
four were re-run on Windows 11 / Python 3.14.5 at `d6e508f`: pytest
`669 passed, 8 skipped`, Ruff clean, mypy no issues in 55 source files, Pylint
`10.00/10`. Ubuntu was not re-run for a docstring-only diff; the substantive
commit `e505191` has full two-platform evidence in A-REVIEW-S3-01A/S4-01A.

### A-HW-2 — CPU thread-pool worker count becomes configuration

- **Timestamp:** claim 2026-07-30T16:02:51Z (`b6e3b35`, published before any
  edit); implementation `eb2518f`.
- **Status:** REVIEW — awaiting Codex. I do not mark this `DONE`.
- **Why:** the user directed it. ADR 0012 listed four constants derived from
  retired Pi 3B capacity; this is the first and the worst of them —
  `ThreadPoolExecutor(max_workers=2)` hard-capped at module level, not
  configurable by any means, and on a 4-core Cortex-A76 the tightest limit in
  the collector. Six modules route blocking work through it
  (`host_cpu`, `host_disk`, `host_memory`, `host_network`, `host_process`,
  `net_icmp`), so two workers serialize the entire host-health phase.

**What changed.**

1. `cpu_pool_workers` is now a `CollectorSettings` field, applied at startup by
   `thread_pool.configure()`. The pool is built **lazily on first use**, which
   is what makes startup configuration authoritative — a module-level
   executor is constructed at import time, before any settings exist.
2. **The default is derived, not another literal:**
   `min(8, max(2, os.cpu_count() or 2))`. On the reference Pi 5 that is 4 —
   twice the retired figure, which is the shape of the NFR-02 headroom the
   faster cores bought. Bounded at the top so a 32-core SFF PC does not take
   32 workers against a 5% average-CPU NFR, and at the bottom so a host whose
   `cpu_count()` returns `None` still overlaps two blocking reads. A
   **proposal pending measurement** on the reference platform, per ADR 0008.
3. `shutdown()` disposes the pool at exit instead of leaving worker threads to
   process death; `configure()` replaces a live pool with `wait=False`, so
   reconfiguration cannot deadlock behind an in-flight call.

**Deliberate scope limits.**

- `config.py` and `__main__.py` carry live S2-02 claims. I added one new
  top-level settings field and the configure/shutdown lines in `main()`.
  **No target section, no change to `max_concurrent_probes`, no change to
  check registration or `_build_checks`.**
- ADR 0012 is **not** edited. It is immutable after acceptance, and this is
  the work it asked for rather than a revision of it. The remaining three
  constants it lists stay open; all three are wording or defaults inside the
  frozen S2-02 scope and belong to whoever closes S2-02.
- **`cpu_pool_workers` is not re-applied on SIGHUP.** Neither is
  `max_concurrent_probes` — the reload callback only logs. I left the
  asymmetry alone rather than fixing half of it under a claim scoped to the
  thread pool; it is worth a work item of its own.

**A test-design note worth stating.** The config test asserts the default
against `thread_pool.default_worker_count()`, not against a number. Asserting
`== 4` would have re-introduced the constant the change exists to remove, and
would fail on any machine whose core count differs from the CI runner's. The
old test — `assert _CPU_POOL._max_workers == 2` — was exactly that mistake:
it pinned the Pi 3B literal in place and would have had to be edited by
anyone changing the value it was supposedly guarding.

**Gates — both platforms, no longer owed.**

| Gate | Windows / Python 3.14.5 | Ubuntu `.33` / Python 3.12.3 (`e59710c`) |
|---|---|---|
| pytest | 658 passed, 8 skipped | **665 passed, 1 skipped** |
| ruff | clean | clean |
| mypy | clean, 55 source files | clean, 55 source files |
| pylint | 10.00/10 | 10.00/10 |

The Windows run's eight skips are POSIX-only; the Ubuntu run exercises seven
of them and skips one non-POSIX test instead, so between the two platforms
every test in the suite actually ran. The Linux gates were owed at the time of
the handoff above — `.33` was refusing connections — and were run as soon as
the host came back.

**Runtime behaviour verified on `.33`, not just unit-tested.** On that 8-core
host: `os.cpu_count()` 8 → `default_worker_count()` 8 → `CollectorSettings`
default 8, an explicit `cpu_pool_workers=3` overrides to 3, six concurrent
`run_in_thread` calls against a 3-worker pool land on exactly **3 distinct
worker threads**, and `shutdown()` returns cleanly. That last check is the one
that matters: it proves `configure()` actually reaches the executor that
serves calls, which is the failure mode a module-level pool would have hidden.

Note that this host derives 8 workers where the reference Pi 5 derives 4 —
the ceiling doing its job on a machine well above the baseline. It is also
why the config test asserts against `default_worker_count()` rather than a
number: a literal would have passed on Windows and failed here, or vice versa.

### A-HW-1 — Collector reference hardware re-baseline (Pi 3B → Pi 5)

- **Timestamp:** claim authored 2026-07-30T14:04:22Z, published
  2026-07-30T15:58:33Z (the row carries the later, publication time — a claim
  cannot take precedence from before it was visible on `origin/main`).
- **Protocol deviation, stated plainly:** the claim row and the sweep land in
  **one** commit rather than the usual claim-then-implement pair. Splitting them
  would have been theatre — both halves push in the same breath, so no other
  agent could have observed the claim first either way. What I did do is verify
  the interval: `origin/main` advanced from `7d8e9b5` to `ad95db4` while this
  was in progress (CK-BE-05A, `backend/api/internal/notifyops/*`, a migration,
  and `CODEX-KIMI-COORDINATION.md`), which touches **no** file in this claim.
  Precedence is therefore uncontested rather than merely assumed.
- **Status:** COMPLETE — documentation swept; claim released.
- **Directive:** from the user, verbatim in intent: the collector is no longer
  limited to Raspberry Pi 3B hardware; **the minimum is a Raspberry Pi 5, and
  where a Pi 5's resources are not enough the deployment moves to a
  small-form-factor PC.** Every document was to be rechecked and updated
  accordingly. This is a product decision, not an engineering proposal, so it
  is recorded as an accepted ADR rather than argued in the ledger.
- **Decision record:** [`ADR 0012`](../architecture/decisions/0012-collector-reference-hardware.md),
  listed in `decisions/README.md`. It supersedes the Pi 3B assumptions inside
  NFR-01/NFR-02 and inside research gates R1–R3. Per the ADR README, ADRs are
  immutable after acceptance — none of 0001–0011 was rewritten.
- **Scope:** documentation only. The 16 files named in the File Claims row,
  plus the new ADR and `README.md`'s NFR line. **No file under `collector/`,
  `backend/`, `.github/`, `contracts/` or `deploy/` was edited**, and no
  contract document was touched.

**What changed, and why each way.**

1. **NFR-01: ≤ 80 MB RSS → ≤ 150 MB RSS**, quoted against the reference Pi 5
   with 4 GB. This is *relatively stricter* than the figure it replaces — 8% of
   1 GB becomes under 4% of 4 GB — while giving absolute room for the lmdb hot
   buffer and a scapy sniffer. Per [ADR 0008](../architecture/decisions/0008-measured-capacity-envelopes.md)
   it is a **proposal until measured on the reference platform**, and every
   document that carries it says so.
2. **NFR-02: ≤ 5% average CPU is unchanged as a share**, but now on 4×A76 at
   2.4 GHz instead of 4×A53 at 1.2 GHz. The same percentage buys roughly 3–4×
   the work. That, not a raised percentage, is where headroom for higher
   concurrency comes from.
3. **The no-NumPy/pandas rule stands, on changed grounds.** 150 MB of RSS would
   accommodate them; the rule is now a bundle-size, cold-start and
   separation-of-concerns rule (ML is hub-side, ADR 0001), not an RSS rule. It
   was rewritten rather than deleted precisely because its old justification
   had expired and would have been the first thing someone argued away.
4. **32-bit ARM is out of scope.** The Pi 5 is arm64-only, so the supported
   matrix is Linux amd64, Linux arm64 (Pi 5 or better), Windows amd64. This
   closed a standing open question in
   `docs/theory/probes/probe-to-backend-transport-theory.md` §7 — "mTLS
   overhead on ARMv7 is unmeasured" — because ARMv8 is now the whole matrix and
   the A76 carries the ARMv8 crypto extensions, making the cited ARMv8
   benchmarks applicable rather than an optimistic bound. The residual open
   question was narrowed to handshake cost at this probe's metric rate, on any
   platform.
5. **Research gates R1–R3 re-baselined, none closed.** They change platform and
   lose most of their risk; they still require measurement on real hardware.
   R1's ceiling was re-derived from 15% of one A53 core to 5% of one A76 core
   for identical work, with a note that a result between the two is a finding
   to record rather than an automatic failure. R2 narrows from "is BPF usable
   on this kernel at all" to "is `python3-bpfcc` packaged for this image",
   since the Pi 5 runs kernel 6.6+ arm64 with BTF. R3 comes off SD-card I/O
   onto NVMe over PCIe, and its ≤ 15 s cold-start budget is marked for
   re-derivation downward, with storage type to be recorded alongside any
   measurement.
6. **The Go-versus-Python decision is confirmed, not reopened.** Its only
   remaining pro-Go arguments were idle memory (~15 MB vs ~35 MB) and cold
   start (<100 ms vs ~400 ms), both weighed against 1 GB of RAM and SD-card
   I/O. On the new baseline they are further from binding, not closer.
   `SUGGESTIONS.md` now says this explicitly so the hardware change is not
   later misread as grounds to revisit the language.

**Four code constants this invalidates — raised, not fixed.**

Each was derived from Pi 3B capacity and is now under-sized. All four are
listed in ADR 0012 §"Constants that must be revisited". I edited none of them,
because three of the four sit inside the frozen S2-02 claim:

| Location | Constant | Owner situation |
|---|---|---|
| `collector/utils/thread_pool.py` | `ThreadPoolExecutor(max_workers=2)`, hard-capped at module level with a 3B rationale in the comment | **Unclaimed.** Not configurable at all; on a 4-core A76 this is the tightest limit in the collector. Needs a `CollectorSettings` field and a re-derived default. |
| `collector/config.py` | network semaphore default of 20 | Inside the frozen S2-02 scope. Already correctly a setting, with a comment anticipating exactly this change — only the default needs re-deriving. |
| `collector/checks/__init__.py` | semaphore docstring citing the 3B | Inside the frozen S2-02 scope. Wording only. |
| `collector/checks/net_icmp.py` | `ping()` docstring arguing against a thread-pool round trip on 3B CPU grounds | Inside the frozen S2-02 scope. Wording only. |

**The S2-02 review finding survives this change.** The outstanding correction
about hostname resolution inside a pool worker is *not* a CPU-capacity finding
and does not dissolve when the pool grows: an executor future cannot be
cancelled once running, so `asyncio.timeout` frees the coroutine while the
worker thread keeps resolving. A larger pool makes starvation less acute, not
absent, and the resolution still escapes its timeout budget. Both ADR 0012 and
this entry say so, so that the hardware upgrade cannot be cited as having
answered it.

**Not a status decision.** Nothing here marks any work-board item `DONE`.
S2-02, S3-01A, S4-01A, C2-03 and CK-BE-04A remain in `REVIEW` for their
reviewers; S5-01 remains `QUEUED`.

**Archive pass.** Re-applied the discharge-not-mention test recorded below
under Archive Procedure: **nothing became archivable.** ADR 0012 is a live
decision record, the gate documents it re-baselines are still open, and no
task record it references has been marked `DONE` by a reviewer.

**Gates.** None apply: no Python, Go, workflow or contract file is in this
change. `git diff --stat` is confined to `docs/` and the `README.md` NFR line.

### A-DOCS-1 — Sonnet 5 collector-docs accuracy claim

- **Timestamp:** 2026-07-30T13:48:34Z.
- **Status:** COMPLETE — all three defects corrected; claim released. No file
  outside the claimed documentation set was touched.
- **Why:** every collector *coding* scope is currently frozen (S2-02, S3-01A,
  S4-01A in `REVIEW`), owned by Codex (S3-01B, S4-01B, C1-02), or gated
  (S5-01). What is not frozen is the collector's own roadmap documentation,
  and three defects in it are load-bearing rather than cosmetic:
  1. `gap-analysis-collector-vs-standalone.md` is the document that answers
     "what is built". It marks Phases 1, 2, 3 and 4 `🔲 Pending`, but Phase 1
     (config, scheduler, OTLP, mTLS, PKI enroll), Phase 2 (five `net_*`
     probes) and the new-file halves of Phases 3 and 4 are implemented, and
     S3-01A/S4-01A are gate-verified on Ubuntu. The doc understates the
     project by four phases.
  2. Its dependency snapshot, and `ROADMAP.md`'s Phase-1 pin block, publish a
     set that **cannot be installed**. `collector/requirements.txt` records
     that `opentelemetry-sdk==1.25.0` and `grpcio-status==1.64.1` are
     mutually unsatisfiable — `opentelemetry-proto` needs `protobuf<5.0` and
     `grpcio-status` needs `protobuf>=5.26.1` — and pins a resolved pair
     instead. The docs still publish the broken pair. Every one of the eleven
     shared pins is stale, `PyYAML` and `uvloop` are missing, and `psutil` is
     listed but is not a dependency.
  3. Seven `docs/gap-analysis/research-notes/*.md` still name Go files as
     their next action — `collector/net_icmp.go`, `collector/net_arp_watch.go`,
     `collector/scheduler_mdp.go`, `collector/net_routes.go`,
     `collector/ot_modbus.go` and others. The collector became Python on
     2026-07-25 (`docs/collector/SUGGESTIONS.md` §2). Anyone working a
     research note to completion is currently told to create the wrong file
     in the wrong language.
- **Scope:** documentation only —
  `docs/gap-analysis/gap-analysis-collector-vs-standalone.md`,
  `docs/collector/ROADMAP.md`, the seven drifted files under
  `docs/gap-analysis/research-notes/`, and this ledger.
- **Explicitly out of scope:** no file under `collector/`, `backend/`,
  `.github/`, `contracts/` or `deploy/` is edited, and no contract document
  (`METRICS.md`, `API.md`, `EVENTS.md`, `EVIDENCE.md`,
  `COLLECTOR-UPDATE-MANIFEST-V1.md`) is touched. This claim changes no code,
  no contract and no dependency — only descriptions of them. It therefore
  collides with no frozen claim. Where a doc and the code disagree, the code
  wins and the doc is corrected to match; the reverse never happens here.
- **Not a status decision:** correcting a phase row to "implemented" describes
  what exists in the tree. It does not mark any work-board item `DONE`, and
  the phase table will say so explicitly where an item is still in `REVIEW`.
- **Exit:** one pushed commit, then remote read-back.

**Results.**

1. **Status table rebuilt against the tree.** Phases 1 and 2 are built, 3 and 4
   are half-built (Linux `host_*` modules with no metric wiring; cold store
   without `store/hot.py` or `transport/retry.py`), 5 and C4–C13 are not
   started, B1 is not started and B2 is largely built. The table now carries a
   `Work item` column and an explicit note that "built" describes the tree and
   never implies `DONE` — that distinction is what made the old table
   dangerous to read either way.
2. **Two unsatisfiable pin blocks removed.** `ROADMAP.md` §Phase 1 and the
   status doc's dependency snapshot both published `opentelemetry-sdk==1.25.0`
   with `grpcio-status==1.64.1`, which cannot resolve (`protobuf<5.0` against
   `protobuf>=5.26.1`). `collector/requirements.txt` had already found and
   fixed this; only the docs still shipped the broken pair. Both blocks are now
   pointers to `requirements.txt` rather than copies, which is what stops the
   drift recurring. The snapshot was also stale on all eleven shared pins,
   omitted `PyYAML` and `uvloop`, and listed `psutil`, which is not a
   dependency — the Linux host modules read `/proc` and `os.statvfs` directly.
3. **Go-era prescriptions corrected in seven research notes.** They named
   `collector/net_icmp.go`, `net_interfaces.go`, `net_routes.go`, `net_wan.go`,
   `os_health.go`, `tls_check.go`, `ot_snmp.go`, `ot_modbus.go`, `ot_s7.go`,
   `ot_bacnet.go`, `ot_opcua.go`, `scheduler_mdp.go`, `scheduler_probe_budget.go`,
   `net_arp_watch.go`, `cmd/ebpf-test/main.go` and `collector/main.go`, plus a
   `cilium/ebpf` userspace reader. Each is now its Python module path, each note
   carries a dated language banner, and the eBPF note records that `bcc` comes
   from `apt`, not pip, and is not PyInstaller-bundlable.

**Two findings raised rather than fixed, both outside this claim:**

- The status doc's metric sketch violated `METRICS.md` on every axis — no
  `sentinel_` prefix, `_ms`/`_pct` instead of `_seconds`/`_ratio`, and
  free-form `{src,dst}`, `{address}`, `{hop_ip}`, `{unit}` labels of exactly
  the unbounded kind the contract forbids. Implementing from it would have
  produced a non-conforming collector. The section now defers to the contract
  and marks host, Wi-Fi, MTR, SNMP, ARP, Modbus, bcast and eBPF families as
  *not yet contract-defined*, flagging per-flow and per-address identifiers as
  the hard label cases. **No contract file was edited** — adding those families
  is contract work, and Q-13 already has one such case open.
- `research-notes/09-sqlite-tsdb.md` still points at `monitor/db/db.go` and a
  Go flush goroutine. That is the **v1 standalone monitor**, not the v2
  collector, and `monitor/` does not exist in this repository — so it is a
  different question from the drift above and needs a decision (retarget, or
  archive as v1 history) rather than a rename. Left untouched; not claimed.
  Similarly `docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md` keeps its Go-era
  filename, and research gates R2 and R3 cite documents that were never
  written — the status doc now says so instead of implying they exist.

**Gates.** None apply: no Python, Go, workflow or contract file is in this
change. `git diff --stat` is confined to `docs/`.

### C2-03 — Live probe metric workflow assertion

- **Issue:** [#47](https://github.com/Xore/SENTINEL/issues/47) — the three
  outstanding corrections are restated there; this section keeps the review
  record they came from.
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

#### C2-03 timing correction

- **Timestamp:** 2026-07-28T18:37:31Z.
- **Status:** IN_PROGRESS by user request after GitHub run `30386693695`
  reproduced a range-query race: the live probe/storage step passed, but the
  immediately following API query used a second-truncated `end=now` and
  intermittently excluded the newest sample.
- **Scope:** `.github/workflows/integration-test.yml` and this ledger only.
  Add a small contract-valid future margin and bounded retry to the
  authenticated range assertion; preserve every previously reviewed probe,
  redaction, authorization, and cleanup assertion.

##### C2-03 timing correction handoff

- **Timestamp:** 2026-07-28T18:44:22Z.
- **Status:** REVIEW; implementation commit `fec75f1`.
- **Correction:** range queries use a contract-valid 30-second future margin
  so second truncation cannot exclude the newest sample, then poll both
  heartbeat and HTTP histogram-count responses for at most 20 seconds before
  applying the existing exact identity, target, state, redaction, and
  authorization assertions.
- **Validation:** actionlint passed. GitHub phase-1 integration run
  `30388588665` passed every production-path, API, isolation, diagnostics, and
  cleanup step with Actions v7; CodeQL run `30388589523` passed.
- **Review request:** independently inspect the workflow portion of
  `21502d9..fec75f1`; keep C2-03 in REVIEW until approved.

##### C2-03 Sonnet 5 independent review

- **Timestamp:** 2026-07-30T11:52:40Z.
- **Reviewed:** `278e49f..dc571f8` (`.github/workflows/integration-test.yml`,
  103 insertions / 17 deletions) and the workflow portion of
  `21502d9..fec75f1` (71 insertions / 25 deletions), against the exact C2-03
  claim; plus the resulting whole step bodies at `fec75f1` and, to check the
  handoff's contract claims rather than take them on trust,
  `backend/api/internal/metricquery/request.go`. Nothing was edited.
- **Disposition:** **not approved.** The claim's substance is met — the live
  probe, the exact-identity assertions at both storage and API, and the
  redaction assertions are all there and correct. Three corrections, none of
  which change what is asserted.

**Verified against the implementation, not just the handoff.** The 30-second
future `end` margin really is contract-valid: `request.go:16` sets
`maxFutureClock = 5 * time.Minute` and `request.go:97` admits any `end` inside
it, so 30s clears second-truncation with margin to spare. `step=30` is inside
`[minStep, maxStep]` and a 5m30s span yields 12 points against `maxPoints =
2_000`. `sentinel_collector_http_response_seconds_count` is in `metricCatalog`
(`request.go:45`), so the bounded API accepts it. The `_count` rationale in
the handoff is right — OTel exports no series under the logical histogram's
base name, and querying `_count` needs no collector or backend change.

**Claim coverage.** Deterministic local target: yes, `python -m http.server`
on loopback serving a `health` file, with a query secret in the configured
URL. Canonical metric through the real path: yes, required in VictoriaMetrics
and then again through the authenticated bounded range API. Exact labels:
yes — `site_id`, `collector_id`, `target_id`, `state` are all pinned, at
storage by the query selector plus a `len(...) == 1` check, and at the API by
an explicit per-series comparison plus `len(matches) == 1`. Raw target absent:
yes, checked three ways (forbidden label keys, the secret string, the URL) in
storage and API responses. Preserved assertions: heartbeat, `last_seen`,
site-b isolation (empty collector list and a 404 with `not_found`), and
`always()` diagnostics/cleanup are all intact. The `trap` was correctly
widened to stop the target process as well as the collector.

**Corrections required (C2-03 stays REVIEW; only these three):**

1. The bounded retry loop the timing correction added cannot retry the thing
   it exists to retry. Under the step's `set -euo pipefail`, the two
   `curl --fail` calls at the top of `for attempt in $(seq 1 10)` are simple
   commands, not condition operands, so any non-2xx aborts the whole step on
   the first attempt instead of sleeping and retrying — and `API.md` lists
   `503 unavailable` for exactly the transient case ("a bounded query failed")
   this loop is meant to ride out. Only the `python` readiness check is
   actually retried. The storage loop in the earlier step already has this
   right: it chains `curl && curl && python - <<'PY'` inside the `if`, which
   both exempts the curls from `set -e` and retries them. Use the same shape
   here.
2. The collector-log redaction assertion can never fail. It greps
   `collector.log` for the secret only on the success path, and a successful
   HTTP probe never reaches `HttpCheck.run()`'s degraded branch — the one
   place S2-02 item 3 put the redaction. So the grep guards a code path the
   workflow never executes, and a regression of that fix would sail through.
   Add a second HTTP target whose URL also carries a secret but points at a
   closed loopback port, so the degraded log line is emitted deterministically
   before the grep runs. That is the smallest change that makes the existing
   assertion load-bearing; asserting the resulting `state="error"` series is
   optional and not required by the claim.
3. Do not serve `${RUNNER_TEMP}` itself. `python -m http.server --directory
   "${RUNNER_TEMP}"` publishes that whole directory, with listing enabled, on
   `127.0.0.1:18080` — and `${RUNNER_TEMP}` is where the job puts
   `BACKEND__PKI_DIR: ${{ runner.temp }}/dev-node-1-pki`, i.e. the collector's
   enrolled mTLS private key, alongside `collector.log` and the dev CA. The
   blast radius on a disposable runner is small and the material is dev-only,
   but a workflow whose entire purpose is proving that secrets do not leak
   should not be the one serving the client key over HTTP, and this file is
   the template later production-path jobs will copy. Serve a dedicated
   directory (`${RUNNER_TEMP}/http-target-root`) holding only `health`.

**Observations, not corrections.** The API-side forbidden-label check
(`{"target", "url", "http.url"} & metric.keys()`) sits inside the identity
match, so a series that fails the identity comparison is never label-checked;
the payload-wide secret and URL scan still covers it, and the storage-side
equivalent is query-pinned, so nothing is currently missed. The target server
is started without a readiness wait, so in principle the collector could
probe before the port is bound — harmless here because every assertion
requires `state="ok"`, and it is not a substitute for correction 2 because it
is a race, not a deterministic path.

**Gates.** I re-ran no CI under this claim. Codex's evidence — actionlint,
integration run `30388588665`, CodeQL `30388589523` at `fec75f1` — is
consistent with the diff and I do not dispute it. None of it contradicts the
three findings: correction 1 describes a path only a transient API error
reaches, and corrections 2 and 3 describe assertions and exposure that a
passing run does not exercise.

### C1-02 — CI/CD checkpoint

- **Issue:** [#48](https://github.com/Xore/SENTINEL/issues/48) — what is still
  open (binary artifacts, the unexecuted tag path, canary and rollback). The
  list below is the record of what has already landed and passed.
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

> **Superseded 2026-07-30 by A-S2-02-3.** The last clause no longer holds for
> S2-02: the user explicitly authorized Sonnet 5 to close it after taking the
> outstanding corrections over from an idle Codex claim. The rule itself stands
> for every other item — this is a named exception, not a precedent.

---

## Archive Procedure

When an item becomes `DONE`, the reviewer:

1. appends assignment, claim, handoff, review, results, decisions, and SHAs to
   `docs/archive/coordination/YYYY-MM-agent.md`;
2. removes its active claim and detailed exchange here;
3. **moves the documents that item consumed and fully discharged** into
   `docs/archive/`, updating every inbound link in the same commit (see the
   qualification test below);
4. updates the completed reference;
5. commits and pushes archive plus compact ledger together;
6. fetches and reads both files back from `origin/main`.

### Which documents move (user instruction, 2026-07-30)

The standing instruction is to keep `docs/` lean by archiving the documents a
finished task referenced. The qualification test is **discharge, not mention**:

- A document moves when every action it prescribes is complete and nothing
  live still depends on it — a task record, a closed research note, a
  superseded design.
- A document stays when it retains an open action item, an unticked exit
  criterion, or an unresolved question, *even if the task that cited it is
  `DONE`*. A research note whose implementation shipped but whose validation
  checkbox is still open has not been discharged.
- **Contracts never move while any queued work consumes them.**
  `docs/contracts/**` is implementation authority for future phases;
  `COLLECTOR-UPDATE-MANIFEST-V1.md` is cited by `QUEUED` S5-01 and stays
  active regardless of C5-01 being `DONE`.

Applying the test on 2026-07-30 (A-DOCS-1): **nothing qualifies yet.** Every
work-board item is `REVIEW`, `QUEUED` or `IN_PROGRESS`; the completed items are
already archived; and each of the nine research notes still carries an open
next action. The documents that become archivable the moment their items reach
`DONE`, so the reviewer does not have to re-derive the list:

| When this is `DONE` | Move |
|---|---|
| ~~S2-02~~ (`DONE` 2026-07-30) | `research-notes/01-baseline-parity.md` — **re-applied and it still does not qualify**: the note's `±1 sample` box against the standalone monitor's `ping_samples` is unticked and needs live network access, so the note keeps an open next action and stays put. Nothing else was gated on S2-02 alone. |
| ~~S3-01A~~ (`DONE` 2026-07-30) + S3-01B | the OS-health portion of `research-notes/02-routes-wan-os-tls-snmp.md`; the rest stays until routes/WAN/TLS/SNMP ship. **Re-applied: does not qualify** — this row needs *both*, and S3-01B has not started. |
| ~~S4-01A~~ (`DONE` 2026-07-30) + S4-01B | `research-notes/09-sqlite-tsdb.md`. **Re-applied: does not qualify** — same reason; S4-01B has not started. |
| S5-01 | the S5 gate section here; **not** `contracts/COLLECTOR-UPDATE-MANIFEST-V1.md` |
| C1-02 | the C1 exchanges here |

~~`SONNET-5-WORK-QUEUE.md` moves only when S2-02, S3-01A and S4-01A are all
`DONE` — it is still the cited authority for two items in `REVIEW`.~~
**Discharged and moved 2026-07-30T16:39Z (A-ARCHIVE-1).** S2-02 reached `DONE`
that day (A-S2-02-3) and S3-01A and S4-01A followed
(A-REVIEW-S3-01A/S4-01A), so the condition was met. The document defines
exactly five items — S2-01, S2-02, S3-01A, S4-01A, S5-00 — and every one is
`DONE`, so it is fully discharged and now lives at
[`archive/coordination/SONNET-5-WORK-QUEUE.md`](../archive/coordination/SONNET-5-WORK-QUEUE.md).
It never contained an S5-01 spec; that lives in the S5-01 Gate section here,
which is why archiving it strands nothing.

Git history is the lossless source for verbose earlier ledger states. Monthly
history is the readable durable index.
