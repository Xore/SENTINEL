# Topic 9: SQLite WAL vs. Embedded TSDB Storage Crossover

**Status:** Literature reviewed (Pelkonen VLDB 2015, Raasveldt SIGMOD 2019, benchmarks). Decision matrix populated. Crossover benchmark requires live Pi 4 SD card run — pending.

---

## Gorilla (Pelkonen et al. VLDB 2015) — Workload Profile

**Citation:** Pelkonen, T. et al. "Gorilla: A Fast, Scalable, In-Memory Time Series Database." VLDB 2015.

### Workload Characterisation (§3)
- 85% of queries are over the last 26 hours (recent data dominates)
- 80% of queries are range queries, not point lookups
- 40% of all CPU in Facebook's monitoring was consumed by read-path aggregations
- Write amplification is the bottleneck, not read latency, for ingest-heavy workloads

### Relevance to This Project
- The `monitor/` dashboard query pattern will closely approximate Gorilla's profile: time-range queries for recent RTT/loss data
- SQLite handles range queries well via `WHERE timestamp BETWEEN` + index on `timestamp`
- At 1000 metrics/s, a 24-hour window = 86.4M rows — **this is the scale where SQLite starts to show query latency degradation**, not write throughput degradation

---

## DuckDB (Raasveldt & Mühleisen SIGMOD 2019)

**Citation:** Raasveldt, M. & Mühleisen, H. "DuckDB: An Embeddable Analytical Database." SIGMOD 2019.

### Design Rationale
- Columnar in-process OLAP database — designed for bulk analytical reads, not transactional row-level writes
- Vectorised execution: processes batches of rows (1024-row vectors by default) — excellent for aggregation queries
- **ARM64 support:** DuckDB v0.10+ has first-class ARM64 Linux support; verified on Raspberry Pi 4 by community
- **Write characteristics:** bulk Arrow batch insert (10K–100K rows) is extremely fast; single-row insert is 3–10× **slower** than SQLite WAL — **never use single-row DuckDB inserts**

### When to Migrate from SQLite to DuckDB
From `docs/theory/storage/embedded-tsdb-selection.md` §4:
- SQLite WAL handles ≤ 1000 metrics/s comfortably on Pi 4 SD (estimated)
- DuckDB bulk insert outperforms SQLite above ~3000–5000 metrics/s on Pi 4 SD (unverified — requires benchmark)
- DuckDB query latency for aggregations over 10M+ rows is typically 10–100× faster than SQLite due to columnar vectorised execution

---

## SQLite Write Throughput Reference Data

| Platform | Mode | Measured writes/s |
|---|---|---|
| x86 (benchmark, marending.dev Dec 2023) | WAL + SYNCHRONOUS=NORMAL | 80,000–113,000 |
| Linux ARM (Hetzner CAX31, cloud) | WAL default | 3,316 |
| Pi 4 SD card (estimated) | WAL + SYNCHRONOUS=NORMAL | 15,000–25,000 |
| Pi 4 SD card (estimated) | WAL + SYNCHRONOUS=OFF | 50,000–80,000 |

> ⚠️ **The Pi 4 SD estimates are unverified.** The `scripts/benchmark_sqlite_write.py` benchmark must be run on the actual Pi 4 SD card hardware to fill in this table.

The SD card I/O is the actual bottleneck, not CPU. `PRAGMA synchronous = NORMAL` achieves a good balance: data survives OS crash (WAL protects), but not power loss. For a monitoring device on a UPS or with acceptable data loss on power failure, `SYNCHRONOUS=NORMAL` is the right choice.

---

## Decision Matrix

| Metrics/s | Collectors | Recommendation | Action |
|---|---|---|---|
| ≤ 1,000 | 1 | **Keep SQLite WAL** | Confirm `PRAGMA synchronous = NORMAL` in `monitor/db/db.go` |
| 1,000–5,000 | 2–4 | **SQLite + batched writes** | Buffer 100–500ms, batch INSERT |
| > 5,000 | > 4 | **Migrate to DuckDB** | Arrow batch writer, rewrite range queries |
| Any, query latency > 5s | Any | **Migrate to DuckDB** | Query pattern requires columnar store |

---

## Benchmark Script

See `scripts/benchmark_sqlite_write.py` for the full benchmark.

Test rates: 100 / 500 / 1,000 / 2,000 / 5,000 rows/s (60 seconds each)
Metrics captured: sustained INSERT throughput, p95 write latency, WAL checkpoint frequency, disk I/O (iostat)

Expected output format:
```
Rate     | Achieved (rows/s) | p95 latency (ms) | WAL checkpoints/min | Disk util%
---------|-------------------|------------------|---------------------|----------
100      | ~100              | < 1ms            | 0.1                 | < 5%
500      | ~500              | < 2ms            | 0.5                 | < 10%
1,000    | ???               | ???              | ???                 | ???    ← fill on Pi 4
2,000    | ???               | ???              | ???                 | ???    ← fill on Pi 4
5,000    | ???               | ???              | ???                 | ???    ← fill on Pi 4
```

---

## DuckDB Migration Path (If Needed)

If benchmark shows SQLite crossover at < 2,000 metrics/s on Pi 4 SD:

1. Add Go channel buffer in `monitor/` write path (channel size: 10,000 rows)
2. Flush goroutine: drain channel every 500ms, convert to Arrow record batch
3. DuckDB bulk insert via `go-duckdb` Arrow binding
4. Rewrite time-range queries: `GROUP BY time_bucket('30 seconds', timestamp)` instead of SQLite `strftime`
5. Verify ARM64 compatibility: `go-duckdb` v0.4+ links DuckDB v0.10+ which has ARM64 support

---

## Exit Criteria Status

- [ ] `scripts/benchmark_sqlite_write.py` run on actual Pi 4 SD card; crossover point measured and documented
- [ ] Decision (SQLite or DuckDB) documented with measured numbers
- [ ] `PRAGMA synchronous = NORMAL` confirmed in `monitor/db/db.go`
- [ ] If DuckDB: bulk-insert write path implemented and 24-hour soak tested
- [ ] If SQLite retained: WAL checkpoint interval set appropriately (every 1000 pages default is fine)

## Next Implementation Step

Run `scripts/benchmark_sqlite_write.py` on the Pi 4. If crossover is above 3000 metrics/s, confirm SQLite is sufficient for current deployment scale and document. If below 2000 metrics/s, plan DuckDB migration as part of a future sprint.
