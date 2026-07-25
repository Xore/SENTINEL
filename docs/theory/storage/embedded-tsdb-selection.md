# Embedded TSDB Selection: SQLite WAL vs. Purpose-Built Storage

> **Status:** Open research / implementation guide  
> **Scope:** `monitor/` backend storage engine for probe time-series data  
> **Related:** `docs/research-guide-for-gap-topics.md` §9, `ROADMAP.md` §Open Research Questions  
> **Reference architecture:** Pelkonen et al. "Gorilla: A Fast, Scalable, In-Memory TSDB."
> VLDB 2015 — already cited in `docs/theory/probes/gorilla-compression-go-theory.md`

---

## 1. Problem Statement

The `monitor/` component currently uses SQLite (WAL mode) as its persistent store.
At the current probe rate (one collector, ≤ 200 metrics/s), SQLite is adequate.
Two growth scenarios make the current choice non-obvious:

1. **Multi-collector deployment:** If multiple collector nodes (Pi4, VPS, laptop)
   push concurrently, the aggregate ingest rate approaches or exceeds 1 000 metrics/s.
2. **High-resolution probing:** Enabling per-second ICMP probing on 10+ targets +
   interface counters + OS health already produces ~500 metrics/s per collector.

This document characterises the SQLite write-throughput ceiling, describes the
crossover conditions under which a purpose-built TSDB becomes appropriate, and
documents the evaluated alternatives.

---

## 2. SQLite WAL Write Throughput

### 2.1 Empirical Ceiling

SQLite in WAL mode achieves significantly higher write throughput than the default
journaling mode. Measured throughput on real hardware (2023–2025 benchmarks):

| Platform | WAL + default sync | WAL + SYNCHRONOUS=NORMAL | WAL + in-memory |
|---|---|---|---|
| M1 MacBook Air | 14 401 writes/s | 113 684 writes/s | 981 836 writes/s |
| Linux Ampere ARM (Hetzner CAX31) | 3 316 writes/s | — | — |
| Generic x86 Linux | 5 542 writes/s | 80 145 writes/s | 952 380 writes/s |

Source: marending.dev SQLite benchmarks, December 2023.

**Important caveats for time-series workloads:**

- These numbers are for *single-row inserts* in a tight loop. Real time-series inserts
  include index updates (timestamp + target composite index), which reduce throughput.
  The benchmark's "WAL + Index (mixed 80% write)" scenario shows 22 801–59 111 writes/s
  — the most representative scenario for the probe database schema.
- WAL mode uses a single writer. Multiple concurrent writer goroutines **do not** scale
  linearly; each must acquire the write lock. At ≥ 3 concurrent collectors writing via
  the same SQLite file over NFS or a network mount, WAL degrades to near-serialised
  performance.
- `SYNCHRONOUS=NORMAL` trades crash-safety (data loss on OS crash, not SQLite crash)
  for 5–15× higher throughput. Acceptable for probe metrics; unacceptable for
  financial or audit data.

### 2.2 Crossover Point Estimate

For the `analyseLaptop` schema (approximate):
- Each metric write = 1 INSERT into `probe_samples` (timestamp, collector_id, check_type,
  target, value) + 1 index update = ~2 disk operations.
- At WAL + SYNCHRONOUS=NORMAL on a Raspberry Pi 4 (ARM): expect ~15 000–25 000
  writes/s practical ceiling (Pi 4 SD card I/O is the real bottleneck, not CPU).
- At 1 000 metrics/s aggregate, the Pi 4 is comfortably within ceiling.
- At 5 000 metrics/s (5 collectors × 1 000 metrics/s), the Pi 4's SD card I/O
  ceiling is reached and sustained write latency degrades from < 1 ms to > 10 ms,
  causing the `monitor/` insert backlog to grow unboundedly.

**Estimated crossover point:** SQLite becomes a write bottleneck on Raspberry Pi 4
at approximately **3 000–5 000 aggregate metrics/s** (SD card-limited) or
**10 000–20 000 metrics/s** (NVMe SSD-limited). This crossover is **not yet
measured** on the actual deployment hardware — see §5 for the required benchmark.

---

## 3. Alternative Storage Engines

### 3.1 DuckDB (Embedded Columnar OLAP)

DuckDB is an embedded OLAP engine using a columnar storage format with vectorised
execution. Released as v1.0 in 2024 (Raasveldt & Mühleisen, CWI 2018).

**Relevant properties for time-series probe data:**

| Property | SQLite | DuckDB |
|---|---|---|
| Write model | Row-oriented, append | Columnar, batched insert |
| Compression | None (raw rows) | Per-column: RLE, delta, ZSTD |
| Read pattern fit | Point queries, recent rows | Range aggregations, GROUP BY time |
| Concurrent writers | 1 (WAL serialised) | 1 (single-writer model) |
| Analytical queries | Slow (row scan) | Fast (columnar + vectorised) |
| Gorilla compression | Manual via extension | Manual (not built-in for floats) |
| Disk format portability | Single .db file | Single .duckdb file |
| ARM support | Yes | Yes (tested on ARM64) |

**Pelkonen et al. (Gorilla, VLDB 2015) query workload characterisation:**
The Gorilla paper characterised Facebook's TSDB workload as dominated by:
1. Recent data reads (last 24 hours) — served from in-memory hot store.
2. Aggregate range queries (min/max/avg over time windows) — served from cold store.
3. Rare point queries (< 5 % of total).

DuckDB's columnar storage and vectorised GROUP BY are well-matched to patterns 1 and 2.
SQLite's row-oriented model handles pattern 3 better. For the `monitor/` dashboard
(time-series graphs + anomaly alerts), pattern 2 dominates — DuckDB is structurally
a better fit at query time.

**DuckDB write throughput:** DuckDB is optimised for bulk analytical loads, not
high-frequency single-row inserts. Inserting rows one at a time via DuckDB is
*slower* than SQLite WAL. The correct usage pattern is: buffer metrics in-memory
for 1–5 s (e.g., using Go channel + batch goroutine), then flush as a bulk
`INSERT INTO ... VALUES (...)` or Arrow batch. At bulk insert, DuckDB achieves
~500 000–1 000 000 rows/s on ARM64.

**Verdict:** DuckDB is appropriate if:
- Aggregate ingest rate > 5 000 metrics/s (where SQLite degrades on Pi 4), OR
- Dashboard query latency on time-range aggregations is unacceptable with SQLite.
DuckDB is *not* a drop-in replacement for SQLite — it requires a batching write
path and schema changes (columnar layout).

### 3.2 Prometheus with Remote-Read

Prometheus's own TSDB (prometheus/tsdb package, Go) uses an LSM-tree with
Gorilla-compressed chunks. It is the reference implementation of the Pelkonen et al.
design.

**Relevant properties:**

- **Write throughput:** Designed for 10⁶–10⁷ samples/s in production (Prometheus
  production data, 2023, per mechanicalsnail.com analysis).
- **Compression:** Delta-of-delta timestamps (1.37 bits/sample avg) + XOR float64
  values (12 bits/sample avg) → 9.6× compression vs. raw float64.
- **Query interface:** PromQL; remote-read API allows external consumers.
- **Deployment footprint:** Prometheus binary is ~100 MB; adds a separate process;
  requires port 9090 or configured remote-write endpoint.
- **ARM support:** Full (official Prometheus arm64 binaries available).

**Verdict:** Prometheus TSDB is appropriate if the deployment already runs a
Prometheus instance (e.g., for Grafana integration) and remote-read from `monitor/`
is acceptable. It avoids re-implementing the Gorilla store already referenced in
`docs/theory/probes/gorilla-compression-go-theory.md`. The overhead of a separate
Prometheus process on a Raspberry Pi 4 is non-trivial (~60–80 MB RSS at idle)
but manageable.

### 3.3 VictoriaMetrics (Embedded Single-Binary Mode)

VictoriaMetrics offers a single-binary mode that is API-compatible with Prometheus
but uses a more aggressive LSM variant with lower RAM usage (~10–20 MB baseline vs.
Prometheus ~60 MB). It handles InfluxDB line protocol and Prometheus remote-write.

**Relevant properties:**
- Lower memory baseline than Prometheus on constrained hardware (Pi 4).
- Handles 10 000+ active series without cardinality explosion issues that affect
  InfluxDB 1.x.
- Not embeddable as a Go library (separate binary required, like Prometheus).

---

## 4. Decision Matrix

| Scenario | Recommended storage | Reason |
|---|---|---|
| Single collector, ≤ 1 000 metrics/s, Pi 4 (SD card) | SQLite WAL + SYNCHRONOUS=NORMAL | Within ceiling; no migration cost |
| 2–4 collectors, 1 000–5 000 metrics/s, Pi 4 (SD card) | SQLite WAL + write batching (100–500 ms flush) | Batch inserts reduce I/O ops; stay within ceiling |
| 5+ collectors or > 5 000 metrics/s on Pi 4 SD | DuckDB (bulk insert path) or Prometheus TSDB | SQLite I/O ceiling exceeded |
| Already running Prometheus/Grafana | Prometheus remote-write | Reuse existing infrastructure; native PromQL |
| Query-heavy dashboard with long time-range aggregations | DuckDB | Columnar vectorised GROUP BY vs. SQLite full scan |

---

## 5. Open Research Question: Crossover Benchmark

The crossover point estimated in §2.2 is based on publicly available benchmarks on
different hardware. The **actual crossover on the deployment Raspberry Pi 4** (with
its specific SD card, I/O scheduler, and SQLite version) is not yet measured.

### 5.1 Required Benchmark

Run the following benchmark on the actual Pi 4 deployment hardware:

```bash
# Commit to: scripts/benchmark_sqlite_write.py
# Measures: sustained INSERT throughput at 100, 500, 1000, 2000, 5000 rows/s
# for 60 seconds each, with the same schema as monitor/db/schema.sql
# Metrics: actual write latency (p50/p95/p99), WAL checkpoint frequency,
#          disk I/O utilisation (iostat)
```

### 5.2 Exit Criteria for Closing This Research Question

- [ ] Benchmark run on the actual Pi 4 deployment SD card, measuring
  sustained write throughput and p95 insert latency at 100/500/1000/5000 metrics/s.
- [ ] Crossover point documented with actual measured numbers (not estimates).
- [ ] If crossover < 3 × current peak ingest rate: migration path to DuckDB
  or Prometheus TSDB documented in `ARCHITECTURE.md`.
- [ ] If crossover > 3 × current peak ingest rate: document SQLite as confirmed
  adequate with current deployment scale, and re-evaluate at next hardware change.

---

## 6. Related Work

| Reference | Relevance |
|---|---|
| Pelkonen et al. "Gorilla: A Fast, Scalable, In-Memory TSDB." VLDB 2015 | Query workload characterisation (already cited in gorilla-compression-go-theory.md) |
| Raasveldt & Mühleisen "DuckDB: An Embeddable Analytical Database." SIGMOD 2019 | DuckDB design rationale: columnar in-process OLAP |
| mechanicalsnail.com "Inside a High-Performance TSDB in Go." 2025 | LSM-tree architecture, WAL design, Gorilla compression in Go |
| marending.dev SQLite Benchmarks, December 2023 | Empirical WAL write throughput on x86 and ARM |
| shivekkhurana.com "SQLite in Production", December 2025 | Real-world WAL throughput degradation under concurrent connections |
| InfluxData "DuckDB vs. OpenTSDB" comparison | DuckDB time-series analytical query performance characterisation |
| Prometheus TSDB design docs (github.com/prometheus/prometheus/tsdb) | LSM-block architecture, 2-hour block size rationale, compaction strategy |
