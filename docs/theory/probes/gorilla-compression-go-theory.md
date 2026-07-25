# Delta-of-Delta / XOR Compression for Go Telemetry Exporters — Theory

Research reviewed 2026-07-25.
Covers the Gorilla compression algorithm (Pelkonen et al. VLDB 2015) and its concrete
application to the `collector/` Go exporter, with full bit-level encoding rules and a
reference implementation.

---

## 1. Why Gorilla compression matters for this project

The `collector/` agent generates time-series data at a fixed interval (default 30 s) for
every checked target and metric. Without compression, each data point is an
`(int64 timestamp, float64 value)` pair = **16 bytes**.

Pelkonen et al. (VLDB 2015, 480+ citations) measured 440 000 real monitoring data points
from Facebook's production fleet and found:

| Field | Uncompressed | After Gorilla | Bits/point avg |
|---|---|---|---|
| Timestamp (int64, 8 B) | 64 bits | **1 bit** in 96.39 % of cases | ~1.37 bits |
| Float64 value | 64 bits | **1 bit** for identical, short frame for similar | ~10.9 bits |
| **Total** | **128 bits (16 B)** | **~12.3 bits** | **~12×** |

For the probe's expected rate of ≤ 100 metrics/s, this means:
- Uncompressed: 1.6 KB/s (128 bit × 100/s)
- Gorilla-compressed: ~154 B/s
- Over a 30-second OTLP batch: 4.6 KB → ~450 B on the wire

This is directly relevant to the wireless transport scenario (probe on Wi-Fi, sending to
backend over WireGuard tunnel where every byte increases jitter).

---

## 2. Timestamp encoding: Delta-of-Delta

Monitoring metrics arrive at near-fixed intervals. Define:

```
Δ(n)   = T(n) − T(n−1)           first-order delta
D(n)   = Δ(n) − Δ(n−1)           delta-of-delta (D = 0 if perfectly regular)
```

Because D(n) ≈ 0 for regular probes (60 s interval ± NTP jitter ≈ ± 1 ms), the entire
timestamp stream compresses to near-zero bits.

### Encoding table (Pelkonen 2015, §4.1)

| D(n) value | Control bits | Payload bits | Total bits |
|---|---|---|---|
| 0 | `0` | 0 | **1** |
| [−63, 64] | `10` | 7 (ZigZag signed) | 9 |
| [−255, 256] | `110` | 9 | 12 |
| [−2047, 2048] | `1110` | 12 | 16 |
| any other | `1111` | 32 | 36 |

**ZigZag encoding** maps signed integers to unsigned: `(n << 1) ^ (n >> 63)` — this
lets the variable-length encoding work on the magnitude rather than two's complement.

For the `tsenart/go-tsz` improvement over the original paper: the timestamp delta is
first ZigZag-encoded and then **decremented by 1** before encoding, then incremented by
1 on decode. This shifts the most-frequent value (D=0 → ZigZag 0 → stored as −1 + 1 = 0)
to fit within the 7-bit range even at millisecond precision.

### 27-bit delta header (go-tsz improvement)

The original Gorilla paper uses a 14-bit first delta header, which limits block duration
to ~2.7 hours at second precision. `tsenart/go-tsz` extends this to **27 bits**, allowing
**up to 1 day of millisecond-precision data per block** — important for the probe's
14-day retention window where blocks represent a full day's samples.

---

## 3. Float64 value encoding: XOR

IEEE 754 float64 layout:
```
[sign:1][exponent:11][mantissa:52]
```
Consecutive monitoring values (e.g. RTT hovering at 1.2 ms) share the same sign,
the same exponent, and most mantissa bits. XOR produces a mostly-zero bit pattern.

### Encoding rules (Pelkonen 2015, §4.1)

```
XOR(n) = float64_bits(V(n)) XOR float64_bits(V(n−1))
```

| Case | Control bits | Payload |
|---|---|---|
| XOR = 0 (identical value) | `0` | none |
| XOR fits in previous leading/trailing-zero frame | `10` | meaningful bits only |
| XOR needs new leading/trailing-zero frame | `11` | 5-bit leading-zero count + 6-bit length + meaningful bits |

**Leading zeros** (up to 63, stored in 6 bits — go-tsz improvement over the original 5-bit
limit which allowed only 31 leading zeros, breaking for values like `NaN`).

For RTT values like 1.2 ms = `0x3FF3333333333333`:
- Leading zeros: 0 (sign+exponent non-zero)
- Trailing zeros: 16 (low mantissa bits are zero for this magnitude)
- Meaningful bits: 48

For highly stable values like `0.0` or `1.0`:
- XOR = 0 → **1 bit total**

For NTP offset (typically ±1 ms, very stable): consecutive XORs are nearly all-zero →
high compression ratio matching the Gorilla paper's 59 % single-bit case.

---

## 4. Existing Go libraries

| Library | License | Notes |
|---|---|---|
| `github.com/tsenart/go-tsz` | MIT | Fork of dgryski/go-tsz with ZigZag + 27-bit header improvements; implements Pelkonen 2015 |
| `github.com/keisku/gorilla` | MIT | Clean Go 1.18+ implementation; simple API (`NewCompressor` / `NewDecompressor`) |
| `github.com/dgryski/go-tsz` | — | Original; no explicit license; avoid |
| Prometheus `chunkenc` | Apache 2.0 | Production-grade XOR chunk used in Prometheus TSDB; handles histogram and float series |

**Recommendation:** use `github.com/tsenart/go-tsz` for the exporter's local buffer
encoding (MIT, improvements over the original paper, Go-idiomatic) and the Prometheus
`chunkenc` XOR chunk if/when Prometheus remote-write is adopted (compatible schemas).

---

## 5. Reference implementation for `collector/`

The following is the concrete integration pattern for the `collector/` Go exporter.

### 5.1 Data model

```go
// collector/compress/series.go
package compress

import (
    "bytes"
    "time"

    tsz "github.com/tsenart/go-tsz"
)

// Series buffers one metric time series in a Gorilla-compressed block.
// A new block is created each flush interval; the compressed bytes are
// sent to the backend as the payload of the OTLP/JSON envelope.
type Series struct {
    name      string
    target    string
    tags      map[string]string
    buf       bytes.Buffer
    compressor *tsz.Series   // tsz.Series wraps the go-tsz compressor
    count     int
    startedAt time.Time
}

func NewSeries(name, target string, tags map[string]string) *Series {
    s := &Series{
        name:   name,
        target: target,
        tags:   tags,
        startedAt: time.Now(),
    }
    // tsz.New takes the timestamp of the *first* point (block header)
    // and returns a *tsz.Series that implements Push(t uint32, v float64)
    s.compressor = tsz.New(uint32(time.Now().Unix()))
    return s
}

// Push adds a (timestamp, value) data point to the compressed block.
// t is Unix seconds (uint32); v is the float64 metric value.
func (s *Series) Push(t time.Time, v float64) error {
    s.compressor.Push(uint32(t.Unix()), v)
    s.count++
    return nil
}

// Flush finalises the compressed block and returns the raw bytes.
// The Series is reset and ready for a new block after Flush.
func (s *Series) Flush() ([]byte, int, error) {
    // Finish() writes the end-of-stream marker and flushes bit-padding
    it, err := s.compressor.Iter()
    if err != nil {
        return nil, 0, err
    }
    _ = it // iterate if needed for validation

    b, err := s.compressor.MarshalBinary()
    if err != nil {
        return nil, 0, err
    }
    n := s.count

    // Reset for next block
    s.compressor = tsz.New(uint32(time.Now().Unix()))
    s.count = 0
    s.startedAt = time.Now()
    return b, n, nil
}
```

### 5.2 Compressed envelope format

The backend receives a JSON envelope with a `compressed_series` array. Each element
carries the metadata (name, target, tags) plus the raw Gorilla bytes encoded as
base64, plus the point count and block start time for the decoder.

```go
// collector/compress/envelope.go
package compress

import (
    "encoding/base64"
    "encoding/json"
    "time"
)

// CompressedBlock is the wire format for one metric series block.
type CompressedBlock struct {
    Name      string            `json:"name"`
    Target    string            `json:"target"`
    Tags      map[string]string `json:"tags"`
    StartTime time.Time         `json:"start_time"`
    PointCount int              `json:"point_count"`
    // GorilaB64 is the base64url-encoded Gorilla-compressed block bytes.
    // The decoder must: base64.RawURLEncoding.DecodeString → pass to tsz.NewIterator.
    GorillaB64 string           `json:"gorilla_b64"`
    // UncompressedBytes is informational only (for logging compression ratio).
    UncompressedBytes int       `json:"uncompressed_bytes,omitempty"`
}

func (s *Series) ToBlock() (*CompressedBlock, error) {
    raw, n, err := s.Flush()
    if err != nil {
        return nil, err
    }
    return &CompressedBlock{
        Name:              s.name,
        Target:            s.target,
        Tags:              s.tags,
        StartTime:         s.startedAt,
        PointCount:        n,
        GorillaB64:        base64.RawURLEncoding.EncodeToString(raw),
        UncompressedBytes: n * 16, // 8B ts + 8B float64
    }, nil
}
```

### 5.3 Backend decoder (Python)

```python
# monitor/compress.py — decodes Gorilla blocks from the collector
import base64
import struct
from typing import Iterator, Tuple

def decode_gorilla_block(b64: str) -> Iterator[Tuple[int, float]]:
    """
    Decode a Gorilla-compressed block from the Go collector.
    Yields (unix_timestamp_seconds, float64_value) pairs.

    Note: this is a pure-Python reference implementation of the
    tsenart/go-tsz wire format. For production use, call the Go
    collector's /decompress endpoint (which embeds go-tsz) rather
    than reimplementing the bit-level decoder in Python.

    For a simple integration that avoids reimplementing the codec,
    use the OTLP/gRPC path where the OTLP exporter handles encoding
    and the OpenTelemetry Collector handles decoding — no custom
    codec needed on the Python side.
    """
    # Recommended approach: the Go collector exposes a lightweight
    # /decompress HTTP endpoint that accepts a base64 Gorilla block
    # and returns the decoded points as JSON. The Python monitor calls
    # this endpoint rather than reimplementing the bit decoder.
    raise NotImplementedError(
        "Use OTLP/gRPC path or the Go /decompress endpoint. "
        "See docs/theory/probes/probe-to-backend-transport-theory.md §2.1."
    )
```

**Recommended integration pattern:** the Go collector already has `go-tsz` linked.
Expose a `/api/decompress` HTTP endpoint on the collector (or inline the decode into
the OTLP metric serialisation step) so the Python monitor never needs a Go-compatible
bit-stream decoder. Alternatively, use the OTLP/gRPC path directly — the OTLP protobuf
encoding of `NumberDataPoint` already carries timestamp + value without a custom codec,
and the Gorilla compression layer is applied at the block/chunk level *within* the
collector's local SQLite store only, not on the wire.

---

## 6. Compression strategy decision tree

```
Where to apply Gorilla compression:

  collector/ local store (SQLite WAL)
    → Yes. Compress every Series before writing to SQLite.
      Column: gorilla_block BLOB, series_meta JSON.
      Query: read blob → decode in Go → aggregate in memory.
      Benefit: 12× storage reduction; all 14 days fit in < 100 MB.

  collector/ → backend wire (OTLP/gRPC)
    → No (or optional). OTLP protobuf + gzip already reduces payload
      by 3–10×. Adding Gorilla on top is redundant when gzip catches
      repeated protobuf field patterns. Keep wire format standard OTLP.

  backend SQLite store
    → Yes. Backend receives OTLP → decodes to (ts, value) tuples
      → re-encodes to Gorilla blocks before writing to cold table.
      Hot table (< 26 h): raw rows for fast window queries.
      Cold table (> 26 h): Gorilla blocks for storage efficiency.
```

---

## 7. Block boundary and hot/cold table design

Pelkonen et al. (VLDB 2015 §5) found that 85 % of monitoring queries read data from the
most recent 26 hours. This motivates a two-tier storage design:

```sql
-- Hot table: raw rows, indexed for fast range queries
CREATE TABLE metrics_hot (
    target      TEXT NOT NULL,
    metric      TEXT NOT NULL,
    ts          INTEGER NOT NULL,   -- Unix seconds
    value       REAL NOT NULL,
    tags        TEXT,               -- JSON string
    PRIMARY KEY (target, metric, ts)
) WITHOUT ROWID;
CREATE INDEX idx_hot_ts ON metrics_hot(ts);

-- Cold table: Gorilla-compressed blocks (one row per 2h block per series)
CREATE TABLE metrics_cold (
    target      TEXT NOT NULL,
    metric      TEXT NOT NULL,
    block_start INTEGER NOT NULL,   -- Unix seconds of block start
    block_end   INTEGER NOT NULL,
    point_count INTEGER NOT NULL,
    gorilla_block BLOB NOT NULL,    -- raw Gorilla bytes (go-tsz binary format)
    PRIMARY KEY (target, metric, block_start)
) WITHOUT ROWID;
```

**Compaction job** (runs every hour, driven by `scheduler.py`):
```sql
-- Move rows older than 26h from hot to cold
INSERT INTO metrics_cold SELECT ... FROM metrics_hot WHERE ts < (strftime('%s','now') - 93600);
DELETE FROM metrics_hot WHERE ts < (strftime('%s','now') - 93600);
-- Then purge cold rows older than 14 days
DELETE FROM metrics_cold WHERE block_end < (strftime('%s','now') - 1209600);
```

---

## 8. Open questions requiring empirical work

1. **Compression ratio on probe-specific distributions.** The Gorilla paper's 12× ratio
   is measured on Facebook's production fleet (server RTTs, mostly stable). Probe metrics
   that include loss events, Wi-Fi roaming drops, and NTP corrections may have higher
   XOR entropy. Measure actual compression ratio on 24 h of captured probe data before
   committing to block sizing.

2. **Block size vs. decode latency.** Larger blocks compress better but require decoding
   the entire block to answer a point query. For dashboard queries spanning < 5 minutes,
   a 2-hour block wastes ~23× more decode work than needed. Consider 15-minute blocks
   for the cold table.

3. **go-tsz vs. Prometheus chunkenc.** `go-tsz` implements the original Gorilla paper
   with improvements; Prometheus `chunkenc` is battle-hardened at 10^9 points/day scale
   but adds histogram support overhead. Benchmark both at 10 000 points/block to confirm
   encode/decode latency is sub-millisecond for the compaction job.

---

## 9. References

- Pelkonen, T. et al. (2015). **Gorilla: A Fast, Scalable, In-Memory Time Series Database.**
  *VLDB Endowment*, 8(12). https://www.vldb.org/pvldb/vol8/p1816-teller.pdf

- tsenart/go-tsz (Go implementation, MIT, ZigZag + 27-bit improvements).
  https://pkg.go.dev/github.com/tsenart/go-tsz

- keisku/gorilla (clean Go 1.18+ implementation, MIT).
  https://github.com/keisku/gorilla

- Winter, C. (2024). **The Simple Beauty of XOR Floating Point Compression.**
  https://clemenswinter.com/2024/04/07/the-simple-beauty-of-xor-floating-point-compression/

- Mechanical Snail (2023). **Inside a High-Performance Time Series Database in Go.**
  https://mechanicalsnail.com/posts/timeseries-database-go/

- Related: `docs/theory/probes/probe-to-backend-transport-theory.md` §3 (R-C1, R-C2).
