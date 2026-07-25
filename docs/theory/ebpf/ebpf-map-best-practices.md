# eBPF Map State Best Practices for Long-Running Go Services

> **Academic basis:** cilium/ebpf library design (pkg.go.dev); ebpf.io pinning docs; Zhao et al. Wasm-bpf arXiv:2408.04856, 2024; Tarazi, "Primer on eBPF Map Batch Operations", LPC 2024.

This document records the canonical patterns for managing eBPF map state in long-running Go services such as `collector/`. All code uses `github.com/cilium/ebpf`, which is explicitly designed for long-running production processes.

---

## 1. Map Lifetime & Reference Counting

Every BPF map is **reference-counted by the kernel**. When the last file descriptor referencing it closes — including your Go process exiting or crashing — the kernel frees the map and all its data. This is the most common bug in long-running services.

**Always pin maps that must survive process restarts:**

```go
// Pin to /sys/fs/bpf — survives process restart, not system reboot
if err := objs.MyMap.Pin("/sys/fs/bpf/myapp_flows"); err != nil {
    log.Fatalf("pin failed: %v", err)
}

// On next startup: open the existing pin instead of creating a new map
pinned, err := ebpf.LoadPinnedMap("/sys/fs/bpf/myapp_flows", nil)
if err == nil {
    // reuse existing map — state preserved across restart
} else {
    // first run — map was created fresh by LoadObjects
}
```

Alternatively, use `LIBBPF_PIN_BY_NAME` in the BPF C definition so `cilium/ebpf` handles pin/open automatically.

**For the collector:** the `flows` hash map and the `rtt_histogram` map should be pinned. The `events` ring buffer should **not** be pinned — it is ephemeral by design.

---

## 2. Graceful Shutdown — Always Close in Order

Close in this strict order to avoid a kernel-side race where the BPF program writes to a map whose FD is already closing:

```go
// 1. Detach hooks (stops new kernel-side writes)
// 2. Drain the ring buffer / perf reader (flush pending events)
// 3. Close maps last (kernel ref count drops to zero)

func (c *Collector) Shutdown() {
    c.kprobe.Close()          // 1. detach kprobe
    c.tcHook.Close()          // 1. detach TC hook (if ePPing active)
    c.ringbufReader.Close()   // 2. unblocks Read() goroutine, drains remaining events
    c.objs.Close()            // 3. closes all maps + program FDs
    close(c.done)
}
```

Wire this to OS signal handling:

```go
sig := make(chan os.Signal, 1)
signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
go func() {
    <-sig
    collector.Shutdown()
}()
```

---

## 3. Ring Buffer — Handle Dropped Events

`BPF_MAP_TYPE_RINGBUF` (kernel ≥ 5.8) is preferred over `perf_event_array` for event streams. If user-space is slow, the kernel drops events and increments a counter rather than blocking the BPF program. Always track drops:

```go
for {
    rec, err := rd.Read()
    if errors.Is(err, ringbuf.ErrClosed) {
        return // clean shutdown
    }
    if err != nil {
        log.Warnf("ringbuf read error: %v", err)
        continue
    }
    if rec.LostSamples > 0 {
        // Export as Prometheus counter
        ebpfDroppedEvents.Add(float64(rec.LostSamples))
        log.Warnf("eBPF ring buffer dropped %d events — consider increasing max_entries", rec.LostSamples)
    }
    // process rec.RawSample ...
}
```

**Sizing rule:** `max_entries` (in bytes) should be at least `expected_event_rate_per_sec × max_processing_latency_s × event_size_bytes × 2`. For the TCP RTT collector at 10k connections/s with 32-byte events and 10ms processing budget: `10000 × 0.01 × 32 × 2 = 6400 bytes` → round up to `256 * 1024` (conservative).

---

## 4. Hash Map Overflow — Use LRU for Flow Tracking

Regular `BPF_MAP_TYPE_HASH` will **silently fail inserts** when full (`ENOSPC` returned to BPF program, invisible to user-space). For flow tracking maps that grow unboundedly, always use LRU:

```c
// BPF C: use LRU_HASH instead of HASH for flow tables
struct {
    __uint(type, BPF_MAP_TYPE_LRU_HASH);  // evicts LRU entry when full
    __uint(max_entries, 65536);
    __type(key,   struct flow_key);
    __type(value, struct flow_state);
} flow_table SEC(".maps");
```

Monitor fill rate periodically from Go (expensive — run every 60s, not in hot path):

```go
func monitorMapFill(m *ebpf.Map, name string) {
    info, _ := m.Info()
    var count uint32
    iter := m.Iterate()
    var k, v []byte
    for iter.Next(&k, &v) { count++ }
    ratio := float64(count) / float64(info.MaxEntries)
    if ratio > 0.80 {
        log.Warnf("BPF map %s is %.0f%% full — consider increasing max_entries", name, ratio*100)
    }
}
```

---

## 5. Batch Operations for Bulk Reads

For hash maps read on every collection cycle, batch operations are 10–50× faster than iterating key-by-key (one syscall per entry). Use `BatchLookup` for bulk reads and `BatchLookupAndDelete` to atomically read-and-reset counters:

```go
// Read all flow RTT entries in bulk
const batchSize = 256
keys   := make([]FlowKey, batchSize)
values := make([]FlowState, batchSize)
var cursor ebpf.MapBatchCursor

for {
    n, err := m.BatchLookup(&cursor, keys[:], values[:], nil)
    for i := 0; i < n; i++ {
        processFlow(keys[i], values[i])
    }
    if errors.Is(err, ebpf.ErrKeyNotExist) {
        break // end of map
    }
    if err != nil {
        log.Warnf("batch lookup error: %v", err)
        break
    }
}
```

Avoid `m.Iterate()` in collection hot paths — it holds a kernel-side iterator reference and makes one syscall per entry.

---

## 6. Live Config Updates Without BPF Reload

When you need to push new configuration (e.g. RTT threshold, probe interval) to the running BPF program without reloading it:

**Option A — Global variables** (ebpf-go v0.17+, 2024 — cleanest):

```c
// BPF C: declare as volatile const
volatile const __u32 rtt_threshold_us = 3000;
volatile const __u32 high_latency_ratio = 3;   // multiplier vs subnet baseline
```

```go
// Go: update live — no program reload needed
objs.TcprttVariables.RttThresholdUs.Set(5000)
objs.TcprttVariables.HighLatencyRatio.Set(4)
```

**Option B — Map-in-map swap** (for structured config, older kernels):

```go
// Write new config into shadow inner map, then atomically swap outer map reference
// This is the pattern Cilium uses for zero-downtime policy updates
newInner, _ := ebpf.NewMap(innerSpec)
populateConfig(newInner, newConfig)
outerMap.Put(uint32(0), newInner)
newInner.Close() // outer map now holds the only reference
```

---

## 7. Per-CPU Maps for High-Rate Counters

For counters updated on every packet/connection event, use `BPF_MAP_TYPE_PERCPU_ARRAY` to avoid inter-CPU cache-line contention. The BPF program writes to its local CPU slot; user-space aggregates:

```c
// BPF C
struct {
    __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
    __uint(max_entries, 1);
    __type(key,   __u32);
    __type(value, __u64);
} pkt_count SEC(".maps");

SEC("kprobe/tcp_close")
int BPF_KPROBE(tcp_close, struct sock *sk) {
    __u32 key = 0;
    __u64 *cnt = bpf_map_lookup_elem(&pkt_count, &key);
    if (cnt) __sync_fetch_and_add(cnt, 1);
    return 0;
}
```

```go
// Go: sum across all CPU slots
var perCPU []uint64
objs.PktCount.Lookup(uint32(0), &perCPU)
total := uint64(0)
for _, v := range perCPU { total += v }
```

Never use a regular `ARRAY` map for per-packet counters — false sharing across CPUs causes significant overhead at >1 Mpps.

---

## 8. Observability — Export Map Health as Prometheus Metrics

```go
// Expose these metrics from collector/metrics.go
ebpf_map_fill_ratio{map="flow_table"}          gauge   // 0.0–1.0
ebpf_ringbuf_dropped_total{map="events"}       counter // cumulative lost samples  
ebpf_kprobe_events_total                       counter // successful events processed
ebpf_map_batch_lookup_duration_seconds         histogram
```

This makes map overflow and drop events visible in Grafana (Phase 7 of the repository roadmap) without adding any overhead to the BPF hot path.

---

## Quick Reference

| Problem | Pattern |
|---|---|
| Map lost on process restart | Pin to `/sys/fs/bpf/` |
| Kernel writes to closing map | Close hooks → drain reader → close maps |
| Ring buffer overflow / dropped events | Log `LostSamples`; increase `max_entries`; export as counter |
| Hash map silently full | Use `LRU_HASH`; monitor fill ratio every 60s |
| Slow per-key iteration | Use `BatchLookup` / `BatchLookupAndDelete` |
| Config push without BPF reload | Global variables (ebpf-go v0.17+) or map-in-map swap |
| High-rate counters | `PERCPU_ARRAY` + user-space sum |
| Map health visibility | Export fill ratio + drop counter as Prometheus metrics |

---

## References

1. cilium/ebpf — pure-Go eBPF library, designed for long-running processes. https://github.com/cilium/ebpf
2. ebpf.io — Pinning concept and BPF filesystem. https://docs.ebpf.io/linux/concepts/pinning/
3. Tarazi, C. "Primer on eBPF Map Batch Operations." LPC 2024. https://www.youtube.com/watch?v=hKkVjiAUSfw
4. cilium/ebpf v0.17 release — Global variables, Decl Tags, package pin. https://github.com/cilium/ebpf/discussions/1632
5. Zhao et al. "Wasm-bpf: Streamlining eBPF Deployment in Cloud Environments." arXiv:2408.04856, 2024. https://arxiv.org/abs/2408.04856
6. Bertrone et al. "COP2: Continuously Observing Protocol Performance." arXiv:1902.04280, 2019. https://arxiv.org/abs/1902.04280
