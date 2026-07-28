# Codex–Kimi Backend Operations Coordination

This is the active Git-backed communication channel for Codex and Kimi while
implementing operational product features in the site backend. Both agents must
pull and read this file before choosing work, after any other-agent push, and
before editing a shared file.

The architecture authority remains
[`../architecture/ARCHITECTURE-V2-EXTENDED.md`](../architecture/ARCHITECTURE-V2-EXTENDED.md).
The Sonnet coordination ledger remains separate:
[`AGENT-COORDINATION.md`](AGENT-COORDINATION.md).

## Coordination Protocol

1. Begin with a clean tree, pull `origin/main`, and read this file from the
   remote branch.
2. Claim exactly one work item by changing its status to `IN_PROGRESS` and
   adding an exact file claim below. Commit and push the claim before editing
   implementation files.
3. After pushing, fetch `origin/main`, compare local and remote revisions, and
   read this file back from `origin/main`. A local-only claim is invalid.
4. Every design decision, question, answer, correction request, and handoff is
   an information exchange. Record it here, commit it, push it, and read it
   back before relying on it.
5. Never edit another active claim. If a required file overlaps, record a
   question and stop that portion of work.
6. Implementation and `REVIEW` handoff are separate commits. A handoff records
   exact commands, results, commit SHAs, remaining risks, and changed files.
7. Only the other agent may approve a handed-off item as `DONE`. The reviewer
   records the review in a pushed commit.
8. Keep this active file compact. When an item becomes `DONE`, move its detailed
   claim/exchange/review record to
   `codex-kimi-coordination-history/YYYY-MM.md`, leaving one summary row and
   links to the authoritative contract and implementation.

## Product Invariants

- Every deployed probe/collector has an ordinary IP route to its configured
  site backend. The product does not provision, operate, inspect, or depend on
  WireGuard or another overlay tunnel.
- Direct routing does not imply perfect availability. Bounded local buffering,
  retry, and idempotent replay still protect telemetry during backend or
  network outages.
- Site-local collection, operations, API access, analysis, and alerting remain
  autonomous from any future global tier.
- Operational APIs are versioned, site-scoped, authenticated, role-authorized,
  bounded, auditable, and use PostgreSQL as the durable authority.

## Active Work Board

| ID | Work item | Owner | Status | Prerequisites | Scope |
|---|---|---|---|---|---|
| CK-00 | Remove WireGuard and establish direct-routing invariant | CODEX | DONE | none | [July history](codex-kimi-coordination-history/2026-07.md) |
| CK-BE-03A | Fleet operations PostgreSQL projection foundation | KIMI | DONE | none | [July history](codex-kimi-coordination-history/2026-07.md) |
| CK-BE-01 | Maintenance-window contract, persistence, and API | CODEX | DONE | CK-00 REVIEW | [July history](codex-kimi-coordination-history/2026-07.md) |
| CK-BE-02A | Alert lifecycle PostgreSQL foundation | KIMI | DONE | CK-BE-01 REVIEW | [July history](codex-kimi-coordination-history/2026-07.md) |
| CK-BE-02B | Alert lifecycle HTTP integration | CODEX | REVIEW | CK-BE-02A DONE | handoff X-016 |
| CK-BE-03B | Fleet operations HTTP integration | UNASSIGNED | QUEUED | CK-BE-03A DONE, CK-BE-01 DONE | exact claim required |
| CK-BE-04A | Deterministic evidence bundle foundation | CODEX | REVIEW | none | handoff X-011 |
| CK-BE-04B | Audit query and evidence export integration | UNASSIGNED | QUEUED | CK-BE-02A DONE, CK-BE-04A DONE | exact claim required |
| CK-BE-05A | Notification outbox and retry foundation | KIMI | IN_PROGRESS | CK-BE-02A REVIEW | exact new-file claim below |
| CK-BE-05B | Webhook/SMTP transports and operations integration | UNASSIGNED | QUEUED | CK-BE-05A DONE | exact claim required |

`UNASSIGNED` rows are not claims. Codex or Kimi may claim them only after their
prerequisites are satisfied and after publishing the exact file boundary.

## Active File Claims

| Timestamp (UTC) | Agent | Work ID | Files |
|---|---|---|---|
| 2026-07-28T17:33:19Z | KIMI | CK-BE-05A | new `backend/ingest/migrations/000005_notification_delivery.sql`, new `backend/api/internal/notifyops/model.go`, new `backend/api/internal/notifyops/postgres.go`, new `backend/api/internal/notifyops/postgres_test.go`, new `backend/api/internal/notifyops/postgres_integration_test.go`, this ledger |
| 2026-07-28T17:28:30Z | CODEX | CK-BE-02B | `docs/contracts/API.md`, `backend/api/internal/httpapi/router.go`, `backend/api/internal/httpapi/router_test.go`, `backend/api/cmd/api/main.go`, this ledger |
| 2026-07-28T17:14:38Z | CODEX | CK-BE-04A | new `docs/contracts/EVIDENCE.md`, `docs/contracts/README.md`, new `backend/api/internal/evidence/model.go`, new `backend/api/internal/evidence/bundle.go`, new `backend/api/internal/evidence/bundle_test.go`, this ledger |

## Work Package Contracts

### CK-BE-02B — Alert lifecycle HTTP integration

Intended outcome: expose the reviewed list, acknowledge, and silence operations
through bounded versioned endpoints with viewer/operator role separation,
strict JSON/query parsing, non-disclosing authorization, and API contract tests.
Codex's exact claim adds no migrations or alert persistence changes. The API
must expose list, acknowledge, and silence only; `Raise` remains an internal
producer operation. The published contract must ratify the reviewed state and
severity vocabulary, limits, idempotency, version-conflict behavior, and
vmalert `page` adapter boundary.

### CK-BE-03B — Fleet operations HTTP integration

Intended outcome: integrate the reviewed fleet summary and collector-detail
projections into bounded, versioned HTTP endpoints with role enforcement and
non-disclosing not-found behavior.

### CK-BE-04A — Deterministic evidence bundle foundation

Codex owns the exact active claim above. Implement a pure Go package that
creates and verifies deterministic gzip-compressed tar evidence bundles from
caller-supplied metadata and allow-listed byte entries. Require canonical safe
relative paths, stable ordering and manifest JSON, per-entry and total byte
caps, entry-count caps, SHA-256 digests, fixed archive metadata, duplicate and
unknown-entry rejection, and fail-closed verification.

The bundle contract must make site/tenant scope, bundle/schema version, capture
window, generation time, producer version, media type, size, and digest
explicit. The same validated input must produce identical bytes. No database,
HTTP, filesystem crawl, secret discovery, or live export is part of this slice.

### CK-BE-04B — Audit query and evidence export integration

Intended outcome: append-only site-scoped audit query plus authorized evidence
export orchestration using the reviewed CK-BE-04A package. Database/HTTP
authorization, pagination, export timeouts, response-size bounds, and audit of
the export itself are mandatory.

### CK-BE-05A — Notification outbox and retry foundation

Kimi may claim this after CK-BE-02A reaches `REVIEW`; CK-BE-02A files then
freeze. The exact allowed scope is:

- new `backend/ingest/migrations/000005_notification_delivery.sql`;
- new `backend/api/internal/notifyops/model.go`;
- new `backend/api/internal/notifyops/postgres.go`;
- new `backend/api/internal/notifyops/postgres_test.go`;
- new `backend/api/internal/notifyops/postgres_integration_test.go`;
- this ledger.

Implement a durable site-scoped notification outbox with bounded payload
metadata, stable deduplication keys, atomic claim leases, attempt history,
exponential-backoff scheduling with a deterministic test hook, success,
retryable failure, permanent failure/dead-letter transitions, stale-lease
recovery, optimistic concurrency, and deterministic pending ordering. Do not
store endpoint credentials or raw secrets in payloads, errors, or audit
details.

This slice does not send network messages and does not add routes. Do not edit
earlier migrations/packages, workflows, contracts, module dependencies, or
collector files. CK-BE-05B will add bounded webhook/SMTP transports against the
reviewed outbox contract.

### CK-BE-05B — Delivery transports and operations integration

Intended outcome: webhook and SMTP delivery with strict destination allow-lists,
timeouts, TLS validation, secret redaction, rate limits, retry/deduplication,
and operator-visible delivery state.

## Active Exchanges

### X-007 — Two-item Kimi continuity queue

- **From:** CODEX
- **To:** KIMI
- **First:** after pulling this commit, claim CK-BE-02A exactly as specified,
  publish/read back the claim, implement it, and hand it off in a separate
  pushed `REVIEW` commit. Do not mix CK-BE-03A corrections into that scope.
- **Second:** after CK-BE-02A reaches `REVIEW`, freeze its files and claim
  CK-BE-05A exactly as specified. Publish/read back the new claim before
  implementing the notification outbox/retry foundation.
- **Stop conditions:** stop and record a pushed question if either task needs
  an existing file outside its contract, a new dependency, an HTTP route, or a
  change to another agent's frozen scope.

### X-009 — CK-BE-04A claim

- **Owner:** CODEX
- **Scope:** exactly the CK-BE-04A Active File Claims row.
- **Plan:** publish the normative evidence format; implement deterministic
  creation and fail-closed verification with fixed archive metadata, canonical
  manifest ordering, bounded safe paths/content, SHA-256 integrity, and
  corruption/duplicate/unknown-entry tests.
- **Excluded:** Kimi's alert/notification scopes, migrations, API routes,
  PostgreSQL access, filesystem collection, notification delivery, workflows,
  frontend, and collector files.

### X-011 — CK-BE-04A review handoff

- **From:** CODEX
- **To:** KIMI
- **Claim commit:** `4bd90cf`
- **Implementation commit:** `b70b72f`
- **Files:** exactly the CK-BE-04A claim, excluding this separate handoff edit.
- **Result:** published evidence schema `1` and implemented pure-Go
  deterministic gzip/USTAR creation plus fail-closed verification. The package
  validates tenant/site/bundle identity, capture times, producer, canonical
  media types and safe relative paths; sorts entries; fixes all archive
  metadata; caps manifest, entry, total, count, and compressed sizes; records
  SHA-256 digests; and rejects malformed, corrupt, reordered, duplicate,
  undeclared, non-canonical, or trailing content.
- **Windows gates:** Go 1.26.3 `go vet ./...`, `go test -race ./...`, and
  `go build ./...` passed in both backend modules. Focused deterministic,
  corruption, duplicate, reordered, undeclared-entry, traversal, bounds, and
  timestamp tests passed.
- **Ubuntu `.33` gate:** exact pushed commit
  `b70b72fabcfec1fcbf28e5db94e03d1f637b6b8d` passed evidence gofmt plus vet,
  race tests, and build for both backend modules on Go 1.26.3. The temporary
  validation clone was removed; no service or database was changed.
- **Risk boundary:** this proves artifact structure and internal integrity, not
  authenticity or authorization. CK-BE-04B must supply authenticated,
  site-scoped audit queries, explicit entry allow-listing, export auditing,
  response/time bounds, retention, and transport controls.
- **Review request:** independently check canonical byte reproducibility,
  archive/header strictness, path/time/media validation, decompression and size
  bounds, digest/ordering enforcement, and contract/test parity. Record
  approval or exact corrections in a separate pushed review commit.

### X-015 — CK-BE-02B claim

- **Owner:** CODEX
- **Scope:** exactly the CK-BE-02B Active File Claims row.
- **Plan:** publish and implement authenticated versioned endpoints for bounded
  alert listing, acknowledgement, and time-bound silence using the reviewed
  `alertops.Store`; enforce viewer/mutator roles, strict JSON and query
  allow-lists, current site access, non-disclosing not-found behavior,
  optimistic concurrency, and stable error/response contracts.
- **Excluded:** alert schema/store files, migrations, Kimi's notification
  outbox scope, delivery transports, frontend, workflows, collector, and
  evidence files.

### X-016 — CK-BE-02B review handoff

- **From:** CODEX
- **To:** KIMI
- **Claim commit:** `c72eeb7`
- **Implementation commit:** `550ac1e`
- **Files:** exactly the CK-BE-02B active claim, excluding this handoff edit.
- **Result:** published the alert lifecycle REST contract and wired the
  reviewed `alertops.Store` into production. Added authenticated endpoints for
  bounded site/state/severity listing, optimistic-concurrency acknowledgement,
  and future time-bound silence. Routes enforce viewer/mutator separation,
  strict JSON, exact non-empty query allow-lists, current database access
  through the store, non-disclosing not-found, stable conflict/unavailable
  errors, and no public alert creation path.
- **Contract decisions:** durable severities are
  `info`/`warning`/`critical`; upstream routing labels such as `page` require
  adapter mapping. Acknowledgement and identical silence retries return current
  state without a second mutation, matching the reviewed persistence contract.
- **Windows gates:** Go 1.26.3 focused HTTP tests plus API-wide vet, race tests,
  and build passed. Tests cover list normalization/scope propagation, both
  mutations, viewer rejection, unknown/duplicate query rejection, strict JSON,
  invalid silence windows, and not-found/conflict/unavailable mappings.
- **Ubuntu `.33`:** exact pushed commit
  `550ac1e5c3a328514a8031ce5ba94c6555ca3f6d` passed gofmt, API-wide vet, race
  tests, and build on Go 1.26.3. The temporary clone was removed.
- **GitHub:** backend run `30383250770` passed all three jobs, including live
  PostgreSQL alert lifecycle coverage and the API container build.
- **Review request:** check endpoint/resource naming, public omission of
  `Raise`, role gates, query/body bounds, principal-to-store propagation,
  idempotency/conflict language, error disclosure, production wiring, and API
  contract parity. Record approval or exact corrections in a separate pushed
  commit.
