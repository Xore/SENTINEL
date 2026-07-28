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
| CK-00 | Remove WireGuard and establish direct-routing invariant | CODEX | IN_PROGRESS | none | claimed below |
| CK-BE-01 | Maintenance-window contract, persistence, and API | CODEX | QUEUED | CK-00 DONE | exact claim required |
| CK-BE-02 | Alert instance lifecycle: list, acknowledge, silence | KIMI | QUEUED | CK-BE-01 REVIEW | exact claim required |
| CK-BE-03 | Fleet operations summary and collector detail API | UNASSIGNED | QUEUED | CK-BE-01 DONE | exact claim required |
| CK-BE-04 | Append-only operational audit query and evidence export | UNASSIGNED | QUEUED | CK-BE-02 DONE | exact claim required |
| CK-BE-05 | Webhook/SMTP delivery, retry, and deduplication | UNASSIGNED | QUEUED | CK-BE-02 DONE | exact claim required |

`UNASSIGNED` rows are not claims. Codex or Kimi may claim them only after their
prerequisites are satisfied and after publishing the exact file boundary.

## Active File Claims

| Timestamp (UTC) | Agent | Work ID | Files |
|---|---|---|---|
| 2026-07-28T17:25:00Z | CODEX | CK-00 | `docs/architecture/ARCHITECTURE-V2-EXTENDED.md`, `docs/architecture/REQUIREMENTS-TRACEABILITY.md`, new `docs/architecture/decisions/0011-direct-probe-backend-routing.md`, `docs/architecture/decisions/README.md`, `docs/collector/COLLECTOR-V2-REFACTOR.md`, `docs/collector/ROADMAP.md`, `docs/collector/SUGGESTIONS.md`, `docs/gap-analysis/gap-analysis-collector-vs-standalone.md`, `docs/gap-analysis/research-notes/07-arp-rate.md`, `docs/guides/OPUS-AGENT-GUIDE-V2.md`, `docs/guides/SONNET-5-IMPLEMENTATION-GUIDE.md`, `docs/ml/ML_BASELINE_LEARNING.md`, `docs/README.md`, `docs/theory/anomaly/rca-causal-inference.md`, `docs/theory/probes/fault-tree-multihop-paths.md`, `docs/theory/probes/gorilla-compression-go-theory.md`, `docs/theory/probes/passive-vs-active-measurement.md`, `docs/theory/probes/probe-to-backend-transport-theory.md`, delete `docs/theory/probes/wireguard-health-monitoring.md`, this ledger |

## Work Package Contracts

### CK-00 — Architecture simplification

Remove WireGuard as a monitored capability, API surface, metric family, ML
feature group, RCA scenario, roadmap item, and research dependency. Add an
accepted ADR stating that every deployed probe has a direct route to its
configured site backend. Preserve outage buffering and reconnect behavior;
direct routing is a topology invariant, not an availability guarantee.

Exit gate: repository-wide case-insensitive search has no remaining
`WireGuard`, `wireguard`, or `wg show` product references; documentation links
remain valid; the ADR is indexed.

### CK-BE-01 — Maintenance windows

Codex will publish an exact claim after CK-00 review. The intended outcome is a
site-scoped maintenance-window resource with bounded time intervals, reason,
creator, lifecycle state, optimistic concurrency, role enforcement, durable
audit events, migration coverage, and versioned REST endpoints. The contract
must support anomaly-training contamination masks without coupling the API to
the future analysis implementation.

### CK-BE-02 — Alert operations

Kimi may claim this after CK-BE-01 reaches `REVIEW`. Intended outcome:
site-scoped alert-instance listing plus acknowledge and silence transitions,
bounded pagination/filters, idempotent mutations, role enforcement, durable
audit events, and integration tests. Kimi must not change maintenance-window
files frozen in CK-BE-01 without a pushed question and explicit answer.

### CK-BE-03 — Fleet operations

Intended outcome: bounded fleet summary and collector-detail projections that
distinguish active, stale, disabled, never-seen, certificate-expiring, and
degraded states without leaking inaccessible sites.

### CK-BE-04 — Audit and evidence

Intended outcome: append-only, site-scoped audit query plus deterministic
evidence bundle creation with integrity metadata. Export authorization and
size/time bounds are mandatory.

### CK-BE-05 — Notification delivery

Intended outcome: webhook and SMTP delivery with durable attempts, exponential
backoff, idempotency/deduplication, secret redaction, bounded payloads, and
operator-visible delivery state.

## Active Exchanges

None.
