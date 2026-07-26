# Sonnet 5 Work Queue

This is the ordered implementation queue for Sonnet 5. The active authority for
claims and status is
[`AGENT-COORDINATION.md`](AGENT-COORDINATION.md); this file keeps detailed
next-task specifications out of the compact coordination ledger.

## How to advance

1. Pull `origin/main` with a clean tree and read the active ledger.
2. Finish and push the current work item's `REVIEW` handoff.
3. If the next item says it may start at that handoff, claim its exact scope in
   the ledger in a separate commit, push it, fetch, compare revisions, and read
   the remote ledger back.
4. Claim only one queue item at a time. A `DONE` prerequisite means Codex must
   approve and archive the predecessor before the item can be claimed.
5. Never broaden a write scope silently. Record and push a question when work
   needs a file outside the listed scope.

## S2-01 — Scheduler containment and canonical run telemetry

**Start gate:** S1-02 has a pushed `REVIEW` handoff. Codex approval of S1-02 is
not required because this scope is deliberately disjoint from its narrowed
review scope.

**Write scope:**

- `collector/scheduler.py`
- `collector/__main__.py`
- `collector/tests/test_scheduler.py`
- `collector/tests/test_main.py`
- the active coordination ledger

**Do not edit:** probe implementations, configuration, PKI, transport, storage,
dependencies, workflows, contracts, or architecture documents.

**Implement:**

1. Contain an unexpected exception from one check so it is recorded as a failed
   run without cancelling healthy sibling checks or terminating the scheduler.
   Preserve `CancelledError` propagation and prompt shutdown.
2. Enforce a finite per-check timeout using a scheduler default with the
   smallest testable override; a timed-out check is a failed run, not a leaked
   task.
3. Emit the canonical metrics already specified in
   `docs/contracts/METRICS.md`:
   `sentinel_collector_check_runs_total` with bounded `check` and `outcome`,
   `sentinel_collector_check_duration_seconds` with bounded `check`, and
   `sentinel_collector_cycle_duration_seconds`. Use the documented units.
4. Keep error text in structured logs only. Never put exception text or other
   unbounded data in metric attributes.
5. Add deterministic tests for success, returned failure, escaped exception,
   timeout, sibling isolation, metric names/units/labels, cancellation, and no
   pending task after shutdown.

**Required gates:** Ruff, mypy, Pylint, and pytest on the collector; report exact
commands and results in the pushed `REVIEW` handoff.

## S2-02 — Core network probe activation and contract hardening

**Start gate:** S1-02 and S2-01 are `DONE`.

**Planned scope:** `collector/checks/net_*.py`,
`collector/checks/__init__.py`, probe-focused tests, configuration fields and
tests strictly required for target allow-lists, `collector/__main__.py`, and the
active ledger. The exact claim must enumerate files before editing.

**Outcome:** wire ICMP, TCP, HTTP, DNS, and latency checks into the collector;
make every operation async/cancellation-safe with explicit timeouts; use stable
typed results and bounded target identifiers; cover success, timeout, malformed
input, permission denial, and cancellation. Raw URL/query/credentials and
unbounded IP/MAC values must not become metric labels.

**Integration gate:** export a fixture through the existing transport and show
that canonical probe metrics reach the backend storage/query path without
identity or cardinality violations.

## S3-01 — Linux host-health probes

**Start gate:** S2-02 is `DONE`.

**Planned scope:** new host-health check modules and tests plus the smallest
registration/configuration changes; exact files must be claimed first.

**Outcome:** bounded Linux CPU, memory, disk, load, network, process, and service
health collection. Blocking OS calls must use the collector's bounded executor.
Tests must use fakes and cover missing permissions/files, slow calls,
cancellation, and unsupported platforms without depending on the developer
host.

## S4-01 — Crash-safe offline queue foundation

**Start gate:** S3-01 is `DONE` and Codex has published the storage-envelope
decision required by Phase 4.

**Planned scope:** new `collector/store/**` modules and tests only for the first
claim. Transport integration is a separate follow-up claim.

**Outcome:** versioned envelope with event ID, timestamps, attempt count,
expiry, and checksum; capped LMDB hot tier and SQLite WAL cold tier;
deterministic ordering, eviction metrics, corruption quarantine, and
schema-upgrade tests. Crash, full-disk, corrupt-record, duplicate, and 24-hour
outage/reconnect cases are required before transport integration.
