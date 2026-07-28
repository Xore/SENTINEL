# Probe-to-Backend Transport and Backend Processing — Theory

Research reviewed 2026-07-25. Covers secure transport of diagnostic data from a network probe
to a backend and effective processing methods for that data once received.

---

## 1. Threat model for the transport path

Before selecting a protocol or compression scheme, the threat surface of the transport must
be characterised. A probe-to-backend link is a point-to-point data channel where the
following threats apply:

| Threat | Mitigation tier |
|---|---|
| Passive eavesdropping (packet capture en-route) | TLS 1.3 in-transit encryption |
| Active MITM / certificate spoofing | Mutual TLS (mTLS) with pinned CA |
| Probe impersonation (rogue sender) | Client certificate authentication (mTLS) |
| Backend impersonation | Server certificate validation, CA pinning |
| Replay of stale telemetry | Monotonic sequence numbers inside payload |
| Data injection / tampering | TLS record integrity (AEAD) |
| Denial-of-service flood from compromised probe | Rate limiting at backend ingestion layer |

Tagliaro et al. (ACM CCS 2024) performed large-scale empirical analysis of real-world IoT
backends and found that **99.84 % of MQTT-speaking backends used insecure transport**,
with only 0.16 % adopting TLS — of which 70.93 % further adopted valid certificates.
This empirical baseline underlines that TLS + mTLS is the exception in deployed systems,
not the norm, and therefore must be an explicit design requirement here rather than an
assumed default.

**Design requirement (R-T1):** All probe-to-backend connections MUST use TLS 1.3 with
mutual certificate authentication. Plain HTTP or unauthenticated MQTT MUST NOT be used,
even on a "trusted" management VLAN.

---

## 2. Transport protocol selection

### 2.1 OTLP/gRPC (recommended primary path)

The **OpenTelemetry Protocol (OTLP)** is an open-standard, vendor-neutral telemetry wire
format specified by the OpenTelemetry project. It covers metrics, traces, and logs in a
single schema and is serialised as Protocol Buffers (protobuf) over gRPC or HTTP/2. The
stable OTLP v1.0.0 specification provides full binary-compatibility guarantees for metrics,
traces, and logs.

Key security properties of OTLP/gRPC:
- TLS is **required by default**; the Go OTLP exporter rejects plaintext unless
  `insecure: true` is explicitly set.
- mTLS is natively supported via `cert_file` / `key_file` / `ca_file` in the exporter
  configuration.
- gRPC uses HTTP/2 framing; a single persistent connection multiplexes all metric streams,
  reducing handshake overhead vs. per-request TLS.
- The exporter ships with built-in **retry-with-backoff** and an in-memory **sending queue**
  with configurable depth, enabling store-and-forward under transient backend unavailability.
- gzip compression is enabled by default on the OTLP exporter, compressing protobuf
  payloads a further 30–60 % over the wire.

Benchmarks comparing wire formats at scale (Mechanical Snail, 2025; Gravitee, 2025)
consistently show protobuf is **3–10× smaller** than equivalent JSON and **5–20× faster**
to parse. For diagnostic telemetry (timestamps + float64 values), protobuf's varint and
ZigZag encoding compresses repeated small integers efficiently without the overhead of
field-name strings that JSON carries on every record.

**Design requirement (R-T2):** The Go collector SHOULD implement an OTLP/gRPC exporter
(using `go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc`) as its
primary push path. The Python monitor stack SHOULD use the
`opentelemetry-exporter-otlp-proto-grpc` package.

### 2.2 MQTT with TLS (alternative for constrained / OT-adjacent networks)

For segments where HTTP/2 is impractical (constrained bandwidth, OT DMZ with deep packet
inspection that blocks gRPC), MQTT 5.0 over TLS 1.3 is an academically well-studied
alternative. Tofan et al. (MDPI Sensors 2024) measured TLS overhead on MQTT across
constrained hardware and found that AES-128-GCM at TLS 1.3 adds only 3–8 % CPU overhead
on Cortex-A class processors (Raspberry Pi range) — acceptable for this probe's expected
message rate of < 100 metrics/s.

MQTT QoS level 1 (at-least-once delivery with ACK) is the recommended setting for
diagnostic telemetry: it prevents silent loss without the duplicate-suppression complexity
of QoS 2. QoS 0 (fire-and-forget) is not acceptable for security-relevant event records.

However, MQTT requires an intermediary broker (e.g., Mosquitto or EMQX), which adds an
operational component. For this project's architecture — where every probe has
an ordinary IP route to its configured site backend — OTLP/gRPC is simpler
end-to-end.

**Design requirement (R-T3):** If OTLP/gRPC cannot traverse the network path, use
MQTT 5.0 + TLS 1.3 with QoS 1, client certificates, and a locally pinned CA. Do not
use MQTT without TLS.

### 2.3 TLS cipher suite selection

After et al. (MDPI Sensors 2023) benchmarked TLS 1.3 cipher suites on COTS embedded
devices and found that **Curve25519 + RSA** reduced computation latency up to **4× over
P-256 + RSA** on the same hardware. For the Go collector running on Raspberry Pi (ARM64),
the cipher preference order SHOULD be:

1. `TLS_AES_128_GCM_SHA256` (hardware AES on Pi 4/5)
2. `TLS_CHACHA20_POLY1305_SHA256` (software fallback on Pi 3 / older ARM)
3. `TLS_AES_256_GCM_SHA384` (heavier; only if compliance requires 256-bit)

Go's `crypto/tls` selects from these automatically based on hardware capability; no manual
override is needed unless auditors require an explicit cipher list.

---

## 3. Wire-format compression and time-series encoding

### 3.1 Gorilla delta-of-delta + XOR compression

Pelkonen et al. (VLDB 2015, cited 480+) introduced the **Gorilla** compression algorithm
for monitoring time series at Facebook. Gorilla achieves an average compression ratio of
**12× over raw 16-byte (timestamp, float64) pairs** by applying:

- **Delta-of-delta timestamps:** monitoring metrics arrive at near-fixed intervals; the
  second-order delta is almost always zero or a small correction, representable in 1–7 bits.
- **XOR floating-point values:** consecutive metric values are similar (e.g., RTT hovers
  around a stable baseline); XOR with the previous value produces a mostly-zero bit pattern
  that encodes in 1 bit (identical) or a compact leading/trailing-zero frame.

The Gorilla block format is what Prometheus's remote-write protocol and InfluxDB's TSM
storage engine both derive from. An average monitoring data point compresses from
16 bytes to **1.37 bytes** — a ratio that directly reduces both network transmission cost
and backend storage.

For the `analyseLaptop` probe, diagnostic data points are naturally Gorilla-compatible:
- RTT, loss %, RSSI, jitter, NTP offset: slowly-varying float64 series at fixed intervals.
- TCP/HTTP/DNS service latency: similarly bursty but locally correlated.

**Design requirement (R-C1):** Use Gorilla-compatible encoding (delta-of-delta timestamps +
XOR float values) for metric payloads. This is provided automatically by the Prometheus
remote-write exposition format and by protobuf-encoded OTLP `NumberDataPoint` messages
when batched in time order.

### 3.2 Batch sizing and flush intervals

Sending each measurement individually (one HTTP POST per ping result) creates per-request
TLS record overhead that dominates at low metric rates. The optimal batch size balances:

- **Latency to backend:** smaller batches → fresher data, higher per-byte overhead.
- **Memory on probe:** larger batches → more buffering, higher risk of loss on probe
  crash.
- **Compression ratio:** larger batches compress better (more repeated field names in
  JSON, more correlated values in Gorilla).

The OTLP exporter's default `batch_timeout` of 5 s with `max_export_batch_size` of 512
datapoints is a reasonable starting point. For a probe generating ≤100 metrics/s, a
5-second batch produces ≤500 points — small enough to fit in a single gRPC message and
large enough that per-record TLS overhead is negligible.

**Design requirement (R-C2):** Batch flush interval 5–30 s (configurable). Maximum in-memory
queue depth: 10 000 datapoints. On queue overflow, drop oldest (ring behaviour) rather
than blocking the probe's measurement loop.

---

## 4. Authentication and certificate management

### 4.1 Mutual TLS (mTLS) for probe identity

mTLS requires both the backend (server) and the probe (client) to present X.509 certificates
signed by a shared CA. This provides:

- **Cryptographic probe identity:** the backend can verify which specific probe is
  connecting and reject any certificate not in its trust list.
- **No shared secrets in config files:** unlike API-key or basic-auth schemes, private keys
  never leave their respective hosts and cannot be extracted from a config file.
- **Zero-trust posture:** even if the management VLAN is compromised, an attacker cannot
  inject synthetic telemetry without a valid probe certificate.

For a small fleet (1–10 probes), a self-signed CA is operationally sufficient. The CA root
is deployed once to the backend trust store; each probe receives a unique leaf certificate
(`CN=probe-<hostname>`) signed by the CA.

### 4.2 Certificate rotation

Certificate rotation on constrained devices is an open problem in the literature. The
recommendation from Tofan et al. (MDPI Sensors 2024) and the OTLP Collector hardening
guidelines (SystemsHardening 2026) is:

1. Issue leaf certificates with a **90-day validity** (matches Let's Encrypt practice;
aligned with NIST SP 800-57 Part 3 for short-lived credentials).
2. Use automated renewal via a lightweight ACME client or a simple cron that calls
   `openssl` + `scp` to push the new cert before the 30-day reminder threshold.
3. Configure Go's `crypto/tls` with `GetClientCertificate` callback rather than a
   static certificate path, so the running process picks up a renewed certificate from
   disk without restart.

**Design requirement (R-A1):** Issue unique leaf certificates per probe. Set 90-day expiry.
Monitor `NotAfter` and alert at T−30 days. Use `GetClientCertificate` callback in the
Go collector's TLS config.

---

## 5. Backend ingestion and processing

### 5.1 Streaming vs. batch processing tradeoffs

TMA 2025 (Quantifying Differences Between Batch and Streaming, Trinocular study) provides
the most directly applicable academic result for this project's use case:

> "Streaming is ideal for reporting what is happening now, but batch should be used to
> assess improvements in overall reliability. Streaming over-reports outages in cases
> where batch confirms reachability [...] batch-up/streaming-down is 5× larger than
> batch-down/streaming-up."

This means:
- A **streaming ingestion path** is appropriate for real-time alerts and dashboards (the
  probe's live RTT chart, outage event table).
- A **batch reprocessing path** is appropriate for baseline computation, percentile
  calculation, and trend accuracy — where the extra latency is acceptable.

For `analyseLaptop`, the backend is a single SQLite store. The equivalent architecture is:
- **Streaming path:** write raw datapoints to SQLite immediately on receipt; trigger
  SQLite-based alert evaluation per INSERT (using SQLite triggers or a lightweight
  Python watcher).
- **Batch path:** a periodic job (every 5–15 minutes) reads the last N hours of data
  and recomputes baselines, percentiles (p50/p95/p99), and smoothed trend lines.

### 5.2 Data stream processing as a tuple pipeline

Gupta et al. (HotNets 2016 — Sonata, cited 86+) formalised network monitoring as a
**streaming analytics problem** where each measurement is treated as a tuple in a
pipeline of relational operators (filter → project → aggregate → join). The key insight
for this project:

- Each probe result (target, metric_name, timestamp, value, tags) maps directly to a
  relational tuple.
- Backend evaluation reduces to: **filter** (by target/metric), **window aggregate**
  (rolling 5-min average), **threshold join** (compare to baseline), **emit alert**.

This pipeline can be implemented entirely in SQLite using window functions (`AVG() OVER
(PARTITION BY target ORDER BY ts ROWS BETWEEN 300 PRECEDING AND CURRENT ROW)`).
No external stream processor (Kafka, Flink, Storm) is warranted at the probe's data
rate, but the tuple-pipeline mental model ensures the schema and query design remain
extensible if a heavier backend is adopted later.

Shah et al. (MDPI Sensors 2021 — Data Stream Processing for Packet-Level Analytics,
PubMed) demonstrated that stream processing pipelines over multi-core general-purpose
hardware handle **10–20 Gb/s** of packet tuple streams. The `analyseLaptop` probe
generates at most a few hundred tuples per second — SQLite with WAL mode handles this
easily without any batching concern at the storage layer.

### 5.3 Threat detection and prevention pipeline

Amorim et al. (Wiley CPE 2021 — Fast and Accurate Threat Detection) proposed combining
**real-time streaming** (first-packet-based heuristics, ≤ 5 packet window) with **batch
classification** (full-flow features over historical data) to achieve > 95 % accuracy
with low false-positive rates. Applied to this project's IDS integration (`ids_reader.py`):

- **First-window (streaming):** Suricata's EVE JSON tail delivers per-alert records
  within < 1 s of detection. The backend's `ids_reader.py` watcher is already this
  streaming layer.
- **Correlation (batch):** Periodically join IDS alerts with probe RTT/loss events in
  SQLite to identify correlated anomalies (e.g., an IDS alert that co-occurs with a
  packet-loss spike on the same target).

### 5.4 Time-series storage at the backend

Pelkonen et al. (VLDB 2015 — Gorilla) showed that **85 % of monitoring queries read
the most recent 26 hours of data**. This directly informs the SQLite schema design:

- Keep a **hot table** (last 26 hours, uncompressed) in SQLite's WAL file for fast
  `SELECT` queries from the dashboard.
- Run a **compaction job** (every hour or at T+26h) that delta-encodes older rows and
  moves them to a cold table, or simply truncates by the 14-day retention window.
- Index on `(target, metric, ts)` rather than a single `ts` index; the dashboard's
  per-target chart query is a ranged scan by target + time, not a full-table sort.

---

## 6. Implementation map for `analyseLaptop`

| Requirement | Where to implement | Academic basis |
|---|---|---|
| R-T1: TLS 1.3 mandatory | `collector/main.go` TLS config; OTLP exporter | Tagliaro et al. ACM CCS 2024 |
| R-T2: OTLP/gRPC push exporter | `collector/` — new `exporter.go` | OTLP Spec v1.0 (OpenTelemetry 2024) |
| R-T3: MQTT fallback | Optional `collector/mqtt_exporter.go` | Tofan et al. MDPI Sensors 2024 |
| Cipher preference (Curve25519) | `collector/main.go` TLS `CurvePreferences` | After et al. MDPI Sensors 2023 |
| R-C1: Gorilla-compatible encoding | Automatic via OTLP protobuf metric batching | Pelkonen et al. VLDB 2015 |
| R-C2: Batch flush 5–30 s, ring queue | `collector/exporter.go` sending queue | OTLP exporter defaults |
| R-A1: mTLS + 90-day cert rotation | `collector/tls.go`, `GetClientCertificate` | NIST SP 800-57 Pt3; Tofan 2024 |
| Streaming ingestion | `dashboard/` API endpoint → SQLite WAL write | TMA 2025 Trinocular study |
| Batch baseline recomputation | `scheduler.py` periodic SQLite window queries | TMA 2025; Amorim et al. 2021 |
| Tuple-pipeline schema | SQLite schema — `(target, metric, ts, value, tags)` | Gupta et al. HotNets 2016 |
| Hot/cold table compaction | Hourly SQLite compaction job | Pelkonen et al. VLDB 2015 |
| IDS alert correlation | Join `suricata_events` × `probe_results` on `(target, ts±5s)` | Amorim et al. Wiley CPE 2021 |

---

## 7. What still needs research

The following design decisions require further empirical work before implementation:

1. **Optimal batch size under lossy links.** The 5 s / 512-point OTLP default is calibrated
   for data-centre networks. On a laptop probe with intermittent Wi-Fi, the right queue
   depth and flush interval under varying loss rates is an open tuning question. A
   simulation using recorded Wi-Fi loss traces from `outage_monitor.py` would bound this.

2. **SQLite vs. embedded TSDB for backend storage.** At > 1 000 metrics/s, SQLite WAL
   mode saturates on write throughput before the network does. The crossover point for this
   probe needs measurement. If the probe ever aggregates multi-site collectors, migration
   to an embedded TSDB (e.g., Prometheus with remote-read, or DuckDB with Gorilla encoding)
   should be evaluated against Pelkonen et al.'s query workload characterisation.

3. **Certificate rotation automation in offline / air-gapped deployments.** ACME cannot
   reach an air-gapped backend. A lightweight provisioning protocol (e.g., EST — RFC 7030,
   or a simple SSH-push script) needs a concrete design for the OT-adjacent deployment
   scenario.

4. **mTLS overhead on Raspberry Pi 3 (ARMv7).** After et al. benchmarked ARMv8 (64-bit)
   only. The overhead of TLS 1.3 with Curve25519 on 32-bit ARMv7 at the probe's metric
   rate has not been measured in this specific context.

---

## 8. References

- Pelkonen, T. et al. (2015). **Gorilla: A Fast, Scalable, In-Memory Time Series Database.**
  *Proceedings of the VLDB Endowment*, 8(12), 1816–1827.
  https://www.vldb.org/pvldb/vol8/p1816-teller.pdf

- Tagliaro, C. et al. (2024). **Large-Scale Security Analysis of Real-World Backend Systems.**
  *ACM CCS 2024*. https://dl.acm.org/doi/fullHtml/10.1145/3678890.3678899

- Tofan, C. et al. (2024). **A Performance Analysis of Security Protocols for Distributed
  Measurement Systems Based on IoT with Constrained Hardware.**
  *MDPI Sensors*, 24(9), 2781. https://www.mdpi.com/1424-8220/24/9/2781

- After, J. et al. (2023). **TLS Protocol Analysis Using IoTST — An IoT Benchmark Based on
  Scheduler Traces.** *MDPI Sensors*, 23(5), 2538.
  https://www.mdpi.com/1424-8220/23/5/2538

- Gupta, A. et al. (2016). **Network Monitoring as a Streaming Analytics Problem (Sonata).**
  *HotNets 2016*. https://www.rbirkner.ch/assets/pdfs/rbirkner-hotnets16-paper.pdf

- Shah, N. et al. (2021). **Data Stream Processing for Packet-Level Analytics.**
  *MDPI Sensors*, 21(5), 1735. https://doi.org/10.3390/s21051735

- Amorim, I. et al. (2021). **A Fast and Accurate Threat Detection and Prevention
  Architecture Using Stream Processing.** *Concurrency and Computation: Practice and
  Experience*, Wiley. https://onlinelibrary.wiley.com/doi/10.1002/cpe.6561

- Trinocular TMA Study (2025). **Quantifying Differences Between Batch and Streaming
  Network Outage Detection.** *TMA 2025*.
  https://tma.ifip.org/2025/wp-content/uploads/sites/14/2025/06/tma2025_paper12.pdf

- OpenTelemetry Protocol Specification v1.10.0 (2024).
  https://opentelemetry.io/docs/specs/otlp/

- OpenTelemetry OTLP Exporter for Go — TLS/mTLS configuration.
  https://opentelemetry.io/docs/specs/otel/protocol/exporter/

- NIST SP 800-57 Part 3 Rev. 1 — Recommendation for Key Management:
  Application-Specific Key Management Guidance.

- RFC 7030 — Enrollment over Secure Transport (EST).
