# eBPF Deployment Constraints: Raspberry Pi/ARM and Containerized Environments
## Research Backlog Item — Gap #1 from `docs/gap-analysis/gap-analysis-collector-vs-standalone.md`

> **Status:** Research document. Closes the one topic previously flagged as short on *both* literature and validation ("eBPF passive RTT portability" in the gap analysis).
> **Scope:** What specifically breaks or needs verification when running the Phase 2 eBPF passive-RTT collector (`docs/collector/ROADMAP.md` Phase 2, kprobe on `tcp_close`, `cilium/ebpf` + `bpf2go`) on Raspberry Pi/ARM64 hardware and inside Docker containers, and the concrete graceful-fallback contract the collector must implement when these constraints are not met.

---

## Part 1 — ARM64/Raspberry Pi-Specific Constraints

### 1.1 BTF (`/sys/kernel/btf/vmlinux`) Is Not Guaranteed on Default Raspberry Pi OS Images

CO-RE (Compile Once – Run Everywhere) relocation, which the collector's `tcprtt.c` design depends on for cross-kernel portability, requires the kernel to expose BTF type information at `/sys/kernel/btf/vmlinux`. This requires `CONFIG_DEBUG_INFO_BTF=y` at kernel build time. As of late 2025, Raspberry Pi's own kernel engineers confirmed that although `CONFIG_HAVE_EBPF_JIT=y` is enabled by default, `CONFIG_DEBUG_INFO_BTF` is not, and enabling it increases the compressed kernel image size by roughly 17% (9.3 MB → 11 MB) and the full Debian kernel package by 32% — which is why Raspberry Pi has so far declined to enable it by default, leaving BTF generation as a custom-kernel-build requirement rather than an out-of-the-box guarantee [web:290]. This directly validates and quantifies the risk flagged in `docs/gap-analysis/research-guide-for-gap-topics.md` §6.2 ("check whether BTF is available... older Raspberry Pi OS images may not meet this").

**Practical implication for this project:** the collector cannot assume `/sys/kernel/btf/vmlinux` exists on a stock Raspberry Pi OS (Bookworm or otherwise) image. The existing runtime check in `docs/collector/ROADMAP.md`'s `initEBPF()` (`os.Stat("/sys/kernel/btf/vmlinux")`) is the correct approach, but the ROADMAP text describing this as an edge case understates how common it actually is on this specific hardware target — it should be treated as the *default* case for Raspberry Pi fleets, not an exception.

### 1.2 Kprobe/Tracepoint Program Types Have a History of Being Unavailable on ARM64 Kernels

`cilium/ebpf`'s own arm64 support was best-effort (not covered by CI) until December 2023 (PR #1245) [web:287]. Testing on a real Raspberry Pi 4 running an ALARM (Arch Linux ARM) kernel build found `bpftool feature probe` reporting `kprobe`, `tracepoint`, `perf_event`, `raw_tracepoint`, and several map types (`XSKMap`, `InodeStorage`, `TaskStorage`) as **not available**, despite the running kernel version nominally being new enough to support them — indicating the *distribution's specific kernel build configuration*, not just the kernel version number, determines availability [web:287]. This means version-only compatibility checks (e.g., "kernel ≥ 5.6") are insufficient; the collector must probe actual feature availability at runtime.

**Practical implication:** the collector's graceful-degradation check (§3 below) must call `features.HaveProgType(ebpf.Kprobe)` from `cilium/ebpf`'s `features` package (the Go equivalent of `bpftool feature probe`) rather than relying solely on a kernel-version string comparison or the BTF file-existence check alone. A kernel can expose BTF and still lack kprobe program-type support, and vice versa.

### 1.3 Current State (2025-2026) Is Substantially Better Than the 2021 Findings, But Verification Is Still Required Per-Image

The arm64 kprobe example failures reported in 2021 (`error while loading objects: field KprobeExecve: program kprobe_execve: load program without BTF: invalid argument`) were traced partly to running without root privileges and partly to genuine kernel-build gaps, and were substantially fixed upstream by mid-2023 [web:287]. `cilium/ebpf`'s official requirements now state Linux arm64 is tested in CI against kernel.org LTS releases ≥4.4, on par with amd64 [web:293]. This means the *library* is no longer the blocker for modern Raspberry Pi kernels (6.1+, as shipped with current Raspberry Pi OS Bookworm) — the blocker is specifically the BTF-generation gap in §1.1, which is a Raspberry Pi Foundation kernel-configuration decision, not a `cilium/ebpf` limitation.

### 1.4 Fallback for Missing BTF: BTFHub / Prebuilt BTF Files

Where a target kernel lacks embedded BTF, tools such as Aqua Security's Tracee document two supported paths: either the running kernel exposes `/sys/kernel/btf/vmlinux` natively, or the loader falls back to a prebuilt BTF file sourced via BTFHub, matched to the exact kernel version/build [web:304]. This is a viable secondary mitigation for Raspberry Pi fleets where enabling `CONFIG_DEBUG_INFO_BTF` via a custom kernel build (per §1.1) is not acceptable, but it adds a fleet-inventory burden (tracking exact kernel build strings per device) that should be weighed against simply building a custom kernel image for the fleet if eBPF is a hard requirement.

---

## Part 2 — Container/Docker-Specific Constraints

### 2.1 Capability Model: `CAP_BPF` + `CAP_PERFMON`, Not `CAP_SYS_ADMIN`, on Kernel ≥5.8

Before Linux 5.8, all BPF operations (loading programs, creating maps, attaching probes) were gated behind the single broad `CAP_SYS_ADMIN` capability. Since 5.8, this has been split into fine-grained capabilities: `CAP_BPF` is required for every `bpf()` syscall (loading programs, map access) unless the caller already has `CAP_SYS_ADMIN` or unprivileged BPF is enabled; `CAP_NET_ADMIN` is additionally required to attach network-facing programs (TC, XDP); and `CAP_PERFMON` is additionally required to attach tracing programs (kprobes, uprobes, raw tracepoints) [web:218][web:306]. For the collector's `tcp_close` kprobe design specifically, this means the minimum viable capability set is **`CAP_BPF` + `CAP_PERFMON`** (kprobe attach), not `CAP_NET_ADMIN` alone — the ROADMAP's existing capability table correctly lists `CAP_BPF`+`CAP_NET_ADMIN`+`CAP_PERFMON` together, which is the right superset if both the kprobe (Approach A) and the TC-hook ePPing (Approach B) paths are both to be supported by the same binary.

### 2.2 `RLIMIT_MEMLOCK` Matters Only Below Kernel 5.11

Falco's own least-privilege documentation confirms that `CAP_SYS_RESOURCE` (to raise `RLIMIT_MEMLOCK`) is needed only on kernels below 5.11, because BPF map/program memory accounting moved to memory cgroups starting with 5.11, making the memlock rlimit irrelevant afterward [web:301]. The collector's existing `rlimit.RemoveMemlock()` call (already in the ROADMAP's `initEBPF()` sketch) is a no-op on 5.11+ kernels but remains necessary for correctness on the mixed fleet (Raspberry Pi OS Bookworm ships kernel 6.1, comfortably above 5.11, but some VPS/legacy Debian 11 nodes may not be) — retain the call rather than removing it, since it is harmless on newer kernels and required on older ones.

### 2.3 `CAP_BPF` Is Sometimes Not Correctly Recognized by the Container Runtime, Requiring `CAP_SYS_ADMIN` as a Fallback

Falco's own capability audit explicitly warns that "depending on the version of the container runtime of choice, `CAP_BPF` could not be correctly recognized. Unfortunately in this case, `CAP_SYS_ADMIN` is required instead" [web:301]. This is a real, documented deployment risk, not a theoretical one, and means the collector's Docker/Kubernetes deployment documentation should specify a minimum tested container-runtime version (e.g., containerd ≥1.6, Docker Engine ≥20.10) alongside the capability list, and should document `CAP_SYS_ADMIN` as an explicit (undesirable but working) fallback for older runtimes rather than leaving operators to discover the failure mode themselves.

### 2.4 `--privileged` and Full `CAP_SYS_ADMIN` Remain the De Facto Fallback Across Multiple eBPF Tools

Independent of runtime quirks, Aqua Security's Tracee documents the same two-tier model as this project's own ROADMAP: `CAP_BPF`+`CAP_PERFMON` for kernels ≥5.8, or `CAP_SYS_ADMIN` for older kernels, and notes `CAP_IPC_LOCK` may additionally be required "on some environments (e.g. Ubuntu)" — with `--privileged` offered as the simplest (least secure) alternative [web:304]. This cross-validates the project's existing capability table and confirms `CAP_IPC_LOCK` as a previously undocumented environment-specific addition worth testing for on Ubuntu-based collector nodes specifically.

### 2.5 AppArmor: Explicit Profile Requirement on Ubuntu-Family Hosts

Falco's official container deployment guide states plainly that "if you are running Falco on a system with the AppArmor LSM enabled (e.g. Ubuntu), you must" apply a specific unconfined or custom AppArmor profile, even when using the driverless "Modern eBPF" mode that requires no out-of-tree kernel module [web:294]. Debian and Raspberry Pi OS do not enable AppArmor by default, but any Ubuntu-based collector node (a stated deployment target in this project) will need this explicitly addressed — the Docker Compose pattern in `docs/collector/ROADMAP.md` already sets `security_opt: no-new-privileges:true`, but does not yet address AppArmor confinement, which is a gap this document flags for that file.

### 2.6 `hostNetwork`/`network_mode: host` and `hostPID`/`pid: host` Are Correctly Identified as Mandatory in the Existing ROADMAP

The existing `docs/collector/ROADMAP.md` Phase 2d already correctly states that TC hooks and kprobes require host network and host PID namespaces respectively, because BPF maps and kprobes observe the *host* kernel, not a container-scoped view. This is consistent with every external source reviewed for this document and required no correction — it is called out here only to confirm it does not need re-validation.

### 2.7 Kernel Lockdown Mode Can Silently Break eBPF Even When Capabilities Are Correct

A frequently overlooked constraint is Linux kernel lockdown mode (available since kernel 5.4): if a host has lockdown enabled in "confidentiality" mode, BPF is blocked entirely regardless of granted capabilities, whereas "integrity" mode is compatible with eBPF [web:313]. This is a host-level setting (`/sys/kernel/security/lockdown`) outside the container's control, and the collector's fallback logic should check this file's contents as an additional pre-flight condition beyond BTF and capability checks, since a misconfigured host would otherwise produce a confusing failure that looks like a capability problem but is not.

---

## Part 3 — Revised Graceful-Degradation Contract

The existing `initEBPF()` sketch in `docs/collector/ROADMAP.md` Phase 2d checks OS, BTF file existence, and memlock rlimit removal, in that order. Based on the findings above, this check sequence should be extended:

```go
func (c *Collector) initEBPF() {
    if runtime.GOOS != "linux" {
        log.Info("eBPF disabled: non-Linux OS")
        return
    }
    if lockdown, err := os.ReadFile("/sys/kernel/security/lockdown"); err == nil {
        if strings.Contains(string(lockdown), "[confidentiality]") {
            log.Info("eBPF disabled: kernel lockdown mode is 'confidentiality' — BPF blocked at host level")
            return
        }
    }
    if _, err := os.Stat("/sys/kernel/btf/vmlinux"); err != nil {
        log.Info("eBPF disabled: BTF not available (common on stock Raspberry Pi OS — CONFIG_DEBUG_INFO_BTF unset by default; see docs/ebpf-deployment-constraints.md §1.1). Falling back to active ICMP.")
        return
    }
    // Feature-probe, not just kernel-version check — a kernel can expose BTF
    // and still lack kprobe program-type support (see §1.2).
    if haveKprobe, err := features.HaveProgType(ebpf.Kprobe); err != nil || !haveKprobe {
        log.Info("eBPF disabled: kprobe program type unavailable on this kernel build")
        return
    }
    if err := rlimit.RemoveMemlock(); err != nil {
        log.Info("eBPF disabled: cannot remove memlock rlimit (missing CAP_BPF or CAP_SYS_RESOURCE, kernel < 5.11)")
        return
    }
    stop, err := ebpf.StartTCPRTTCollector(c.rttEvents)
    if err != nil {
        log.Warnf("eBPF startup failed: %v — falling back to active ICMP", err)
        return
    }
    c.ebpfStop = stop
    log.Info("eBPF TCP RTT collector active")
}
```

The two additions relative to the existing ROADMAP sketch are the kernel-lockdown pre-check (§2.7) and the explicit kprobe feature-probe via `cilium/ebpf`'s `features` package (§1.2), both added *before* the memlock-removal step so the log messages correctly attribute the actual blocking cause rather than surfacing a downstream error.

---

## Part 4 — Recommendations for This Project's Fleet

1. **Treat missing BTF as the expected default on stock Raspberry Pi OS**, not an edge case — either commit to building and distributing a custom Raspberry Pi kernel with `CONFIG_DEBUG_INFO_BTF=y` (accepting the ~17% kernel image size increase [web:290]) for any Pi expected to run the eBPF module, or budget for BTFHub-sourced prebuilt BTF files matched per exact kernel build [web:304], or accept that Raspberry Pi nodes fall back to active ICMP-only monitoring indefinitely.
2. **Add a runtime kprobe feature-probe, not just a BTF/kernel-version check**, since ARM64 kernel builds have historically diverged from x86_64 in program-type availability independent of the reported kernel version [web:287].
3. **Document a minimum container-runtime version for Docker/Kubernetes deployments** and explicitly note `CAP_SYS_ADMIN` as a documented (not silent) fallback when `CAP_BPF` is not recognized by an older runtime [web:301].
4. **Add an AppArmor profile note to the Docker Compose deployment pattern** in `docs/collector/ROADMAP.md` for Ubuntu-based collector nodes specifically, since Debian/Raspberry Pi OS nodes are unaffected but Ubuntu nodes are a stated deployment target [web:294].
5. **Add a kernel-lockdown-mode pre-flight check** to the graceful-degradation logic, since this failure mode is otherwise indistinguishable from a capability misconfiguration and would waste debugging time [web:313].
6. **Re-run the arm64 CI-status check periodically** — `cilium/ebpf` arm64 support materially improved between 2021 and 2023 [web:287][web:293], so this document's findings should be revisited if the collector's `cilium/ebpf` dependency is upgraded across a major version boundary.

---

## References

1. Raspberry Pi Forums. "Enable ebpf in Pi OS (as a default)?" 2025-2026 thread, Raspberry Pi engineering staff response on `CONFIG_DEBUG_INFO_BTF` and kernel image size impact. https://forums.raspberrypi.com/viewtopic.php?t=391384
2. cilium/ebpf GitHub. Issue #266, "CI: test on arm64" — documents 2021 kprobe/BTF/program-type failures on Raspberry Pi 4 and their resolution by PR #1245 (Dec 2023). https://github.com/cilium/ebpf/issues/266
3. cilium/ebpf GitHub. Repository README, platform support statement (arm64 CI parity with amd64, kernel ≥4.4). https://github.com/cilium/ebpf
4. ebpf.io / docs.ebpf.io. "BPF Token" — capability model history: `CAP_SYS_ADMIN` pre-5.8, `CAP_BPF`+`CAP_NET_ADMIN`/`CAP_PERFMON` post-5.8. https://docs.ebpf.io/linux/concepts/token/
5. Falco Project. "Falco least privileged notes" — capability requirements (`CAP_BPF`, `CAP_PERFMON`, `CAP_SYS_RESOURCE`, `CAP_SYS_PTRACE`), memlock rlimit kernel-version dependency, runtime `CAP_BPF` recognition caveat. https://hackmd.io/@isi99rg1RUG_ltHakQfsug/rkRDx6EWc
6. Falco Project. "Deploy as a container." AppArmor profile requirement on Ubuntu-family hosts for the eBPF driver. https://falco.org/docs/setup/container/
7. Aqua Security. Tracee documentation, "Prerequisites" — capability model, BTF/BTFHub fallback path. https://aquasecurity.github.io/tracee/v0.7.0/install/prerequisites/
8. Security StackExchange. "How to keep data in eBPF maps secure" — capability semantics for `CAP_BPF`/`CAP_NET_ADMIN`/`CAP_PERFMON`/`CAP_SYS_ADMIN`. https://security.stackexchange.com/questions/263438/how-to-keep-data-in-ebpf-maps-secure
9. OneUptime. "How to Secure Calico eBPF Mode" — kernel lockdown mode compatibility (`integrity` vs `confidentiality`) with eBPF. https://oneuptime.com/blog/post/2026-03-13-secure-calico-ebpf-mode/view
