# Research Task: Broadcast/Multicast Top-Talker in Go (gopacket)

> **Created:** 2026-07-25  
> **Status:** Open — research required before implementing `net_bcast.go`  
> **Linked feature:** Collector v2, Phase C11 — `docs/collector/COLLECTOR-V2-REFACTOR.md` Section 16  
> **Assignee:** TBD  

---

## Objective

Research and prototype the minimum viable Go implementation for capturing **broadcast and multicast frames** on a Linux Ethernet interface and identifying the **top-N source MACs by packet rate** — without requiring `libpcap`, `tcpdump`, or Python on the collector node.

The result of this research task is:
1. A confirmed implementation approach (or a reasoned decision to pivot)
2. A working prototype (single `.go` file) that can be reviewed before it is integrated into `net_bcast.go`
3. Updated `go.mod` entries with pinned versions
4. Performance benchmarks (CPU%, RAM, overhead on a Raspberry Pi 4B at 100 Mbps)

---

## Background

Broadcast and multicast storms are a leading cause of OT network degradation and wireless segment saturation (TU Munich NET-2024-04-1 §3; RITICS/NCSC ICS-COI 2024 Appendix A). Identifying the top-N offenders by source MAC and packet rate allows the analysis service to flag misbehaving endpoints before the segment fails.

The collector binary must:
- Run as a **single static Go binary** on Linux/arm64 and Linux/amd64 (Raspberry Pi, x86 NUC)
- Capture only broadcast/multicast frames — **never unicast** (OT confidentiality)
- Inject **zero packets** into the network (fully passive)
- Have **minimal CPU and RAM overhead** on a Pi 3B/4B
- Not require installation of `libpcap`, `tcpdump`, Python, or any external runtime

---

## Candidate Approaches

### Option A: `github.com/google/gopacket` + `pcapgo` (AF_PACKET, no libpcap)

**Hypothesis:** `gopacket/pcapgo` implements AF_PACKET raw sockets in pure Go without requiring the `libpcap` C library. A BPF kernel filter applied at socket creation pre-filters to broadcast/multicast only.

**Research questions:**
- [ ] Does `pcapgo.NewEthernetHandle` work without libpcap on arm64 Linux?
- [ ] Can a classic BPF (cBPF) filter be attached to the AF_PACKET socket via `gopacket/pcapgo` to pre-filter bcast/mcast at kernel level?
- [ ] What is the CPU overhead on a Pi 4B at 100 Mbps with a 10-second capture window every 5 minutes?
- [ ] Does static linking work (CGO_ENABLED=0 cross-compile for linux/arm64)?
- [ ] Is `gopacket v1.1.19` the last maintained version, or is there an actively maintained fork?

**Prototype sketch:**
```go
package main

import (
    "github.com/google/gopacket"
    "github.com/google/gopacket/pcapgo"
    "github.com/google/gopacket/layers"
    "net"
    "time"
    "fmt"
)

func main() {
    handle, err := pcapgo.NewEthernetHandle("eth0")
    if err != nil { panic(err) }
    defer handle.Close()

    // BPF filter: only broadcast dst OR multicast dst
    // ether[0] & 1 != 0  →  LSB of first octet set = group address
    if err := handle.SetBPF(bcastMcastFilter()); err != nil {
        panic(err)
    }

    counts := make(map[string]uint64) // src MAC -> pkt count
    deadline := time.Now().Add(10 * time.Second)

    src := gopacket.NewPacketSource(handle, layers.LayerTypeEthernet)
    for pkt := range src.Packets() {
        if time.Now().After(deadline) { break }
        eth, ok := pkt.Layer(layers.LayerTypeEthernet).(*layers.Ethernet)
        if !ok { continue }
        counts[eth.SrcMAC.String()]++
    }

    // Print top-5
    for mac, n := range counts {
        fmt.Printf("%s -> %d pkts\n", mac, n)
    }
}
```

**Open question:** `pcapgo.NewEthernetHandle` may still require some kernel headers at link time. Needs verification on a clean Pi OS image without dev packages.

---

### Option B: `golang.org/x/net/bpf` + `syscall.Socket(AF_PACKET, SOCK_RAW, ...)` — pure stdlib

**Hypothesis:** A raw AF_PACKET socket can be opened with standard `syscall` package, and a classic BPF program assembled with `golang.org/x/net/bpf` can be attached via `SO_ATTACH_FILTER`. This has zero non-stdlib dependencies.

**Research questions:**
- [ ] Is `golang.org/x/net/bpf` expressive enough for the `ether[0] & 1 != 0` filter?
- [ ] How does manual Ethernet frame parsing compare in effort to gopacket?
- [ ] Is this approach better for CGO_ENABLED=0 cross-compilation?

**Prototype sketch:**
```go
// Open raw AF_PACKET socket
fd, err := syscall.Socket(syscall.AF_PACKET, syscall.SOCK_RAW,
    int(htons(syscall.ETH_P_ALL)))
if err != nil { /* handle */ }

// Assemble BPF: accept packet if ether[0] & 1 != 0 (group address)
filter := []bpf.Instruction{
    bpf.LoadAbsolute{Off: 0, Size: 1},           // load dst[0]
    bpf.ALUOpConstant{Op: bpf.ALUOpAnd, Val: 1}, // & 0x01
    bpf.JumpIf{Cond: bpf.JumpEqual, Val: 0, SkipTrue: 1},
    bpf.RetConstant{Val: 65535},                 // accept
    bpf.RetConstant{Val: 0},                     // reject
}
assembled, _ := bpf.Assemble(filter)
// attach to socket via SO_ATTACH_FILTER ...
```

---

### Option C: `github.com/mdlayher/packet` — modern AF_PACKET wrapper

`github.com/mdlayher/packet` is a pure-Go AF_PACKET library actively maintained (2024), designed specifically to replace the gopacket AF_PACKET handle. It supports BPF filter attachment and zero-copy ring buffers.

**Research questions:**
- [ ] Does `mdlayher/packet` support classic BPF filter attachment?
- [ ] Does it support `PACKET_MMAP` (zero-copy ring buffer) for lower CPU overhead on high-traffic segments?
- [ ] Binary size impact vs gopacket?

---

## Decision Criteria

Choose the option that satisfies ALL of:

| Criterion | Requirement |
|---|---|
| No libpcap binary on collector node | Mandatory |
| CGO_ENABLED=0 cross-compile for linux/arm64 | Mandatory |
| Kernel BPF pre-filter (bcast/mcast only) | Mandatory |
| CPU overhead < 2% on Pi 4B at 10s capture / 5min interval | Mandatory |
| RAM overhead < 20 MB during capture window | Mandatory |
| Fully passive (zero injected packets) | Mandatory |
| Maintained library (last commit < 12 months) | Preferred |
| PACKET_MMAP zero-copy ring buffer support | Preferred |

---

## Deliverables

1. **`prototype/net_bcast_proto.go`** — standalone Go file (not part of collector build) demonstrating the chosen approach
2. **Benchmark results** — CPU%, RSS, pkt/s throughput on Pi 4B, recorded in this document
3. **Decision record** — update this file with the chosen option + rationale
4. **Updated `go.mod` entries** — pinned versions for the chosen library
5. **Implementation notes** — any gotchas discovered (e.g., `PACKET_MMAP` page alignment, BPF assembly quirks, CGO interaction)

---

## Timeline

- **Research + prototype:** 1 week
- **Benchmark + decision:** 2 days
- **Integration into `net_bcast.go`:** tracked as Phase C11 in `COLLECTOR-V2-REFACTOR.md`

---

## References

- `github.com/google/gopacket` — https://github.com/google/gopacket
- `github.com/mdlayher/packet` — https://github.com/mdlayher/packet
- `golang.org/x/net/bpf` — https://pkg.go.dev/golang.org/x/net/bpf
- TU Munich NET-2024-04-1: https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2024-04-1/NET-2024-04-1_09.pdf
- RITICS/NCSC ICS-COI 2024: https://ritics.org/wp-content/uploads/2024/08/How-to-log-and-monitor-in-ICS-OT-Environments.pdf
- Linux AF_PACKET man page: https://man7.org/linux/man-pages/man7/packet.7.html
- Paris traceroute (mtr basis): Augustin et al. IMC 2006 — https://dl.acm.org/doi/10.1145/1177080.1177100
