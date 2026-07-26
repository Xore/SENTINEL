# ADR 0006 — Signed Collector Update Authority

- **Status:** Accepted
- **Date:** 2026-07-26

## Decision

The unprivileged collector never overwrites its running binary or invokes
arbitrary systemd commands. A separate minimal updater helper:

1. reads a root-owned update request file;
2. verifies an Ed25519-signed manifest, platform, monotonically increasing
   version, artifact size, and SHA-256;
3. stages on the same filesystem;
4. atomically switches a versioned symlink;
5. restarts only the named collector service;
6. performs a bounded health check;
7. rolls back to the previous version on failure.

The helper accepts no shell commands, URLs, or paths from the collector. Updates
roll out canary → cohort → fleet and support pause/abort.
