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
| S2-02 | 2 | Core network probe activation and hardening | CODEX | REVIEW | S2-01 DONE | Sonnet review below: not approved, 3 corrections |
| S3-01A | 3 | Linux host-health new-file foundation | SONNET5 | REVIEW | S2-02 REVIEW | corrections handed off at `e81cdaf`; needs Ubuntu gates |
| S4-01A | 4 | Envelope and SQLite cold queue foundation | SONNET5 | REVIEW | S3-01A REVIEW | correction handoff below; commit `0dc7f5d` |
| S3-01B | 3 | Host-health metrics and runtime integration | CODEX | QUEUED | S2-02 DONE, S3-01A DONE | forward package below |
| S4-01B | 4 | Durable export spool and replay integration | CODEX | QUEUED | S2-02 DONE, S4-01A DONE | forward package below |
| S5-01 | 5 | Signed updater verifier and installer foundation | SONNET5 | QUEUED | S2-02, S3-01A, S4-01A DONE; C5-01 DONE | exact scope in S5-01 gate |
| C1-02 | 1–13 | GitHub Actions CI/CD foundations | CODEX | IN_PROGRESS | C0-02 | `.github/**`, CI-only build/validation files |
| C2-03 | 2 | Live probe metric workflow assertion | CODEX | REVIEW | S2-02 REVIEW | Sonnet review below: not approved, 3 corrections |

Completed: C0-01, C0-02, S0-01, S1-01, S1-02, S2-01, S5-00, C1-01, C1-03, C1-04, C2-01, C2-02, C5-01. See
[July 2026 history](../archive/coordination/2026-07-agent.md).
Detailed Sonnet follow-on scopes and gates are in
[`SONNET-5-WORK-QUEUE.md`](SONNET-5-WORK-QUEUE.md).

---

## File Claims

| Timestamp (UTC) | Agent | Work ID | Files/directories |
|---|---|---|---|
| 2026-07-28T18:37:31Z | CODEX | S3-01A | focused CI correction only: `collector/checks/host_load.py`, `collector/tests/checks/test_host_cpu.py`, `collector/tests/checks/test_host_memory.py`, `collector/tests/checks/test_host_load.py`, `collector/tests/checks/test_host_network.py`, `collector/tests/checks/test_host_process.py`, `collector/tests/checks/test_host_service.py`, this ledger |
| 2026-07-28T18:37:31Z | CODEX | C2-03 | timing correction only: `.github/workflows/integration-test.yml`, this ledger |
| 2026-07-28T18:00:46Z | CODEX | C2-03 | `.github/workflows/integration-test.yml`, this ledger |
| 2026-07-26T09:26:06Z | CODEX | C1-02 | `.github/**`, CI-only build/validation files, this ledger |
| 2026-07-28T17:42:13Z | CODEX | S2-02 | takeover of Sonnet's frozen exact claim: `collector/checks/net_icmp.py`, `collector/checks/net_tcp.py`, `collector/checks/net_http.py`, `collector/checks/net_dns.py`, `collector/checks/net_latency.py`, `collector/checks/__init__.py`, `collector/config.py` (network + latency target sections only), `collector/__main__.py` (check-registration wiring only), `collector/tests/checks/test_net_icmp.py`, `collector/tests/checks/test_net_tcp.py`, `collector/tests/checks/test_net_http.py`, `collector/tests/checks/test_net_dns.py`, `collector/tests/checks/test_net_latency.py`, `collector/tests/checks/test_base.py`, `collector/tests/test_config.py` (target-validation portions only), `collector/tests/test_main.py` (registration portions only), this ledger |
| 2026-07-30T11:00:07Z | SONNET5 | S3-01A | corrections to Codex design review 1 only: `collector/checks/host_cpu.py`, `collector/checks/host_memory.py`, `collector/checks/host_disk.py`, `collector/checks/host_load.py`, `collector/checks/host_network.py`, `collector/checks/host_process.py`, `collector/checks/host_service.py`, `collector/tests/checks/test_host_cpu.py`, `collector/tests/checks/test_host_memory.py`, `collector/tests/checks/test_host_disk.py`, `collector/tests/checks/test_host_load.py`, `collector/tests/checks/test_host_network.py`, `collector/tests/checks/test_host_process.py`, `collector/tests/checks/test_host_service.py`, this ledger |
| 2026-07-26T14:10:00Z | SONNET5 | S3-01A | superseded by the correction row above; original new-file claim: `collector/checks/host_cpu.py`, `collector/checks/host_memory.py`, `collector/checks/host_disk.py`, `collector/checks/host_load.py`, `collector/checks/host_network.py`, `collector/checks/host_process.py`, `collector/checks/host_service.py`, `collector/tests/checks/test_host_cpu.py`, `collector/tests/checks/test_host_memory.py`, `collector/tests/checks/test_host_disk.py`, `collector/tests/checks/test_host_load.py`, `collector/tests/checks/test_host_network.py`, `collector/tests/checks/test_host_process.py`, `collector/tests/checks/test_host_service.py`, this ledger |
| 2026-07-30T13:36:40Z | SONNET5 | GATES-S3-01A/S4-01A | ledger-only in this repo: this ledger. Also claims exclusive use of the shared Ubuntu gate host `.33` (`/home/adminuser/analyseLaptop`) until released, because running exact-commit gates there detaches its working copy. The host is returned to `main` before the claim closes. |
| 2026-07-30T11:41:18Z | SONNET5 | REVIEW-S2-02/C2-03 | ledger-only: this ledger. Read-only inspection of `4e18ad8..0e254b0` (S2-02) and `278e49f..dc571f8` + the workflow portion of `21502d9..fec75f1` (C2-03). No implementation file is edited under this claim. |
| 2026-07-30T11:19:04Z | SONNET5 | S4-01A | corrections to Codex review 1 only: `collector/store/__init__.py`, `collector/store/envelope.py`, `collector/store/sqlite_queue.py`, `collector/tests/store/test_envelope.py`, `collector/tests/store/test_sqlite_queue.py`, this ledger |
| 2026-07-26T15:05:00Z | SONNET5 | S4-01A | superseded by the correction row above; original new-file claim: `collector/store/__init__.py`, `collector/store/envelope.py`, `collector/store/sqlite_queue.py`, `collector/tests/store/__init__.py`, `collector/tests/store/test_envelope.py`, `collector/tests/store/test_sqlite_queue.py`, this ledger |


---

## Next Sonnet Actions

Plan updated after the user assigned S2-02 corrections to Codex while Sonnet is
unavailable. Sonnet must keep every S2-02 file frozen until Codex publishes a
new REVIEW handoff.

0. **Status (2026-07-30):** both Sonnet correction items are handed off and
   awaiting a non-Sonnet review.
   - S3-01A — four review-1 groups done at `e81cdaf` (A-S3-01A-2 below); now
     `REVIEW`, needing only Ubuntu gate evidence plus review. `fec75f1`'s S3
     host portion was independently verified in that handoff, which also fixed
     the `host_load` catch-narrowing defect it introduced.
   - S4-01A — six review-1 groups done at `0dc7f5d` (A-S4-01A-2 below); now
     `REVIEW`, needing only Ubuntu gate evidence plus review. One deliberate
     deviation from the claimed plan is flagged in that handoff (group 5), and
     Q-14 records the lease question it raised.
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
   - S5-01 stays `QUEUED`: it gates on S2-02, S3-01A, and S4-01A all being
     `DONE`, and only Codex may mark them so.
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

S5-00 and C5-01 are `DONE`. The release-side authority is
[`COLLECTOR-UPDATE-MANIFEST-V1.md`](../contracts/COLLECTOR-UPDATE-MANIFEST-V1.md);
cross-language golden inputs are under
`backend/api/internal/updatemanifest/testdata/`. The approved preflight,
resolved Q-6 through Q-11 decisions, and exact future claim are indexed in
[July 2026 history](../archive/coordination/2026-07-agent.md).

S5-01 remains `QUEUED` until S2-02, S3-01A, and S4-01A are all `DONE`. Its later
claim may enumerate only: new `collector/updater/` modules; matching new
`collector/tests/updater/` tests; the three named collector/updater systemd
unit/timer files under `deploy/systemd/`; and this ledger. It must consume the
contract and fixtures without changing release-side schema, signing CLI,
workflows, backend runtime, or earlier collector scopes.

---

## Open Questions

### Q-12 — Home for the shared bounded-identifier validator (Sonnet 5, 2026-07-30)

S3-01A's corrections need a DNS-label-style `target_id` validator and bounded
interface/name validation in three host modules, but both natural homes are
frozen: `collector/config.py` and `collector/checks/__init__.py` are inside the
active S2-02 claim. Following S4-01A's precedent for `envelope.py`, the
correction duplicates a module-private validator rather than importing a
private symbol across a frozen claim boundary. Proposal for S3-01B, which owns
config and registration: consolidate one shared validator (config-level for
configured values, `checks/__init__.py` for construction-time assertions) and
delete the duplicates. Codex decision requested; not blocking the correction.

### Q-13 — Bounded label for a multi-mount disk family (Sonnet 5, 2026-07-30)

`host_disk` emits no label today, so a second configured mount would be
indistinguishable, and a raw mount path is a forbidden label. `METRICS.md` has
no host families yet. Proposal: give the disk family an operator-assigned
`target_id` when S3-01B defines the host metric contract, rather than deriving
a label from the path. Out of this correction's scope; recorded so the choice
is not made silently.

### Q-14 — Should the cold queue offer a delivery lease? (Sonnet 5, 2026-07-30)

`SqliteQueue.peek()` returns rows without claiming them, so two concurrent
senders can observe and transmit the same envelope before either acknowledges
it. That is consistent with at-least-once delivery and leaves dedup to the
receiver, and S4-01A's concurrency tests now state it explicitly rather than
papering over it. If the export path is instead expected to guarantee
single-flight per envelope, the queue needs a lease (`leased_until`,
`lease_owner`, expiry sweep), which is a contract-level addition rather than a
review correction. Codex decision requested before S4-01B builds the replay
integration on top of this API.

---

## Forward Probe Packages

### S3-01B — Host-health metrics and runtime integration

After S2-02 and S3-01A are independently `DONE`, publish an exact claim for the
Phase 3 metrics contract, bounded host-check configuration, registration and
lifecycle wiring, the seven host modules only where reviewed adapter changes
are required, and focused tests. Define canonical `sentinel_` metric names,
types, units, and cardinality budgets before emission. Process and service
families use validated `target_id`; interface identifiers are bounded; raw
process/service/path values never become labels. Prove disabled families are
not constructed, first-sample baselines emit nothing misleading, instruments
are reused, and Windows degrades only for genuinely unsupported checks.

### S4-01B — Durable export spool and replay integration

After S2-02 and S4-01A are independently `DONE`, publish an exact claim for an
async adapter around the reviewed SQLite queue, transport integration,
configuration, runtime wiring, canonical queue telemetry, and focused tests.
Failed exports must be durably enqueued before acknowledgement; reconnect
drains deterministic oldest-first batches with bounded exponential backoff and
jitter; duplicates remain idempotent; poison/corrupt/expired records cannot
wedge replay; blocking SQLite work never runs on the event loop; cancellation
and shutdown leave no task or envelope in an ambiguous state. Enforce the
24-hour/200-MB bounds and test restart, outage, recovery, concurrent enqueue/
drain, redaction, and live backend replay.

Both packages are deliberately queued behind their reviewed foundations. Their
future claims must not overlap Sonnet's correction scopes or silently modify
contracts outside the enumerated files.

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
  scheduler, probe, or entry-point edits, per
  `SONNET-5-WORK-QUEUE.md`'s S4-01A spec.
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

- **Timestamp:** 2026-07-30T13:36:40Z.
- **Status:** IN_PROGRESS.
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

### C2-03 — Live probe metric workflow assertion

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

---

## Archive Procedure

When an item becomes `DONE`, the reviewer:

1. appends assignment, claim, handoff, review, results, decisions, and SHAs to
   `docs/archive/coordination/YYYY-MM-agent.md`;
2. removes its active claim and detailed exchange here;
3. updates the completed reference;
4. commits and pushes archive plus compact ledger together;
5. fetches and reads both files back from `origin/main`.

Git history is the lossless source for verbose earlier ledger states. Monthly
history is the readable durable index.
