# ADR 0012 — Collector Reference Hardware Baseline

- **Status:** Accepted
- **Date:** 2026-07-30
- **Supersedes:** the Raspberry Pi 3B assumptions embedded in NFR-01 and NFR-02
  of [`COLLECTOR-V2-REFACTOR.md`](../../collector/COLLECTOR-V2-REFACTOR.md) and in
  research gates R1–R3.

## Context

Every collector-side resource decision to date was derived from a Raspberry Pi
3B: four Cortex-A53 cores at 1.2 GHz and 1 GB of RAM. That single assumption
propagated into absolute constants — a two-worker CPU thread pool, a
network-concurrency semaphore of 20, an 80 MB RSS ceiling — and into the
framing of three open research gates, each of which asks whether a Python
feature is affordable *on a Pi 3B*.

The 3B is no longer the floor. It is a 2016 board whose 1 GB of RAM and
32-bit-era cores forced conservatism that the project does not actually need,
and several of the constants it produced are now the binding limit on
throughput rather than a protection against overload.

## Decision

**The minimum supported collector platform is the Raspberry Pi 5.** Where a
Pi 5 has insufficient resources for a given site's probe load, the deployment
moves to a small-form-factor x86-64 PC. There is no lower tier.

The reference configuration for stated envelopes and acceptance criteria is a
Raspberry Pi 5 with 4 GB RAM on arm64. The 2 GB variant is supported but is not
the figure envelopes are quoted against; 8 GB and 16 GB variants and SFF PCs
have strictly more headroom.

This changes the class of machine, not the discipline:

- **Resource budgets stay expressed as a share of the node, not as constants.**
  NFR-01 and NFR-02 remain percentage-shaped. A collector that grows to consume
  its larger allowance is still a defect.
- **Absolute limits tuned to the 3B become configuration, not literals.** Any
  constant whose value was derived from 3B capacity is a configurable setting
  with a default sized for the reference Pi 5. `CollectorSettings` is the home
  for these; hard-coded module-level caps are not.
- **Envelopes still come from measurement**, per
  [ADR 0008](0008-measured-capacity-envelopes.md). Numbers re-derived here from
  the hardware change are *proposals* until measured on the reference platform.
- **32-bit ARM is out of scope.** The Pi 5 is arm64-only, so the supported
  target matrix is Linux amd64, Linux arm64, Windows amd64. No armv7 artifact
  is built, tested, or supported.

## Consequences

### Revised non-functional requirements

| ID | Was (Pi 3B) | Now (reference Pi 5, 4 GB) | Note |
|---|---|---|---|
| NFR-01 | ≤ 80 MB RSS — 8% of 1 GB | ≤ 150 MB RSS — under 4% of 4 GB | Relatively *stricter* than before while giving absolute room for the lmdb hot buffer and a scapy sniffer. Proposal pending measurement. |
| NFR-02 | ≤ 5% average CPU on 4×A53 @ 1.2 GHz | ≤ 5% average CPU on 4×A76 @ 2.4 GHz | The percentage is unchanged; the work it buys is roughly 3–4× greater, since the A76 is a much wider core at twice the clock. This is where the headroom for raised concurrency comes from. |

The rule barring NumPy and pandas from the collector **stands**, but its
justification changes: it is now a bundle-size, cold-start, and
separation-of-concerns rule (ML is hub-side, per ADR 0001), not an RSS rule.
150 MB would accommodate them; the architecture still should not.

### Constants that must be revisited

These were derived from 3B capacity and are now under-sized. Each needs an
owner, a re-derived default, and a `CollectorSettings` field:

| Location | Constant | Problem |
|---|---|---|
| `collector/utils/thread_pool.py` | `ThreadPoolExecutor(max_workers=2)` | Hard-capped at module level with a 3B rationale in the comment. Not configurable at all. On a 4-core A76 this is the tightest limit in the collector. |
| `collector/config.py` | network semaphore default of 20 | Already correctly a setting, with a comment anticipating exactly this change. Only the default needs re-deriving. |
| `collector/checks/__init__.py` | semaphore docstring | Cites the 3B as the reason for the cap. |
| `collector/checks/net_icmp.py` | `ping()` docstring | Argues against a thread-pool round trip on 3B CPU grounds. |

Raising the pool size does **not** dissolve the S2-02 review finding about
hostname resolution inside a pool worker: that defect is one of cancellation
semantics — an executor future cannot be cancelled once running, so the
resolution outlives the timeout regardless of hardware. A larger pool makes
starvation less acute, not absent, and the resolution still escapes its
timeout budget. The correction stands as written.

### Research gates re-baselined

R1–R3 do not close as a result of this decision; they change platform and lose
most of their risk.

| Gate | Change |
|---|---|
| R1 — scapy CPU overhead | Re-baselined to the Pi 5. The old ceiling of 15% of one A53 core at 100 pps is roughly 4% of an A76 core for identical work; with a kernel BPF filter dropping non-matching frames before Python sees them, this is very likely a non-issue. Still measured, not assumed. |
| R2 — `bcc` / eBPF availability | Materially de-risked. The Pi 5 runs a 64-bit kernel 6.6 or newer with BTF and modern BPF support, against the 3B's older 64-bit Bookworm kernel. The question narrows from "is BPF usable" to "is `python3-bpfcc` packaged for this image". |
| R3 — PyInstaller cold start | Re-baselined off SD card. The Pi 5 supports NVMe over PCIe, so the self-extraction cost the gate was written to catch is largely an artifact of 3B SD-card I/O. The ≤ 15 s acceptance figure should be re-derived downward. |

### Deployment and acceptance

- The supported platform matrix drops armv7 and the 3B/4B wording:
  Linux amd64, Linux arm64 (Raspberry Pi 5 or better), Windows amd64.
- Field acceptance runs on a Pi 5 and an amd64 machine, not a 3B.
- Hub-side container CPU reservations written "conservative on Pi 3B / Pi 4"
  are re-derived; the hub was never a 3B workload in the first place.
- The Go-versus-Python language decision is **confirmed, not reopened**. Its
  only remaining pro-Go arguments were idle memory (~15 MB against ~35 MB) and
  cold start (<100 ms against ~400 ms). Both were weighed against 1 GB and slow
  SD-card I/O; on the new baseline they are further from binding than before.
