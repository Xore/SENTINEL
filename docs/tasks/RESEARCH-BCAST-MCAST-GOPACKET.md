# Research Task: Broadcast/Multicast Top-Talker — Python/scapy

> **Updated:** 2026-07-26 — rewritten for v2 Python collector (scapy replaces gopacket)
> **Status:** Open — research required before implementing `checks/net_bcast.py`
> **Linked phase:** Collector v2, Phase C11 — [`docs/collector/ROADMAP.md`](../collector/ROADMAP.md)
> **Blocks:** Phase C11 cannot start until exit criteria below are met (see also R1 in [`docs/gap-analysis/research-guide-for-gap-topics.md`](../gap-analysis/research-guide-for-gap-topics.md))

---

## Objective

Research and prototype the minimum viable Python implementation for capturing **broadcast and
multicast frames** on a Linux Ethernet interface and identifying the **top-N source MACs by
packet rate** — using `scapy.AsyncSniffer` inside the asyncio collector process.

The result of this task is:
1. A confirmed implementation approach with performance numbers on real Pi hardware
2. A working prototype (`prototype/net_bcast_proto.py`) reviewable before integration
3. Capability and packaging requirements documented for `docs/guides/00-setup.md`
4. Updated exit criteria checked off in the Research Guide (R1)

---

## Background

Broadcast and multicast storms are a leading cause of OT network degradation and wireless
segment saturation (TU Munich NET-2024-04-1 §3; RITICS/NCSC ICS-COI 2024 Appendix A).
Identifying the top-N offenders by source MAC and packet rate allows the collector to flag
misbehaving endpoints before the segment fails.

The v2 collector:
- Is a **Python 3.12 asyncio process**, packaged as a PyInstaller `--onefile` binary
- Must capture only broadcast/multicast frames — **never unicast** (OT confidentiality)
- Must inject **zero packets** into the network (fully passive)
- Must have **minimal CPU overhead** on a Raspberry Pi 5 (weakest supported target since
  [ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md); previously a Pi 3B)
- Uses `scapy==2.5.0` (already in `requirements.txt` for Phase C11)

---

## Implementation approach

### `scapy.AsyncSniffer` with BPF pre-filter

Scapy’s `AsyncSniffer` runs the capture loop in a background thread and passes packets to an
asyncio-safe callback. A BPF filter applied at socket creation pre-filters to broadcast/multicast
only, keeping userspace work minimal.

**Prototype sketch (`prototype/net_bcast_proto.py`):**

```python
import asyncio
import time
from collections import defaultdict
from scapy.all import AsyncSniffer, Ether

WINDOW_SECS = 30
TOP_N = 10

def run_bcast_snapshot(iface: str) -> list[dict]:
    """Capture bcast/mcast for WINDOW_SECS; return top-N talkers by pkt count."""
    counts: dict[str, int] = defaultdict(int)

    def on_packet(pkt):
        eth = pkt.getlayer(Ether)
        if eth:
            counts[eth.src] += 1

    sniffer = AsyncSniffer(
        iface=iface,
        # BPF: accept if dst MAC LSB set (broadcast or multicast)
        filter="ether broadcast or ether multicast",
        prn=on_packet,
        store=False,   # do not buffer raw packets — only counts
    )
    sniffer.start()
    time.sleep(WINDOW_SECS)
    sniffer.stop()

    sorted_talkers = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [
        {"src_mac": mac, "pkts": n}
        for mac, n in sorted_talkers[:TOP_N]
    ]

if __name__ == "__main__":
    import json, sys
    iface = sys.argv[1] if len(sys.argv) > 1 else "eth0"
    print(json.dumps(run_bcast_snapshot(iface), indent=2))
```

**Key design decisions:**
- `store=False` — raw packets are never buffered in memory; only the count dict grows.
- BPF filter applied at kernel socket level — unicast frames never reach Python.
- `prn` callback is called from scapy’s capture thread; the `counts` dict is thread-local
  to the capture window (no asyncio cross-thread sharing needed during the window).
- The final aggregation and OTLP metric emission happen after `sniffer.stop()` on the
  asyncio event loop via `asyncio.get_event_loop().run_in_executor(None, run_bcast_snapshot, iface)`.

---

## Research questions

- [ ] Does the pinned `scapy` install cleanly inside the PyInstaller venv on a Pi 5? (arm64 only — the Pi 5 is 64-bit and armv7 is out of scope)
- [ ] Is `CAP_NET_RAW` sufficient, or does scapy require full root on Pi OS?
- [ ] Does PyInstaller correctly bundle scapy’s BPF/socket internals (`--collect-all scapy`)?
- [ ] What is CPU overhead (% of one core) at 100 pps broadcast traffic on a Pi 5?
- [ ] What is RSS memory overhead during a 30 s capture window with `store=False`?
- [ ] Does `sniffer.stop()` reliably unblock within <1 s after the window ends?
- [ ] Are there dropped packets (`sniffer.results` stats) at 100 pps on Pi 5 storage?

---

## Benchmarking procedure

### Step 1 — Install and import check
```bash
pip install scapy==2.5.0
python3 -c "from scapy.all import AsyncSniffer; print('ok')"
```

### Step 2 — Capability check
```bash
# Test with service account (not root)
sudo setcap cap_net_raw+ep $(which python3)
python3 prototype/net_bcast_proto.py eth0
# OR via systemd AmbientCapabilities=CAP_NET_RAW
```

### Step 3 — CPU measurement at baseline
```bash
# In one terminal: run the prototype
python3 prototype/net_bcast_proto.py eth0

# In another: sample CPU every second
python3 -c "
import psutil, time
for _ in range(35):
    print(psutil.cpu_percent(interval=1))
"
```

### Step 4 — Stress test at 100 pps
From another host on the same segment:
```python
from scapy.all import sendp, Ether, IP, UDP
sendp(
    [Ether(dst="ff:ff:ff:ff:ff:ff") / IP() / UDP()] * 3000,
    iface="eth0", inter=0.01  # 100 pps
)
```
Repeat the CPU measurement from Step 3 during replay.

### Step 5 — PyInstaller bundle test
```bash
pyinstaller --onefile --collect-all scapy prototype/net_bcast_proto.py
time ./dist/net_bcast_proto eth0
```
Confirm the bundled binary runs and produces correct output.

---

## Decision criteria

| Criterion | Requirement |
|---|---|
| Installs in PyInstaller venv on Pi 5 (arm64) | Mandatory |
| `CAP_NET_RAW` sufficient (no full root) | Mandatory |
| Kernel BPF pre-filter (bcast/mcast only, no unicast) | Mandatory |
| CPU overhead <5% of one core at 100 pps on Pi 5 | Mandatory (re-derived from the old 15%-of-an-A53 figure) |
| RAM overhead <30 MB during 30 s window (`store=False`) | Mandatory |
| Fully passive (zero injected packets) | Mandatory |
| PyInstaller bundle works (`--collect-all scapy`) | Mandatory |
| `sniffer.stop()` unblocks within 1 s | Mandatory |

---

## Deliverables

1. **`prototype/net_bcast_proto.py`** — standalone Python file demonstrating the approach
2. **Benchmark results** — CPU%, RSS, pkt/s on a Pi 5, recorded in this document under a `## Results` section
3. **Decision record** — update this file: confirmed approach or reasoned pivot
4. **Capability grant documented** — exact `setcap` or systemd `AmbientCapabilities` line for `docs/guides/00-setup.md`
5. **Exit criteria R1 checked off** in [`docs/gap-analysis/research-guide-for-gap-topics.md`](../gap-analysis/research-guide-for-gap-topics.md)

---

## References

- scapy `AsyncSniffer` docs: https://scapy.readthedocs.io/en/latest/usage.html#asynchronous-sniffing
- scapy BPF filters: https://scapy.readthedocs.io/en/latest/usage.html#filtering
- PyInstaller + scapy: https://pyinstaller.org/en/stable/hooks.html (`--collect-all scapy`)
- TU Munich NET-2024-04-1: https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2024-04-1/NET-2024-04-1_09.pdf
- RITICS/NCSC ICS-COI 2024: https://ritics.org/wp-content/uploads/2024/08/How-to-log-and-monitor-in-ICS-OT-Environments.pdf
- Linux AF_PACKET man page: https://man7.org/linux/man-pages/man7/packet.7.html
