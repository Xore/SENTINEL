# GitHub Actions Pipeline

## Current required validation

| Workflow | Scope | Required behavior |
|---|---|---|
| `collector.yml` | Python collector | Ruff, mypy, pytest |
| `pylint.yml` | Python collector | Pylint |
| `backend.yml` | Go backend and SQL | gofmt, vet, race tests, build, empty-PostgreSQL migration |
| `container-supply-chain.yml` | Go ingest image | PR/main build, fixed high/critical vulnerability gate, SPDX SBOM; signed multi-arch GHCR publish only for `v*` tags |
| `codeql.yml` | Python, Go, Actions | CodeQL when repository security features permit |

All workflows use least-privilege `contents: read` unless a documented write is
required. Pull-request workflows do not execute untrusted repository code with
write-capable tokens or deployment secrets.

## Planned gated delivery

Multi-architecture ingest builds, SBOM generation, vulnerability scanning, and
signed provenance are active. Main and pull requests never publish. Creating a
`v*` tag is the explicit release authorization that publishes immutable version
and commit tags to GHCR, signs the digest with GitHub OIDC, and attaches GitHub
provenance and SBOM attestations. `latest` is never emitted.

The following remain intentionally inactive:

1. protected-environment hub deployment;
2. canary/cohort collector rollout;
3. automatic rollback and post-deploy verification.

These activate only after production Dockerfiles/Compose, immutable image
versioning, GitHub environments, secret bootstrap, and rollback procedures exist.
No workflow may deploy to the documented live Wi-Fi-only collector.
