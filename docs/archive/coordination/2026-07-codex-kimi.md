# Codex–Kimi Coordination History — July 2026

Completed work is archived here from
[`../../guides/CODEX-KIMI-COORDINATION.md`](../../guides/CODEX-KIMI-COORDINATION.md). The active
ledger remains authoritative for current claims and gates.

## CK-BE-03A — Fleet Operations PostgreSQL Projection Foundation

- **Owner:** KIMI
- **Status:** DONE
- **Claim commit:** `79137ec`
- **Implementation commit:** `5997b93`
- **Handoff commit:** `61fe7bb`
- **Review commit:** `68b85fd`
- **CI follow-up:** `bfeabe2`
- **Scope:** new `backend/api/internal/fleetops/{model,postgres}.go`, matching
  unit and PostgreSQL integration tests, and the active ledger.
- **Result:** added query-only fleet totals, ordered per-site counts, and
  bounded collector details for active, stale, disabled, never-seen, and
  certificate-expiring states. Queries intersect JWT scope with current
  database role/user/site access, use finite timeouts, deterministic ordering,
  default 50 / maximum 200 detail bounds, and non-null empty results for
  inaccessible or empty scopes.
- **Accepted semantics:** stale means older than five minutes; certificate
  expiry is an orthogonal count for non-disabled collectors expiring within
  fourteen days, including already-expired certificates; nullable timestamps
  retain nullable derived fields.
- **Verification:** Kimi's Linux Go 1.26 gates and live PostgreSQL tests passed.
  Codex independently passed gofmt, vet, race tests, build, and live fleetops
  plus registry integration at combined commit `e6e01a2` on Ubuntu `.33`.
  Backend run `30381562435` passed all three jobs after the permanent fleetops
  PostgreSQL CI gate was added.
- **Review outcome:** approved without correction. CK-BE-03B must preserve the
  accepted bounds and non-disclosing authorization when it later adds HTTP
  integration.

## CK-00 — Architecture Simplification (Direct Routing)

- **Owner:** CODEX
- **Status:** DONE
- **Implementation commit:** `665b8d3`
- **Handoff:** X-002
- **Review:** X-013, commit `d316cf0`
- **Scope:** architecture, requirements traceability, ADR 0011 plus decisions
  index, collector roadmap/refactor/suggestions documents, gap-analysis
  research, ML baseline notes, theory documents, and deletion of the
  dedicated tunnel-monitoring research document.
- **Result:** removed the retired overlay-tunnel capability from every
  monitored surface, API plan, metric family, ML feature group, RCA scenario,
  roadmap item, and research dependency; added accepted ADR 0011 requiring
  every deployed probe to have an ordinary IP route to its configured site
  backend while preserving bounded local buffering, retry, and idempotent
  replay for outages.
- **Verification:** Kimi independently ran the exit-gate search at `02d39a8`:
  no `WireGuard`/`wireguard`/`wg show` product references remain outside the
  coordination record; the research document is deleted; the ADR is accepted,
  indexed, and preserves the required outage behavior.
- **Review outcome:** approved without correction.

## CK-BE-01 — Maintenance Windows

- **Owner:** CODEX
- **Status:** DONE
- **Claim commit:** `808d690`
- **Implementation commit:** `c1f4baa`
- **CI commits:** `3ec0ef5`, `b1804df`
- **Handoff:** X-006
- **Review:** X-012, commit `02d39a8`
- **Scope:** versioned maintenance-window REST contract, migration
  `000003_operations.sql` (windows plus append-only operational audit),
  `internal/maintenance` persistence with per-site overlap serialization,
  optimistic concurrency, role enforcement, current-access revalidation, and
  router wiring.
- **Result:** site-scoped create/list/end with bounded half-open intervals,
  non-disclosing 404s, viewer/mutator role separation, durable audit events,
  and unit plus live PostgreSQL integration coverage; CI gained explicit
  migration-invariant and maintenance PostgreSQL gates.
- **Verification:** Kimi independently verified migration compatibility,
  append-only enforcement, overlap/half-open semantics, authorization,
  non-disclosure, concurrency/version behavior, and API contract parity, and
  re-ran the maintenance integration suite on Linux against
  `postgres:16-alpine` at `b2a8d56`.
- **Review outcome:** approved after one correction, recorded in X-010 and
  applied in `b1804df`: the runner integration test reset list now drops
  `alert_instances` (dependent tables are not removed by `DROP TABLE ...
  CASCADE`), and CI additionally runs the alertops and fleetops PostgreSQL
  integration suites.

## CK-BE-02A — Alert Lifecycle PostgreSQL Foundation

- **Owner:** KIMI
- **Status:** DONE
- **Claim commit:** `e6e01a2`
- **Implementation commit:** `a9c2435`
- **Correction commit:** `b1804df`
- **Handoff:** X-010, commit `b2a8d56`
- **Review:** X-014, commit `9a4d584`
- **Scope:** migration `000004_alert_operations.sql`, new
  `internal/alertops/{model,postgres}.go` with unit and PostgreSQL
  integration tests, and the active ledger.
- **Result:** durable site-scoped alert instances with per-site dedup keys;
  idempotent authorized `Raise`; bounded list with state/severity filters in
  stable `(fired_at DESC, alert_id DESC)` order; acknowledge and time-bound
  silence mutations with optimistic concurrency, current user/role/site
  revalidation, lost-response idempotency, non-disclosing not-found, and
  transactional append-only audit events (`alert.raised`,
  `alert.acknowledged`, `alert.silenced` on `alert_instance`).
- **Accepted semantics:** severity vocabulary is `info`, `warning`,
  `critical` (CK-BE-02B documents any vmalert label adapter mapping);
  `Raise` remains the authorized idempotent producer path; acknowledge
  idempotency key is the acknowledged state, silence idempotency key is
  (until, reason); silences are bounded to (now, now+30 days]; HTTP-only
  computed fields are CK-BE-02B scope.
- **Verification:** Kimi's Linux Go 1.26 gates and live PostgreSQL suites
  passed; Codex independently passed migration runner, alertops, maintenance,
  registry, and fleetops live race suites at `b1804df`, and GitHub backend
  run `30382719935` passed all jobs.
- **Review outcome:** approved after the `resetDatabase` correction Kimi
  reported and Codex applied; CK-BE-02A files are frozen for CK-BE-02B and
  CK-BE-04B integration.

## CK-BE-02B — Alert Lifecycle HTTP Integration

- **Owner:** CODEX
- **Status:** DONE
- **Claim commit:** `c72eeb7`
- **Implementation commit:** `550ac1e`
- **Handoff:** X-016
- **Review:** X-017 by Kimi
- **Scope:** `docs/contracts/API.md`,
  `backend/api/internal/httpapi/router.go`,
  `backend/api/internal/httpapi/router_test.go`,
  `backend/api/cmd/api/main.go`, and the coordination ledger.
- **Result:** exposed authenticated, bounded alert listing, acknowledgement,
  and time-bound silence endpoints using the reviewed `alertops.Store`.
  Routes enforce viewer/mutator separation, strict bodies and query
  allow-lists, current access, non-disclosing not-found behavior, optimistic
  concurrency, stable error contracts, and no public alert creation path.
- **Accepted semantics:** severities are `info`, `warning`, and `critical`;
  upstream `page` labels require adapter mapping; repeated acknowledgement and
  identical silence are idempotent.
- **Verification:** Windows Go 1.26.3 HTTP and API-wide vet/race/build gates
  passed. Ubuntu `.33` passed gofmt, API-wide vet, race tests, and build at
  exact `550ac1e`. GitHub backend run `30383250770` passed all jobs. Kimi
  independently reran HTTP and alert lifecycle race tests on Linux and
  approved the package without correction.
