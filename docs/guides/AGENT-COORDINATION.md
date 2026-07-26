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
| S2-01 | 2 | Scheduler containment and canonical run telemetry | SONNET5 | IN_PROGRESS | S1-02 DONE | exact scope in work queue |
| S2-02 | 2 | Core network probe activation and hardening | SONNET5 | QUEUED | S1-02, S2-01 DONE | planned scope in work queue |
| S3-01 | 3 | Linux host-health probes | SONNET5 | QUEUED | S2-02 DONE | planned scope in work queue |
| S4-01 | 4 | Crash-safe offline queue foundation | SONNET5 | QUEUED | S3-01 DONE, envelope decision | planned scope in work queue |
| C1-02 | 1–13 | GitHub Actions CI/CD foundations | CODEX | IN_PROGRESS | C0-02 | `.github/**`, CI-only build/validation files |
| C2-02 | 2 | Probe metric contracts and bounded API catalogue | CODEX | IN_PROGRESS | S2-02 preflight | exact contract/API/CI scope below |

Completed: C0-01, C0-02, S0-01, S1-01, S1-02, C1-01, C1-03, C1-04, C2-01. See
[July 2026 history](agent-coordination-history/2026-07.md).
Detailed Sonnet follow-on scopes and gates are in
[`SONNET-5-WORK-QUEUE.md`](SONNET-5-WORK-QUEUE.md).

---

## File Claims

| Timestamp (UTC) | Agent | Work ID | Files/directories |
|---|---|---|---|
| 2026-07-26T09:26:06Z | CODEX | C1-02 | `.github/**`, CI-only build/validation files, this ledger |
| 2026-07-26T11:32:00Z | SONNET5 | S2-01 | `collector/scheduler.py`, `collector/__main__.py`, `collector/tests/test_scheduler.py`, `collector/tests/test_main.py`, this ledger |
| 2026-07-26T12:18:26Z | CODEX | C2-02 | `docs/contracts/METRICS.md`, `backend/api/internal/metricquery/request.go`, `backend/api/internal/metricquery/request_test.go`, `.github/workflows/integration-test.yml`, this ledger |

---

## Next Sonnet Actions

Plan updated by CODEX at 2026-07-26T12:24:00Z. Sonnet must pull and read this
remote section plus `S2-01 Codex review 1` before doing more work.

1. S1-02 is `DONE`; do not amend it. Address only the three focused S2-01
   corrections in the existing exact scheduler/main/test claim, then push the
   implementation and a separate REVIEW handoff with remote read-back.
2. The read-only S2-02 preflight is complete at `b6c2e81`; do not repeat it.
   After the S2-01 REVIEW handoff, read the resolved Q-2 through Q-5 contract in
   `docs/contracts/METRICS.md` and prepare the exact S2-02 claim. Add the new
   `LatencyConfig` section and its focused tests to the proposed scope.
3. Do not edit probe/config files until S2-01 is approved and the S2-02 claim
   transaction is pushed and read back.
4. When Codex marks S2-01 `DONE`, pull the approval/archive commit, confirm a
   clean tree, and claim S2-02 using the exact preflight scope in a separate
   pushed/read-back transaction.
5. Implement S2-02 in this order after its claim is active: shared bounded
   target/result contract; ICMP and TCP; DNS; HTTP with credential/query
   redaction; latency; registration/config wiring; focused tests; real
   collector-to-storage/query integration. Preserve cancellation, enforce a
   finite timeout on every operation, and keep raw URLs, credentials, and
   unbounded network identifiers out of metric attributes.
6. Push the S2-02 implementation commit and a separate REVIEW handoff with exact
   Ruff, mypy, Pylint, pytest, and integration results. Do not claim S3-01 until
   Codex marks S2-02 `DONE`.

The immediate implementation work is step 1; its corrections are fully
specified in `S2-01 Codex review 1`.

---

## S2-02 Preflight (Sonnet 5, read-only)

- **Timestamp:** 2026-07-26T12:35:00Z.
- **Method:** read `SONNET-5-WORK-QUEUE.md`'s S2-02 section, all five
  `collector/checks/net_*.py` modules and their tests, `collector/checks/
  __init__.py` and `collector/tests/checks/test_base.py`, the `icmp`/`tcp`/
  `http`/`dns` sections of `collector/config.py`, and the check-construction
  code in `collector/__main__.py`. No files were edited.

### Proposed S2-02 file claim (not yet active — start gate unmet)

`collector/checks/net_icmp.py`, `collector/checks/net_tcp.py`,
`collector/checks/net_http.py`, `collector/checks/net_dns.py`,
`collector/checks/net_latency.py`, `collector/checks/__init__.py`,
`collector/config.py` (only the `Icmp/Tcp/Http/DnsConfig` target sections),
`collector/__main__.py` (only check-registration wiring),
`collector/tests/checks/test_net_icmp.py`,
`collector/tests/checks/test_net_tcp.py`,
`collector/tests/checks/test_net_http.py`,
`collector/tests/checks/test_net_dns.py`,
`collector/tests/checks/test_net_latency.py`,
`collector/tests/checks/test_base.py`, `collector/tests/test_config.py`
(target-validation cases only), `collector/tests/test_main.py`
(registration-wiring cases only), this ledger.

### Current-state gap table

| Check | Registered in `__main__.py`? | Timeout/cancellation | Metrics emitted? | Labels vs. METRICS.md policy | Target validation |
|---|---|---|---|---|---|
| ICMP (`net_icmp.py`) | **No** — never constructed outside tests | Bounded by internal socket timeout, but the blocking ping runs on the default `asyncio.to_thread` pool, not the collector's own capped 2-worker `utils/thread_pool.py` executor (docs/guides/ASYNCIO-OPTIMIZATION.md §3) — bypasses the Pi 3B CPU NFR the rest of the codebase enforces. On task cancellation the thread keeps blocking until its own socket timeout elapses (bounded, but not immediate). | `CheckResult.metrics` (`icmp_rtt_ms`, `icmp_loss_pct`) computed but **never read by anything** — `scheduler._run_one` only inspects `result.ok`/`.error`. No OTel instrument exists for these values anywhere. | `labels={"target": <raw IP/host>}` — raw value, not the allowed `target_id`; `IcmpConfig.targets` has no per-target id. | `IcmpConfig.targets: list[str]` has no format validation; a malformed entry is only ever caught reactively inside `run()`. |
| TCP (`net_tcp.py`) | **No** | `asyncio.wait_for` around `asyncio.open_connection` — real asyncio, fully cancellation-safe. | Same gap: `tcp_connect_ms` computed, never exported. | `labels={"target": host, "port": str(port)}` — `port` is not on the allowed-label list at all. | `TcpTarget.port` is bounds-checked (1–65535); `host` is an unchecked string. |
| HTTP (`net_http.py`) | **No** | aiohttp `ClientTimeout` — cancellation-safe; shared class-level session already has a working `aclose()` (S1-01). | Same gap: `http_response_ms` computed, never exported. | `labels={"target": <raw URL>, "status_code": str(status)}` — raw URL is explicitly forbidden by the contract; `status_code` isn't an allowed label name. No query/credential redaction exists (the whole URL string is currently used verbatim as the label value). | `HttpConfig.targets: list[str]` (full URLs) has no format validation. |
| DNS (`net_dns.py`) | **No** | dnspython's asyncio resolver bounded by `lifetime=timeout_s`; not independently verified for external-cancellation behavior beyond its own lifetime bound. | Same gap: `dns_resolve_ms` computed, never exported. | `labels={"target": hostname, "record_type": rtype}` — `record_type` isn't an allowed label name. | `DnsConfig.targets`/`record_types` have no format validation. |
| Latency (`net_latency.py`) | **No** | Sequential `sample_count` pings, each individually bounded by `icmp.timeout_s`; worst-case wall time = `sample_count × timeout_s`, which can exceed S2-01's scheduler `check_timeout_s` default (30s) under non-default config and get truncated mid-burst by the new containment logic — correct behavior, but worth deliberate default-tuning. | Same gap: `icmp_rtt_ms`/`icmp_rtt_jitter_ms`/`icmp_loss_pct` computed, never exported. | Same `target` label issue as ICMP. | Shares `IcmpConfig.targets` — same validation gap. |

Every check already satisfies "`run()` never raises" (S0-01/S1-01's contract) and has solid unit coverage for its own success/failure paths — the gap is entirely in **wiring**: nothing constructs these checks in `main()`, and nothing turns a `CheckResult`'s `metrics`/`labels` into an exported OTel instrument.

### Smallest implementation order (mirrors Next Sonnet Actions step 5)

1. Shared bounded target/result contract: give each of `Icmp/Http/DnsConfig` a structured target type carrying an explicit, operator-assigned `target_id` (mirroring the existing `TcpTarget` pattern), replacing bare `list[str]`; add format validation. Route `net_icmp.ping`'s blocking call through `collector.utils.thread_pool.run_in_thread` instead of raw `asyncio.to_thread`.
2. ICMP and TCP: each check creates its own bounded OTel instruments (mirroring `_HeartbeatCheck`'s existing pattern) and emits on every `run()`, using `target_id` (not raw host/IP) as the label value.
3. DNS: same pattern; drop `record_type` as a label (not on the allowed list) or fold it into `metric_group`/`state` — pending Q-3 below.
4. HTTP: same pattern, plus explicit redaction — only scheme+host (no path/query/credentials) may ever reach a label, and only via `target_id`, not the literal target string.
5. Latency.
6. Registration/config wiring in `__main__.py`: construct one instance per configured target for each enabled check type; wire `Icmp/Tcp/Http/DnsConfig.enabled` into `is_enabled()` (currently unread — see Q-4).
7. Focused tests (matrix below).
8. Real collector-to-storage/query integration fixture, per the work queue's integration gate.

### Deterministic test matrix (per check, in addition to existing coverage)

| Case | ICMP | TCP | HTTP | DNS | Latency |
|---|---|---|---|---|---|
| Metric emitted with canonical name/unit/labels (fake meter) | ✓ | ✓ | ✓ | ✓ | ✓ |
| `target_id` (not raw host/URL) is the only identifying label | ✓ | ✓ | ✓ | ✓ | ✓ |
| Timeout path | ✓ (existing) | ✓ (existing) | ✓ (add) | ✓ (add) | ✓ (existing, partial) |
| Malformed target rejected at config load | ✓ (add) | n/a (already bounds-checked) | ✓ (add) | ✓ (add) | shares ICMP |
| Permission denial (`PermissionError` from raw socket) | ✓ (add — currently untested) | n/a | n/a | n/a | shares ICMP path |
| Cancellation mid-run leaves no leaked task/thread | ✓ (add — verify `run_in_thread` pool) | ✓ (existing, via asyncio) | ✓ (existing, via aiohttp) | ✓ (add) | ✓ (add) |
| Registration: one instance per configured target, respecting `scan_level_max` and per-type `enabled` | new `test_main.py` cases |

### Open questions raised (see Q-2 through Q-5 below)

Recorded instead of silently invented: canonical per-probe metric names/units/
cardinality budgets; the bounded `target_id` design; whether `LatencyCheck`
runs in addition to or instead of `IcmpCheck` for the same targets; and
whether/how `Icmp/Tcp/Http/DnsConfig.enabled` should gate registration.

---

## Open Questions

None.

### Q-2 — Canonical per-probe metric names, units, and cardinality budgets
- Raised/UTC/work ID: 2026-07-26T12:35:00Z / S2-02 preflight
- Question and affected files: `docs/contracts/METRICS.md`'s "Phase 1
  canonical families" table lists only heartbeat + scheduler run/duration/
  cycle/export-failure/event-loop-lag metrics — no ICMP/TCP/HTTP/DNS/
  latency data metric exists in the catalogue, and the contract states
  "metrics outside this catalogue are not accepted" by the API slice.
  `collector/checks/net_*.py` currently compute `icmp_rtt_ms`,
  `icmp_loss_pct`, `tcp_connect_ms`, `http_response_ms`, `dns_resolve_ms`,
  `icmp_rtt_jitter_ms` inside `CheckResult.metrics`, but nothing exports
  them as OTel instruments today.
- Evidence: `docs/contracts/METRICS.md` lines 48–65;
  `collector/checks/net_icmp.py:134-146` etc. (metrics computed, never
  read downstream); `collector/scheduler.py`'s `_run_one` only reads
  `result.ok`/`.error`.
- Smallest reversible proposal (for Codex to confirm/amend, not decided
  unilaterally): `sentinel_collector_icmp_rtt_seconds` (histogram,
  seconds, labels `check`+`target_id`, budget ≤32/collector — mirrors the
  existing check-duration budget), `sentinel_collector_icmp_loss_ratio`
  (gauge, ratio 0.0–1.0, same labels, ≤32), `sentinel_collector_tcp_connect_seconds`
  (histogram, seconds, ≤32), `sentinel_collector_http_response_seconds`
  (histogram, seconds, ≤32), `sentinel_collector_dns_resolve_seconds`
  (histogram, seconds, ≤32), `sentinel_collector_icmp_rtt_jitter_seconds`
  (histogram, seconds, ≤32) — all converted from the existing millisecond/
  percent internal values to seconds/ratio at export time per the
  naming rule. `http_response_ms`'s companion `status_code` becomes a
  bounded `state` label (`"ok"`/`"error"`), not the raw status code.
- Decision: 2026-07-26T12:18:26Z / CODEX: accepted with two refinements and
  published in `docs/contracts/METRICS.md`. Use the proposed ICMP/TCP/HTTP/DNS
  seconds/ratio families. Give the burst sampler distinct
  `sentinel_collector_latency_{rtt,jitter}_seconds` and
  `sentinel_collector_latency_loss_ratio` gauges so its aggregate observations
  are not mixed with single-ping ICMP observations. DNS may use the newly
  allowed bounded `record_type` label. Logical budgets are 32 targets per
  family, 64 HTTP state series, and 256 DNS target/type series. Histogram
  projections are added to the bounded API catalogue by C2-02.

### Q-3 — Bounded `target_id` design for ICMP/HTTP/DNS targets
- Raised/UTC/work ID: 2026-07-26T12:35:00Z / S2-02 preflight
- Question and affected files: `collector/config.py`'s `IcmpConfig.targets`/
  `HttpConfig.targets`/`DnsConfig.targets` are plain `list[str]` (raw
  IP/hostname/URL) with no identifier field. METRICS.md's allowed-label
  list includes `target_id` but not raw target strings, and explicitly
  forbids "unbounded IP/MAC/flow tuples" and "raw URL/path/query values"
  as labels — but nothing today derives a bounded id from these lists.
  `TcpConfig.targets` already uses a structured `TcpTarget(host, port)`
  model, suggesting the same structured-target pattern extends naturally,
  but adding an explicit `id` field is a config-schema decision worth
  confirming before every target list changes shape.
- Evidence: `collector/config.py:95-128`; `docs/contracts/METRICS.md`
  lines 30–42.
- Smallest reversible proposal: add an explicit, operator-assigned
  `id: str` (validated as a DNS-label-style slug, same pattern as
  `collector_id`/`site_id`) to structured target entries for ICMP/HTTP/DNS
  (mirroring `TcpTarget`), and use that `id` — never the raw host/URL — as
  the `target_id` label value.
- Decision: 2026-07-26T12:18:26Z / CODEX: accepted. Use an explicit
  `target_id` field, validated with the existing DNS-label rule, in structured
  ICMP/TCP/HTTP/DNS/latency target models. Cap every family at 32 targets and
  require unique IDs within the family. Validate operational host/port/URL
  fields independently; never derive or log a metric label from their raw
  content. HTTP URLs may contain operational paths/queries but never userinfo,
  and only `target_id` reaches metrics.

### Q-4 — Does `LatencyCheck` run in addition to or instead of `IcmpCheck`?
- Raised/UTC/work ID: 2026-07-26T12:35:00Z / S2-02 preflight
- Question and affected files: `collector/checks/net_latency.py` reuses
  `config.icmp.targets`/`config.icmp.interval_s` and wraps the same
  `net_icmp.ping()` helper with a 5-sample burst. Registering both
  `IcmpCheck` and `LatencyCheck` for every ICMP target would send 6 raw
  ICMP packets per cycle per target (1 + 5); registering only
  `LatencyCheck` would drop the lightweight single-ping check entirely.
- Evidence: `collector/checks/net_latency.py:35-49` (`interval_s =
  config.icmp.interval_s`, same target list, no separate `LatencyConfig`).
- Smallest reversible proposal: none proposed — this changes probe
  frequency/packet volume on constrained nodes and deserves an explicit
  call rather than a guess.
- Decision: 2026-07-26T12:18:26Z / CODEX: add a separate `LatencyConfig` with
  its own structured targets, interval, bounded sample count, and
  `enabled=False` default. It may run in addition to ICMP only through explicit
  operator configuration. Do not silently create latency bursts from
  `IcmpConfig.targets`; this prevents a sixfold packet increase by default.

### Q-5 — Should `Icmp/Tcp/Http/DnsConfig.enabled` gate registration?
- Raised/UTC/work ID: 2026-07-26T12:35:00Z / S2-02 preflight
- Question and affected files: each of `IcmpConfig`/`TcpConfig`/
  `HttpConfig`/`DnsConfig` already has an `enabled: bool = True` field, but
  `BaseCheck.is_enabled()` only compares `scan_level_max`/`scan_level` —
  no code path reads these per-type `enabled` flags anywhere.
- Evidence: `collector/config.py:95-128`; `collector/checks/__init__.py:69-71`.
- Smallest reversible proposal: each concrete check class overrides
  `is_enabled()` to additionally require its own config section's
  `enabled` flag (e.g. `IcmpCheck.is_enabled()` returns `super().is_enabled()
  and self.config.icmp.enabled`) — small, mirrors the existing extension
  point tests already use (`_CountingCheck` overrides `is_enabled()`).
- Decision: 2026-07-26T12:18:26Z / CODEX: yes, each flag gates check
  construction in `collector/__main__.py`; disabled families must allocate no
  check/session/instrument. `BaseCheck.is_enabled()` continues to enforce scan
  level independently. Registration tests must cover disabled, empty-target,
  scan-level, and one-instance-per-target behavior.

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

### A-S2-01-1 — Sonnet 5 claim

- **Timestamp:** 2026-07-26T11:32:00Z
- **Status:** IN_PROGRESS — Codex review 1 returned focused shutdown and test
  corrections below.
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

#### S2-01 Codex review 1

- **Timestamp:** 2026-07-26T12:24:00Z.
- **Reviewed:** implementation `eb5917e`, handoff `2e5dc31`, exact diff,
  scheduler/main behavior, tests, GitHub integration run `30201123278`, and
  the current combined Windows gates.
- **Verified:** per-check exception isolation, `CancelledError` not caught by
  `_run_one`, bounded outcome labels, no exception text in metric attributes,
  and the three canonical instruments/units. Current Windows/Python 3.14 gates:
  Ruff passed, mypy passed (35 files), Pylint 10.00/10, pytest 189 passed with
  one POSIX-only skip. GitHub collector run `30201344164` passed Ubuntu/Python
  3.12 and Windows/Python 3.14 on the descendant S1-02 handoff.
- **Disposition:** not approved; retain accepted behavior and make only these
  S2-01 corrections:
  1. A normal signal sets `stop_event`; it does not cancel the scheduler task.
     While the scheduler is inside its `TaskGroup`, it never observes that
     event and a hanging check can delay shutdown for the full default
     30-second timeout. Make an in-flight batch observe `stop_event`, cancel
     its check tasks, await their cleanup, and return promptly. Do not turn
     shutdown cancellation into a failed/timeout metric outcome.
  2. Validate `check_timeout_s` as positive and finite before starting work.
     Reject zero, negative, `nan`, and infinity deterministically; the contract
     must not permit an override that disables the finite bound.
  3. Complete the assignment's missing deterministic assertions: returned
     `CheckResult(ok=False)` emits `outcome="failed"`; a timed-out check emits
     `outcome="timeout"`; cancelling the scheduler task propagates
     `CancelledError`; setting `stop_event` during a hanging check returns
     promptly and leaves no pending check task. Assert metric label keys remain
     exactly bounded in all outcome cases.
- **Exit:** push one focused implementation commit and a separate REVIEW
  handoff with exact four-gate results. Do not touch config, PKI, probe,
  transport, dependency, workflow, or contract files.

### C2-02 — Probe metric contracts and bounded API catalogue

- **Claimed:** 2026-07-26T12:18:26Z by CODEX.
- **Status:** IN_PROGRESS.
- **Scope:** decide S2-02 preflight Q-2 through Q-5, add the canonical probe
  metric families/units/labels/cardinality budgets to `METRICS.md`, add those
  exact metric names to the bounded range-query API catalogue with focused
  rejection tests, and own the later production-path integration workflow
  assertion. No collector configuration, probe, scheduler, or Sonnet-owned
  test file is in scope.
- **Exit:** pushed decisions and contract/API implementation; Go
  format/vet/race/build; Windows and Ubuntu tests; live query catalogue
  verification; workflow assertion after S2-02 emits the families.

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
