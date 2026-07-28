# Architecture Decision Records

ADRs are immutable after acceptance. Supersede a decision with a new ADR rather
than rewriting its outcome. Implementation must follow accepted ADRs unless the
coordination ledger records a blocking conflict.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-canonical-service-layout.md) | Canonical service and source layout | Accepted |
| [0002](0002-telemetry-ingest-and-naming.md) | Telemetry path and metric naming | Accepted |
| [0003](0003-federation-event-replication.md) | Federation transport and event replication | Accepted |
| [0004](0004-federated-learning-privacy.md) | Federated-learning privacy boundary | Accepted |
| [0005](0005-passive-modbus-detection.md) | Passive Modbus write detection contract | Accepted |
| [0006](0006-signed-collector-updates.md) | Signed collector update authority | Accepted |
| [0007](0007-production-ha-and-versioning.md) | HA configuration and version pinning | Accepted |
| [0008](0008-measured-capacity-envelopes.md) | Scale claims require measured envelopes | Accepted |
| [0009](0009-identity-tenancy-and-time.md) | Identity, tenancy, and time invariants | Accepted |
| [0010](0010-database-migrations.md) | Database migration policy | Accepted |
| [0011](0011-direct-probe-backend-routing.md) | Direct probe-to-backend routing | Accepted |
