# ADR 0001 — Canonical Service and Source Layout

- **Status:** Accepted
- **Date:** 2026-07-26

## Decision

Use these canonical source roots:

```text
collector/                  Python edge collector
backend/ingest/             Go OTLP ingest and PKI enrollment
backend/analyse/            Python site analysis and ML
backend/api/                Go site REST/WebSocket API
frontend/                   SvelteKit site UI
federation/agent/           Go site federation agent
global/api/                 Go global REST/WebSocket API
global/correlator/          Python cross-site correlation
global/ml-aggregator/       Python federated-learning coordinator
frontend-global/            SvelteKit global UI
deploy/                     Compose, proxies, configuration, operations
```

`hub` is a deployment role, not a source-code root. Existing `deploy/hub/` paths
remain valid. New production services must not be created under a second `hub/`
source tree.

## Consequences

- The Opus guide’s `backend/` examples remain valid.
- Compose build contexts point to these canonical roots.
- A component owns its internal models; cross-service models live in
  `contracts/` with generated bindings or compatibility tests.
