# Topic 6: Passive eBPF RTT Layer (Collector Phase 2)

**Status:** Literature reviewed (Sundberg 2024). Compatibility matrix populated from known fleet versions. Prototype requires live Raspberry Pi access — pending.

---

## Sundberg 2024 — epping Design Summary

**Citation:** Sundberg, S. "Towards Ubiquitous and Continuous Network Latency Monitoring." Karlstad University Licentiate Thesis, 2024. DOI: 10.59217/xpyc8728.

### epping Architecture
- Attaches a BPF program at the **TC (Traffic Control) egress hook** on the monitored interface
- Matches outgoing ICMP Echo Request packets, records `{flow_id, seq, timestamp}` in a **BPF hash map**
- On incoming ICMP Echo Reply, computes RTT = `reply_timestamp - stored_request_timestamp`
- Exports RTT samples via BPF ring buffer → userspace Go reader (`cilium/ebpf`)
- Does NOT inject traffic — purely passive observation of existing probe traffic

### Hook Choice: TC vs. XDP
| Hook | Kernel entry point | Requires hardware offload? | Works in Docker? |
|---|---|---|---|
| XDP | Before sk_buff allocation | Optional (native/generic modes) | Depends on veth/bridge setup |
| TC (egress) | After routing, before NIC TX | No | Yes (works on veth pairs) |

TC egress is the **safer choice for this project** — works inside Docker containers on standard veth pairs without hardware support requirements.

### BPF Map Layout
```c
// Key: flow identifier (src_ip, dst_ip, icmp_seq)
struct flow_key {
    __u32 src_ip;
    __u32 dst_ip;
    __u16 icmp_seq;
    __u16 pad;
};
// Value: TX timestamp (nanoseconds since boot, ktime)
struct flow_val {
    __u64 tx_ktime_ns;
};
// Map type: BPF_MAP_TYPE_HASH, max_entries: 1024 (sufficient for 5-15 targets)
// Cleanup: entries removed on reply match; stale entries (> 5s) purged by userspace
```

---

## Target Hardware Compatibility Matrix

| Platform | Kernel version | CAP_BPF available? | CAP_NET_ADMIN available? | epping ≥5.6 requirement | Status |
|---|---|---|---|---|---|
| Raspberry Pi OS (Bookworm) | 6.1.x | Yes (kernel 5.8+) | Yes | ✅ Met | **Supported** |
| Raspberry Pi OS (Bullseye) | 5.15.x | Yes (kernel 5.8+) | Yes | ✅ Met | **Supported** |
| Raspberry Pi OS (Buster/Legacy) | 5.10.x | Partial (5.8+) | Yes | ✅ Met | **Supported (verify)** |
| Raspberry Pi OS (Legacy pre-2020) | 4.19.x | No (< 5.6) | Yes | ❌ Not met | **NOT supported** |
| Ubuntu 22.04 VPS | 5.15.x / 6.x | Yes | Yes | ✅ Met | **Supported** |
| Ubuntu 20.04 VPS | 5.4.x | No (< 5.6) | Yes | ❌ Not met | **NOT supported** |
| Docker container (default seccomp) | Inherits host | Blocked by seccomp | Blocked | Requires `--cap-add` | **Requires explicit capability grant** |
| Docker container (privileged) | Inherits host | Yes | Yes | ✅ Met (if host ≥ 5.6) | **Supported** |

> **Action required:** Run `uname -r` on each Raspberry Pi in the fleet and confirm against this matrix. Update the table with actual measured kernel versions.

### Capability Check Commands
```bash
# Check kernel version
uname -r

# Check if CAP_BPF is available (kernel >= 5.8)
cat /proc/sys/kernel/unprivileged_bpf_disabled
# 0 = unprivileged BPF allowed, 1 = root-only, 2 = disabled

# Check if TC eBPF loading works (requires root or CAP_NET_ADMIN + CAP_BPF)
ip link show  # basic connectivity check
bpftool prog list 2>/dev/null || echo "bpftool not available"

# In Docker: check effective capabilities
cat /proc/self/status | grep CapEff
```

---

## Graceful Fallback Behavior (Required)

Per `research-guide-for-gap-topics.md` §6.4, the collector MUST disable eBPF cleanly rather than crash when capabilities are absent.

### Fallback Decision Tree
```
startup:
  attempt_ebpf_load():
    if kernel_version < 5.6:
      log.Warn("eBPF RTT passive layer disabled: kernel < 5.6")
      set ebpf_enabled = false
      return
    if CAP_BPF not available:
      log.Warn("eBPF RTT passive layer disabled: CAP_BPF not granted")
      set ebpf_enabled = false
      return
    if CAP_NET_ADMIN not available:
      log.Warn("eBPF RTT passive layer disabled: CAP_NET_ADMIN not granted")
      set ebpf_enabled = false
      return
    load_bpf_program():
      if error:
        log.Error("eBPF RTT load failed: %v — falling back to active-only mode", err)
        set ebpf_enabled = false
        return
    set ebpf_enabled = true
    log.Info("eBPF RTT passive layer active on interface %s", iface)

collect_rtt():
  if ebpf_enabled:
    return ebpf_rtt_samples()
  else:
    return nil  // active ICMP probe RTT used instead
```

This fallback must be covered by a unit test that mocks the capability check functions.

---

## Prototype Steps (Requires Raspberry Pi Access)

1. Clone epping source (Apache-2.0): `git clone https://github.com/csperkins/epping`
2. Vendor the BPF C source into `collector/ebpf/epping.bpf.c`
3. Compile: `clang -target bpf -O2 -c epping.bpf.c -o epping.bpf.o`
4. Load via `cilium/ebpf` in a throwaway `cmd/ebpf-test/main.go`
5. Run `ping 8.8.8.8` in background; verify epping ring buffer emits RTT samples
6. Confirm RTT samples match active ICMP probe RTT within ±2ms
7. Test graceful fallback: run as unprivileged user, confirm log warning not crash

---

## Exit Criteria Status

- [ ] Kernel version confirmed on each Raspberry Pi in fleet (table above updated)
- [ ] CAP_BPF + CAP_NET_ADMIN availability confirmed in deployment mode (bare systemd vs. Docker)
- [ ] Working prototype on at least one real Raspberry Pi: epping loads, emits RTT samples
- [ ] Graceful fallback tested: unprivileged run logs warning, collector continues in active-only mode
- [ ] `docs/theory/ebpf/ebpf-deployment-constraints.md` updated with measured kernel versions

## Next Implementation Step

Complete prototype on Raspberry Pi (Step 6.3). Then integrate into `collector/main.go` behind the capability-check fallback gate. Create `collector/ebpf/` package with the BPF C source vendored.
