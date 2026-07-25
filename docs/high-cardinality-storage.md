# Optimizing Data Storage Structures for High-Cardinality Metrics
## New Research Backlog Topic — Basis for `monitor/`'s SQLite schema and future `collector` metrics store

> **Status:** Research document, newly added to the backlog alongside adaptive thresholding and fault-tree analysis.
> **Scope:** How to structure per-target, per-hop, per-interface time-series storage so that adding monitored targets, hops, or interfaces does not degrade write throughput or query latency — directly relevant once collector-parity features (per-hop mtr data, per-interface error counters, SNMP per-OID series) are added to a system that today stores relatively few series.

---

## Part 1 — Why Cardinality Is the Actual Risk, Not Raw Volume

Cardinality is the count of unique `(metric_name, label_set)` combinations tracked by a store; a single metric with a `target_ip` label has cardinality equal to the number of monitored targets, and adding a `hop_index` label for mtr-style multi-hop tracing multiplies that by the average path length (Netdata Academy, 2026, "Metric Cardinality in Observability"). The core mechanism by which this becomes expensive is the **inverted index**: systems like Prometheus, Mimir, Thanos, and OpenTSDB maintain an index from every `(label_key, label_value)` pair back to the series it appears in, so cardinality growth inflates the index (and therefore RAM) roughly linearly, independent of how well the raw sample values themselves compress (Netdata blog, 2026, "High-cardinality metrics at scale"). For this project specifically, the roadmapped collector-parity features (per-hop RTT/loss for `mtr` tracing, per-OID SNMP series, per-interface counters) are exactly the kind of label expansion that turns a currently modest cardinality into a much larger one, so this should be designed for before those features are added, not retrofitted after.

---

## Part 2 — Concrete Design Levers, Ranked by Applicability to This Project's Scale

### 2.1 Normalize Series Identity Into a Separate Metadata Table

An empirical comparison (InfoQ, 2026, "Time-Series Storage: Design Choices That Shape Cost") found that normalizing series identity (target IP, hop index, interface name, etc.) into a separate dimension/metadata table and referencing it by a compact integer key — rather than repeating the full label strings on every sample row — reduced storage by approximately 42% in their experiment. This is directly applicable to the standalone monitor's current SQLite-based storage: a `targets` table (id, ip, hostname, type) and a `hops` table (id, target_id, hop_index) referenced by integer foreign key from the samples table, rather than storing IP strings or hop descriptions repeated on every row.

**Caveat from the same source:** this normalization gain collapses once the number of unique dimension combinations approaches the number of rows — i.e., if `hop_index` combined with a fast-changing dynamic route makes nearly every row's dimension-set unique, normalization stops helping and cardinality itself is the problem, not row repetition.

### 2.2 Keep High-Cardinality/Unbounded Fields Out of Series Identity

The consistent guidance across multiple sources (InfoQ 2026; Netdata Academy 2026; LeanStudy "Time-Series Databases" guide) is to never use unbounded-cardinality values (session IDs, request IDs, arbitrary hostnames from DHCP, ephemeral container IDs) as first-class indexed tags/labels; keep them as row-level fields/columns instead, or push them to a separate log-style store. For this project this specifically means: if OT/IoT device discovery is added (as roadmapped) and device hostnames are attacker-influenced or DHCP-hostname-derived, they should not become an indexed series label directly — use the stable MAC address or a project-assigned device ID as the indexed identity, with the raw hostname stored as an unindexed attribute.

### 2.3 Time-Based Partitioning With a Secondary Series-Identity Axis

Standard practice (Prometheus 2h blocks; InfluxDB per-shard time intervals; TimescaleDB hypertables) is to partition on time first, enabling O(1) expiration by dropping whole partitions rather than row-by-row deletes. However, the InfoQ 2026 analysis notes that time-only partitioning creates a **write hotspot on the current time window** as target/hop count grows; adding a second partitioning axis on series identity (e.g., hash of target_id) distributes writes and narrows read scans. For the project's current SQLite-based standalone monitor, this maps to: partition/rotate the samples table (or use separate database files) by day, and within a day, consider sharding by target-ID hash if write contention becomes measurable — a lower priority than time-partitioning alone until scale actually requires it.

### 2.4 Downsampling and Tiered Retention (Highest-Value, Lowest-Effort Lever)

Across every source reviewed, downsampling is described as the single highest-leverage lever: keep raw per-second/per-probe samples for a short hot window (days), 1-minute or 5-minute aggregates for a mid-term window (weeks), and hourly aggregates for long-term trend storage (months to a year) (Netdata Academy 2026; technori.com 2025 observability TSDB design guide). The InfoQ 2026 experiment measured a 720x row-count reduction downsampling from 5-second to 1-hour resolution. This is the most directly and immediately applicable recommendation for the standalone monitor's existing SQLite schema, and should be prioritized ahead of the partitioning/sharding items above, which only matter at a scale the project has likely not yet reached.

### 2.5 Compression Techniques (Relevant Mainly If Migrating Off SQLite)

If the project ever migrates from SQLite to a dedicated TSDB (Prometheus remote-write target, VictoriaMetrics, etc.), the standard compression techniques — delta-of-delta timestamp encoding and XOR/Gorilla encoding for float values (Netdata Academy 2026; LeanStudy guide) — provide the 10–100x compression ratios that make raw per-second retention affordable at all. This is flagged as a **future consideration**, not an immediate action item, since SQLite does not natively support these encodings and retrofitting them would require either a custom storage layer or an actual database migration.

### 2.6 Cardinality Telemetry (Detect Runaway Growth Before It's a Production Incident)

Both the Netdata Academy (2026) and "High-cardinality metrics at scale" sources recommend emitting the store's own series-count and label-value-histogram as a monitored metric, specifically so a runaway cardinality growth (e.g., a bug that turns a bounded field into an effectively unbounded one) is caught as an alert rather than discovered later as a storage/performance incident. This is a cheap, high-value addition once any of §2.1–§2.3 are implemented — track `SELECT COUNT(DISTINCT target_id, hop_index) FROM samples` (or equivalent) as a self-monitoring metric.

---

## Part 3 — Recommended Priority Order for This Project

1. Downsampling/tiered retention (§2.4) — highest value, works within the existing SQLite schema with no architecture change.
2. Normalize series identity into metadata tables (§2.1) — needed specifically before adding per-hop (`mtr`) and per-OID (SNMP) series, both roadmapped.
3. Exclude unbounded fields from indexed identity (§2.2) — needed specifically before OT/IoT device discovery is added.
4. Cardinality self-monitoring (§2.6) — cheap, add alongside item 2.
5. Time+identity dual-axis partitioning (§2.3) and dedicated-TSDB compression (§2.5) — defer until write-contention or storage-cost data actually justifies the added complexity.

---

## Part 4 — Implementation Checklist

| Item | File | Status |
|---|---|---|
| Add hot/warm/cold downsampling tiers to the existing SQLite schema | `monitor/db.py` (or equivalent schema module) | Add when building |
| Normalize target/hop/interface identity into metadata tables with integer FKs | `monitor/db.py` schema | Add before per-hop/SNMP collector-parity features ship |
| Use MAC/stable device ID, not raw hostname, as indexed identity for discovered OT/IoT devices | device-discovery module (roadmapped) | Add when building discovery |
| Emit distinct-series-count as a self-monitoring metric | `monitor/` aggregator | Add alongside metadata normalization |

---

## References

1. Netdata Academy. "Metric Cardinality in Observability: Strategies." 2026. https://www.netdata.cloud/academy/metric-cardinality-in-observability/
2. Netdata. "High-cardinality metrics at scale: why the standard advice solves the wrong problem." 2026. https://www.netdata.cloud/blog/high-cardinality-metrics-observability-scale/
3. InfoQ. "Time-Series Storage: Design Choices That Shape Cost and Query Performance." 2026. https://www.infoq.com/articles/time-series-storage-design/
4. LeanStudy. "Time-Series Databases — System Design Fundamentals." https://leanstudy.app/system-design/fundamentals/45-time-series-databases/
5. technori.com. "How to design time-series databases for observability systems." 2025. https://technori.com/news/design-time-series-databases-for-observability-systems/
