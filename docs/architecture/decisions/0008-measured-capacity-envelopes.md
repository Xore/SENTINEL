# ADR 0008 — Measured Capacity Envelopes

- **Status:** Accepted
- **Date:** 2026-07-26

## Decision

SENTINEL does not claim “unlimited” scale. Supported deployment sizes are
published as tested envelopes including collector count, sample rate, active
series, event rate, retention, hardware, p95/p99 latency, disk growth, and
failure headroom.

Required load-test checkpoints are 50, 200, 500, and the proposed maximum number
of collectors. A configuration becomes supported only below 70% sustained CPU,
memory, disk I/O, and analysis-cycle capacity with a documented failure margin.
