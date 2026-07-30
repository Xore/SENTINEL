# SENTINEL Documentation

This page is the front door for current project documentation. Start with the
architecture, then use the contracts and implementation guide for the area you
are changing. Completed task records live under [`archive/`](archive/README.md).

**Open work is tracked in [GitHub Issues](https://github.com/Xore/SENTINEL/issues),
not in these documents.** Every unstarted phase, research gate, and undecided
design question has an issue; the documents here describe *what* each thing is
and *why*, and the coordination ledgers carry the live claims and reviews for
whatever is being worked on right now. If you are looking for something to pick
up, start with the issue list.

## Start here

| Need | Document |
|---|---|
| Something to work on | [Open issues](https://github.com/Xore/SENTINEL/issues) |
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
6. GitHub Issues are the backlog. A document states scope once; the issue links
   it. When the two disagree about *what is still open*, the issue wins.
