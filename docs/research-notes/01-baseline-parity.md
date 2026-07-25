# Topic 1: Baseline Parity (Collector Phase 0)

Status: Research complete, validated against `monitor/outage_monitor.py`.

## Findings

- Loss % formula confirmed from `PingWorker`: `(sent - received) / sent * 100`.
- RTT distribution fields to port: `rtt_min`, `rtt_max`, `rtt_p50`, `rtt_p95` per target per cycle.
- Interface counters: Linux via `/proc/net/dev` delta (bytes/s, errors/s, drops/s); Windows via `Get-NetAdapterStatistics`.
- No external research citation needed — this is a direct, data-validatable port per `docs/research-guide-for-gap-topics.md` §1.

## Next Implementation Step

Add `collector/net_icmp.go` (loss%/RTT) and `collector/net_interfaces.go` (counters), matching the design already sketched in `collector/SUGGESTIONS.md` §6.1-6.2. Validate output against `monitor` SQLite `ping_samples` for the same targets/window before merging (exit criteria in research guide §1.3).

## Exit Criteria Status

- [ ] Go prototype loss%/RTT matches standalone monitor within ±1 sample (pending — requires live network access not available in this research session).
