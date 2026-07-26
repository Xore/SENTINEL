# v2 Collector — Research Guide

> **Updated:** 2026-07-26
> **Purpose:** Pre-implementation validation checklist for every open research gate in the v2 Python
> collector. Do not begin coding a phase until its exit criteria below are met.
> **Companion:** [`gap-analysis-collector-vs-standalone.md`](gap-analysis-collector-vs-standalone.md)

---

## How to use this guide

Work in gate order. Each section states:
- **What to test** — concrete prototype or measurement task on real hardware
- **Exit criteria** — the minimum evidence required before the phase is unblocked
- **Blocks phase** — which ROADMAP phase cannot start until this gate closes

---

## R1 — scapy AsyncSniffer on Raspberry Pi 3B (blocks Phase C11)

**Context:** Phase C11 (`checks/net_bcast.py`) uses `scapy.AsyncSniffer` with a BPF filter
`ether broadcast or ether multicast` over a 30 s capture window to snapshot broadcast/multicast
top-talkers. The concern is CPU overhead on a Pi 3B at OT segment rates (typically <100 pps).

### Step R1.1 — Verify scapy install on Pi
- Install `scapy==2.5.0` inside the collector venv on a Pi 3B.
- Confirm `from scapy.all import AsyncSniffer` imports without error.
- Confirm `CAP_NET_RAW` is available to the service account (or document the capability grant needed).

### Step R1.2 — Baseline CPU measurement
- Start `AsyncSniffer(filter="ether broadcast or ether multicast", store=True)` for 30 s
  on the Pi’s primary interface during a representative traffic period.
- Record: CPU% (via `psutil.cpu_percent(interval=1)` sampled every second during the capture),
  total packets captured, and any scapy `WARNING` or dropped-packet messages.

### Step R1.3 — Stress test at target OT rate
- If live traffic is <10 pps, replay a synthetic bcast stream from another host
  (`python3 -c "from scapy.all import *; sendp([Ether(dst='ff:ff:ff:ff:ff:ff')/IP()/UDP()]*500, iface='eth0', inter=0.01)"`).
- Confirm CPU overhead stays below **15% of one core** at 100 pps.
- Confirm the 30 s window completes and top-N=10 aggregation finishes in <1 s.

### Exit criteria — R1
- [ ] `scapy==2.5.0` installs cleanly inside the PyInstaller venv on Pi 3B
- [ ] `CAP_NET_RAW` grant documented (capability or systemd `AmbientCapabilities`)
- [ ] CPU overhead <15% of one core at 100 pps broadcast traffic
- [ ] 30 s capture + top-N aggregation completes within 1 s of window end
- [ ] Results documented in `docs/tasks/RESEARCH-BCAST-MCAST-GOPACKET.md`

---

## R2 — bcc Python bindings on Raspberry Pi OS (blocks Phase C13)

**Context:** Phase C13 (`checks/ebpf/flow_tracker.py`) uses `bcc` Python bindings to load a BPF
C program for passive flow tracking. This requires `python3-bpfcc`, kernel BPF support, and
`CAP_BPF + CAP_PERFMON` (Linux 5.8+). Raspberry Pi OS compatibility is unverified.

### Step R2.1 — Kernel version check
- On each target Pi: `uname -r`. Must be ≥5.8 for `CAP_BPF`/`CAP_PERFMON` split.
- On Raspberry Pi OS (64-bit Bookworm): expected ≥6.1 — confirm.
- On Raspberry Pi OS (32-bit Bullseye): likely <5.8 — document as unsupported.

### Step R2.2 — Package availability
- `apt-cache show python3-bpfcc` — confirm version and availability.
- Note: `python3-bpfcc` is NOT bundled by PyInstaller; it must be a system package.
  Document the install requirement in `docs/guides/00-setup.md`.

### Step R2.3 — Minimal BPF load test
- Write a minimal test: load a `BPF(text="int kprobe__sys_clone(void *ctx) { return 0; }")`
  and confirm it loads and unloads cleanly under the service account’s capability set.
- Confirm `CAP_BPF` and `CAP_PERFMON` can be granted via systemd `AmbientCapabilities`
  without requiring full root.

### Step R2.4 — Graceful fallback
- When `python3-bpfcc` is absent or kernel version is insufficient, confirm the collector
  logs a structured warning and disables Phase C13 cleanly — does not crash, does not
  prevent other phases from running.
- This fallback contract must be implemented and tested before Phase C13 is merged.

### Exit criteria — R2
- [ ] Kernel version confirmed ≥5.8 on all production Pi targets
- [ ] `python3-bpfcc` package confirmed available and installable
- [ ] Minimal BPF load/unload test passes under service account capabilities
- [ ] Graceful fallback (no `python3-bpfcc` or old kernel) tested and confirmed
- [ ] Results documented in `docs/tasks/RESEARCH-EBPF-BCC-RPI.md` (to be created)

---

## R3 — PyInstaller `--onefile` startup time on Pi 3B (blocks Phase B1)

**Context:** The v2 collector ships as a PyInstaller `--onefile` binary. On slow ARM hardware
(Pi 3B SD card), the self-extraction step at startup can take several seconds. This matters
because the systemd unit uses `ExecStartPre` health checks with a short timeout.

### Step R3.1 — Build a representative binary
- Build the Phase 1 binary (`__main__.py` + `config.py` + `scheduler.py` + all Phase 2
  `checks/`) using `pyinstaller --onefile --name collector collector/__main__.py`.
- Target: Linux arm64 via `Dockerfile.collector-arm64` (cross-compiled with buildx + QEMU,
  then copied to Pi for timing).

### Step R3.2 — Measure cold and warm startup
- Cold: `time ./collector --version` immediately after copy to Pi 3B SD card (extraction to `/tmp`).
- Warm: repeat 3 times (extraction cache in `/tmp` may help on subsequent runs).
- Record: cold extraction time, warm time, `/tmp` disk space used by extracted bundle.

### Step R3.3 — Evaluate systemd timeout compatibility
- If cold startup >5 s, increase `TimeoutStartSec` in the systemd unit template and
  document the change.
- If cold startup >15 s, evaluate `--onedir` mode instead of `--onefile`
  (no self-extraction, faster start, but multi-file distribution).

### Exit criteria — R3
- [ ] Cold startup time measured on Pi 3B SD card
- [ ] Warm startup time measured (3 runs)
- [ ] Systemd `TimeoutStartSec` set to a value that comfortably exceeds cold startup
- [ ] Decision (`--onefile` vs `--onedir`) documented with measured numbers
- [ ] Results documented in `docs/tasks/RESEARCH-PYINSTALLER-RPI.md` (to be created)

---

## Research gate summary

| Gate | Blocks phase | Primary test | Hardware needed |
|---|---|---|---|
| R1 — scapy/Pi CPU overhead | C11 (bcast/mcast) | CPU% at 100 pps bcast | Pi 3B |
| R2 — bcc/Pi kernel + package | C13 (eBPF flows) | BPF load test; graceful fallback | Pi 3B (64-bit Bookworm) |
| R3 — PyInstaller startup time | B1 (CI build) | Cold/warm startup timing | Pi 3B SD card |

All three gates require measurement on the **actual target hardware** — do not substitute
cloud VM benchmarks or assume results transfer from x86.
