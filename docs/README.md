# SENTINEL Documentation

This page is the front door for current project documentation. Start with the
architecture, then use the contracts and implementation guide for the area you
are changing. Completed task records live under [`archive/`](archive/README.md).

## Start here

| Need | Document |
|---|---|
| Target system design | [Extended architecture](architecture/ARCHITECTURE-V2-EXTENDED.md) |
| Implementation order and ownership | [Sonnet implementation guide](guides/SONNET-5-IMPLEMENTATION-GUIDE.md) |
| Current Codex/Sonnet work | [Agent coordination](guides/AGENT-COORDINATION.md) |
| Current Codex/Kimi backend work | [Backend coordination](guides/CODEX-KIMI-COORDINATION.md) |
| API, metrics, events, enrollment, and evidence rules | [Contracts index](contracts/README.md) |
| Collector design | [Collector v2 refactor](collector/COLLECTOR-V2-REFACTOR.md) |
| Installation | [Setup guide](guides/00-setup.md) |
| Testing on Windows, CI, and lab hosts | [Testing and installation](guides/08-testing-and-installation.md) |

## Directory map

| Directory | Contents |
|---|---|
| [`architecture/`](architecture/) | Canonical architecture, deployment design, traceability, and accepted ADRs |
| [`collector/`](collector/) | Collector design, roadmap, and implementation decisions |
| [`contracts/`](contracts/) | Normative external and internal contracts |
| [`guides/`](guides/) | Active setup, operations, testing, and agent work queues |
| [`gap-analysis/`](gap-analysis/) | Remaining implementation gaps and validation gates |
| [`theory/`](theory/) | Research inputs for features that are not fully implemented |
| [`ml/`](ml/) | ML baseline-learning design |
| [`security/`](security/) | Open security remediation work |
| [`tasks/`](tasks/) | Open research tasks |
| [`archive/`](archive/README.md) | Completed or superseded records |

## Authority and lifecycle

1. `architecture/ARCHITECTURE-V2-EXTENDED.md` defines the target system.
2. Accepted ADRs and `contracts/` define binding implementation decisions.
3. Active coordination ledgers define current ownership and review state.
4. Research and gap-analysis documents inform future work but do not override
   architecture, ADRs, or contracts.
5. A task document moves to `archive/` only after independent review marks the
   task `DONE`; unresolved or future work stays active.
