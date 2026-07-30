# Topic 7: ARP-Rate / Broadcast-Storm Thresholds (Collector Phase 3)


> **Language note (2026-07-30):** this research note predates the 2026-07-25 decision to
> write the v2 collector in Python (`docs/collector/SUGGESTIONS.md` §2). File names below
> are the Python modules; the findings themselves are language-independent.

**Status:** Literature reviewed (Brügge & Simon 2024). Baseline collection query written. Threshold derivation requires 7+ days of live ARP data — pending.

---

## Brügge & Simon 2024 — Key Findings

**Citation:** Brügge, M. & Simon, M. "Link Failure Detection in Computer Networks." NET-2024-04-1, TU Munich, 2024.

### Relevant Findings
- ARP storms are identified as a **symptom** of link failure or misconfiguration, not a root cause
- The paper does not provide a numeric ARP-rate threshold — it documents ARP-storm detection as an open problem for small/medium network sizes
- For anomaly detection, the paper recommends **local baseline derivation** rather than universal constants, because ARP rates vary significantly by:
  - Network segment size (more hosts → more gratuitous ARPs)
  - Traffic pattern (game servers, backups, and DHCP renewals all spike ARP rates)
  - OS behaviour (Windows gratuitous ARP on IP assignment, Linux arp_announce settings)

### Why a Universal Constant is Wrong for This Project
- A busy game server segment (Arma Reforger with multiple clients) may generate 50–100 ARP/min during session start — this is normal, not an attack
- A backup job starting at 02:00 may cause temporary ARP-cache churn across multiple hosts
- A threshold of e.g. "> 30 ARP replies/min" would be meaningless without knowing this project's baseline

---

## ARP Rate Collection

### Method 1: Via `ip neigh` polling (existing monitor infrastructure)
```bash
# Sample ARP table size every 30s; log changes
watch -n 30 'ip neigh show | wc -l'

# Or via /proc/net/arp
cat /proc/net/arp | grep -v "^IP" | wc -l
```

### Method 2: Via tcpdump/passive capture
```bash
# Count ARP replies per minute on interface eth0
tcpdump -i eth0 -n 'arp[6:2] == 2' 2>/dev/null | \
  awk '{print strftime("%Y-%m-%dT%H:%M"), $0}' | \
  sort | uniq -c -f1
```

### Method 3: Via existing `scripts/l2-health.sh` (already in repo)
The existing `l2-health.sh` script already collects ARP/neighbour data. Extend it to log timestamped ARP reply counts to a CSV:
```bash
# Add to l2-health.sh output:
ARP_COUNT=$(cat /proc/net/arp | grep -c -v '^IP')
echo "$(date -Iseconds),$ARP_COUNT" >> /var/log/arp-baseline.csv
```

---

## Threshold Derivation Algorithm

After collecting ≥7 days of ARP rate data (samples every 30s → ~20,160 samples):

```python
import pandas as pd
import numpy as np

df = pd.read_csv('/var/log/arp-baseline.csv', names=['timestamp','arp_count'])
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Compute per-minute rate (delta of arp_count samples)
df['arp_rate_per_min'] = df['arp_count'].diff() * 2  # ×2 because 30s sample = 2/min
df = df[df['arp_rate_per_min'] >= 0]  # remove negatives (cache eviction)

# Per-IP breakdown requires pcap; ARP table size is a proxy
mean_rate = df['arp_rate_per_min'].mean()
std_rate = df['arp_rate_per_min'].std()

# Set threshold at mean + 3σ (99.7% of normal traffic below this)
threshold_N = mean_rate + 3 * std_rate
print(f'ARP anomaly threshold: {threshold_N:.1f} ARP replies/min')
print(f'(mean={mean_rate:.1f}, std={std_rate:.1f}, 7-day baseline)')
```

This threshold value is what gets hard-coded into `collector/checks/net_arp_watch.py` — **not an arbitrary constant**.

---

## Network-Segment Considerations for This Deployment

| Segment | Expected ARP baseline | Known spikes |
|---|---|---|
| Home LAN (primary) | Low (5–15 hosts, 10–30 ARP/min) | Game server start, backup jobs |
| Raspberry Pi cluster | Very low (static IPs, 3–5 ARP/min) | None expected |
| Routed VPS segment | Near zero (not a shared broadcast domain) | N/A — observe the local L2 segment instead |
| OT segment (if present) | Very low (static addressing, < 5 ARP/min) | DHCP lease renewal only |

Document actual measured baselines per segment after 7-day collection.

---

## Exit Criteria Status

- [ ] 7+ days of ARP rate data collected (via extended `l2-health.sh` or dedicated collection)
- [ ] Per-segment mean and standard deviation computed
- [ ] Anomaly threshold N = mean + 3σ calculated and documented per segment
- [ ] Threshold validated against known-busy periods (game server sessions, backup runs)
- [ ] Threshold N committed to `collector/checks/net_arp_watch.py` with derivation comment referencing this document

## Next Implementation Step

Extend `scripts/l2-health.sh` to log ARP counts with timestamps. After 7-day collection, run the derivation script above. Then implement `collector/checks/net_arp_watch.py` using the derived threshold.
