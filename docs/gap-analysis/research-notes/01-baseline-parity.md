# Topic 1: Baseline Parity (Collector Phase 0)


> **Language note (2026-07-30):** this research note predates the 2026-07-25 decision to
> write the v2 collector in Python (`docs/collector/SUGGESTIONS.md` §2). File names below
> are the Python modules; the findings themselves are language-independent.

Status: Research complete, validated against `monitor/outage_monitor.py`.

## Findings

- Loss % formula confirmed from `PingWorker`: `(sent - received) / sent * 100`.
- RTT distribution fields to port: `rtt_min`, `rtt_max`, `rtt_p50`, `rtt_p95` per target per cycle.
- Interface counters: Linux via `/proc/net/dev` delta (bytes/s, errors/s, drops/s); Windows via `Get-NetAdapterStatistics`.
- No external research citation needed — this is a direct, data-validatable port per `../research-guide-for-gap-topics.md` §1.

## Next Implementation Step

Add `collector/checks/net_icmp.py` (loss%/RTT) and a host interface-counter check, matching the design already sketched in `docs/collector/SUGGESTIONS.md` §6.1-6.2. **Both now exist** — `checks/net_icmp.py` shipped under S2-02 and `checks/host_network.py` under S3-01A — so what remains here is the validation step, not the implementation. Validate output against `monitor` SQLite `ping_samples` for the same targets/window before merging (exit criteria in research guide §1.3).

## Exit Criteria Status

- [ ] Python probe loss%/RTT matches standalone monitor within ±1 sample (pending — requires live network access not available in this research session).
