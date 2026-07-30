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

## Low-Codex continuity window — through 2026-08-02

Codex review capacity is limited until August 2. During this window, a pushed
`REVIEW` handoff may unlock the next item only where this queue explicitly says
so and the next scope is disjoint. The handed-off files become frozen: later
items must not edit them until Codex reviews them. Only Codex may change an item
to `DONE`.

Continuity order:

1. finish the focused S2-01 review corrections;
2. after its corrected REVIEW handoff, claim and implement S2-02;
3. after the S2-02 REVIEW handoff, claim S3-01A's new-file-only host-health
   foundation;
4. after S3-01A REVIEW, claim S4-01A's new-file-only SQLite queue foundation;
5. publish S5-00's read-only signed-update preflight, then stop and wait for
   Codex review.

Every transition still requires a separate claim commit, push, fetch, revision
comparison, and remote ledger read-back. A later task may not fix a frozen
predecessor file; record a question instead.

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

**Start gate:** S1-02 is `DONE` and S2-01 has a pushed corrected `REVIEW`
handoff addressing Codex review 1. S2-01 files become frozen at handoff.

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

## S3-01A — Linux host-health module foundation

**Start gate:** S2-02 has a pushed `REVIEW` handoff. All S2-02 files are frozen.

**Exact claim scope:** new files only:
`collector/checks/host_cpu.py`, `collector/checks/host_memory.py`,
`collector/checks/host_disk.py`, `collector/checks/host_load.py`,
`collector/checks/host_network.py`, `collector/checks/host_process.py`,
`collector/checks/host_service.py`, and seven matching explicitly enumerated
test files under `collector/tests/checks/`, plus the active ledger. Do not edit
config, entry-point, check registry, dependencies, contracts, workflows, or
frozen S2 files.

**Outcome:** independently testable Linux CPU, memory, disk, load, network,
process, and service check modules using stable typed results and bounded
labels already allowed by `METRICS.md`. Blocking filesystem/process calls use
the collector's bounded executor. Registration and OTel instruments are a later
Codex-reviewed claim.

**Required tests:** faked `/proc`/filesystem/subprocess inputs; success;
malformed/missing files; permission denial; slow call; cancellation; bounded
process/service allow-lists; unsupported Windows behavior; no developer-host
dependency. Run and report all four collector gates.

## S4-01A — Crash-safe envelope and SQLite cold queue

**Start gate:** S3-01A has a pushed `REVIEW` handoff. Its files are frozen.

**Exact claim scope:** new files only:
`collector/store/__init__.py`, `collector/store/envelope.py`,
`collector/store/sqlite_queue.py`, `collector/tests/store/__init__.py`,
`collector/tests/store/test_envelope.py`,
`collector/tests/store/test_sqlite_queue.py`, and the active ledger. No
dependency, config, transport, scheduler, probe, or entry-point edits.

**Published envelope decision:** immutable version `1`; `event_id`, `site_id`,
`collector_id`, `observed_at`, `created_at`, `expires_at`, `attempt_count`,
`content_type`, payload bytes, and SHA-256 checksum. IDs use existing bounded
identity rules; timestamps are aware UTC; attempt count is non-negative;
expiry follows observation/creation; checksum is verified before delivery.
Serialization is deterministic and rejects unknown versions.

**Outcome:** stdlib SQLite WAL cold queue with explicit transactions, busy
timeout, deterministic `(created_at,event_id)` ordering, duplicate idempotency,
attempt increment, acknowledge, expiry removal, byte/record caps, oldest-first
eviction, and corruption quarantine. Constructor arguments provide all caps.
LMDB hot tier, configuration, and transport integration are later claims.

**Required tests:** round-trip/determinism, checksum corruption, unknown
version, duplicate, crash/reopen durability, concurrent producer/consumer,
busy/locked database, cap eviction, expiry, retry order, acknowledgement, and
simulated 24-hour backlog drain. Run all four collector gates.

## S5-00 — Signed-update read-only preflight

**Start gate:** S4-01A has a pushed `REVIEW` handoff.

**Write scope:** active coordination ledger only. Read ADR 0006, architecture,
current packaging/release workflows, and collector startup/install paths.

**Outcome:** publish an exact future file claim, trust-root/key-rotation model,
manifest schema, rollback/anti-downgrade rules, atomic install/recovery flow,
platform matrix, failure-injection tests, and open decisions. Do not implement
or edit workflows. Push and read back the preflight, then stop for Codex.
