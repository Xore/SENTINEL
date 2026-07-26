# GitHub Actions Pipeline

## Current required validation

| Workflow | Scope | Required behavior |
|---|---|---|
| `collector.yml` | Python collector | Ruff, mypy, pytest |
| `pylint.yml` | Python collector | Pylint |
| `backend.yml` | Go backend and SQL | gofmt, vet, race tests, build, empty-PostgreSQL migration |
| `codeql.yml` | Python, Go, Actions | CodeQL when repository security features permit |

All workflows use least-privilege `contents: read` unless a documented write is
required. Pull-request workflows do not execute untrusted repository code with
write-capable tokens or deployment secrets.

## Planned gated delivery

The following are intentionally not active yet:

1. multi-architecture container builds;
2. SBOM and vulnerability scan;
3. signed artifacts and provenance;
4. release publication;
5. protected-environment hub deployment;
6. canary/cohort collector rollout;
7. automatic rollback and post-deploy verification.

These activate only after production Dockerfiles/Compose, immutable image
versioning, GitHub environments, secret bootstrap, and rollback procedures exist.
No workflow may deploy to the documented live Wi-Fi-only collector.
