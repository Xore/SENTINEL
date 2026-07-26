# ADR 0004 — Federated-Learning Privacy Boundary

- **Status:** Accepted
- **Date:** 2026-07-26

## Decision

Model gradients/updates are sensitive derived data and are not assumed anonymous.
The protocol requires mTLS, signed round metadata, clipping, tensor/schema
validation, replay prevention, aggregation thresholds, and auditable local
opt-in. Differential privacy is an optional policy with explicit privacy-budget
accounting.

Raw training windows never leave the site. A global model is never promoted
directly: each site evaluates it in shadow mode, applies its own acceptance
threshold, and retains rollback to the previous local version.

## Consequences

- Documentation must not claim gradients contain no recoverable sample data.
- Secure aggregation can be added without changing the round envelope.
- Sites with insufficient clean samples do not participate in a round.
