# 08 — Testing & Installation (v2 Collector)

Acceptance checklist for the v2 collector. Two parts:

- **Part A — Unit & integration tests** (run on the dev machine or CI).
- **Part B — Field acceptance** on real hardware (Raspberry Pi 5 + amd64 lab laptop; [ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md)).

Hardware reference:

| Role | Host | Address | Notes |
|---|---|---|---|
| Windows dev box | (this machine) | — | authoring + unit tests, Git Bash + `.venv` |
| Pi collector (live) | `MGPNetworkAnalayses01` | `192.168.50.32` | **LIVE production, Wi-Fi-only — never destabilise** |
| Lab laptop (safe) | `MGPNetworkAnalayses02` | `192.168.50.33` | `adminuser`, SSH key `~/.ssh/analyse_lab`, NOPASSWD sudo, i7-10610U / 15 GiB |

SSH note: `.32`’s sshd is unreliable over the flaky Wi-Fi link — drive it from its
own console or observe via hub metrics only. `.33` is the safe box to control
programmatically.

Legend: `[ ]` = to do, `[x]` = passed. Record date + tester per box.

---

## Part A — Unit & integration tests

### A0. Dev environment baseline

```bash
cd analyseLaptop/collector
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

- [ ] `python3.12 --version` → `3.12.x`
- [ ] `pip install` completes with no errors
- [ ] `mypy . --ignore-missing-imports` → **0 errors**
- [ ] `ruff check .` → **0 violations**

### A1. Unit test suite

```bash
pytest collector/tests/ -v --tb=short
```

- [ ] All tests pass; note any intentionally skipped (Linux-only) tests on Windows
- [ ] On Linux (`.33`): re-run — 0 tests skipped; Linux-specific tests execute
- [ ] `pytest --cov=collector --cov-report=term-missing` → coverage ≥70 %

### A2. Config validation

- [ ] Valid `collector.yaml` loads without error:
  ```bash
  python -c "from collector.config import CollectorSettings; CollectorSettings.from_yaml('collector.yaml')"
  ```
- [ ] Invalid YAML (e.g. `scan_level_max: "bad"`) raises a `pydantic.ValidationError` with a clear field name
- [ ] SIGHUP hot-reload with a bad config logs a structured error and keeps the previous valid config

### A3. Scheduler smoke test

- [ ] `pytest collector/tests/test_scheduler.py -v` → all pass
- [ ] Priority queue: high-priority ICMP check is never starved by a long 30 s bcast window
- [ ] `asyncio.wait_for()` timeout fires correctly for a synthetic slow check

### A4. OTLP export smoke test

- [ ] Start a local OTLP sink (e.g. `otel-collector` or the test stub in `tests/`):
  ```bash
  pytest collector/tests/test_otlp_export.py -v
  ```
- [ ] Metrics reach the sink within one scheduler cycle (≤30 s)
- [ ] `collector_id` and `site_id` labels appear on every exported metric
- [ ] Hub-unreachable scenario: metrics buffer to `lmdb` hot store; reconnect → buffered metrics flush

### A5. PyInstaller binary build

```bash
# Linux amd64
pyinstaller --onefile --name analyselaptop-collector __main__.py

# Linux arm64 via Docker buildx
docker buildx build \
  --platform linux/arm64 \
  -f Dockerfile.collector-arm64 \
  --output type=local,dest=dist/arm64 \
  .
```

- [ ] Binary produced at `dist/analyselaptop-collector` (Linux amd64)
- [ ] Binary size ≤25 MB
- [ ] `./analyselaptop-collector --version` prints version string
- [ ] `./analyselaptop-collector --help` prints usage without error
- [ ] Cold-start time on the reference Pi 5 (research gate R3; record actual value). The ≤15 s budget was set against Pi 3B SD-card I/O and should be re-derived downward — the Pi 5 boots from NVMe over PCIe.

---

## Part B — Field acceptance (real hardware)

### B0. Pre-flight (all nodes)

- [ ] `git rev-parse --short HEAD` matches the intended release commit
- [ ] Hub is reachable from the collector node: `curl -k https://<hub-ip>:4317` (expect gRPC handshake or TLS hello)
- [ ] Confirm `.32` is live and stable before starting — **make no changes that could drop its Wi-Fi link**

### B1. PKI enrolment (.33)

```bash
mkdir -p /var/lib/analyselaptop/pki
./analyselaptop-collector enroll \
  --hub https://<hub-ip>:4317 \
  --enroll-token <token-from-hub>
```

- [ ] `collector.key` and `collector.crt` written to `pki_dir`
- [ ] `openssl x509 -in collector.crt -noout -enddate` shows a future expiry
- [ ] Re-running `enroll` with the same token returns a clear error (token consumed)

### B2. First run (.33)

```bash
sudo setcap cap_net_raw+ep ./analyselaptop-collector
./analyselaptop-collector --config /etc/analyselaptop/collector.yaml
```

- [ ] Structured JSON logs appear on stdout; no `ERROR` lines in first cycle
- [ ] Hub API shows the collector registered:
  ```bash
  curl -s http://<hub-ip>:8080/api/collectors | jq '.[] | select(.id=="lab-33")'
  ```
- [ ] ICMP reachability metrics appear in hub within 30 s (`icmp_rtt_ms{collector_id="lab-33"}`)
- [ ] ARP watch metrics appear (`arp_table_size`, `arp_new_entry_total`)

### B3. Per-check acceptance (.33)

| Check | Expected metric | Pass |
|---|---|---|
| ICMP reachability (Phase C2) | `icmp_rtt_ms`, `icmp_loss_pct` | `[ ]` |
| ARP watch (Phase C4) | `arp_table_size`, `arp_new_entry_total` | `[ ]` |
| MTR hop-tracing (Phase C5) | `mtr_hop_rtt_ms{hop,hop_ip}`, `mtr_hop_loss_pct` | `[ ]` |
| TCP connect (Phase C6) | `tcp_connect_ms`, `tcp_connect_ok` | `[ ]` |
| HTTP health (Phase C7) | `http_response_ms`, `http_status_code` | `[ ]` |
| SNMP identity (Phase C8) | `snmp_sysuptime_seconds`, `snmp_if_oper_status` | `[ ]` |
| Wi-Fi link stats (Phase C9) | `wifi_rssi_dbm`, `wifi_link_speed_mbps` | `[ ]` |
| Bcast/mcast top talkers (Phase C11) | `bcast_top_talker_pkts_total` | `[ ]` |
| OS health (host CPU/mem/disk) | `host_cpu_usage_pct`, `host_mem_available_bytes` | `[ ]` |

### B4. Graceful degradation (.33)

- [ ] Remove `CAP_NET_RAW` → ICMP/MTR/bcast checks skip; log shows structured warning `cap_net_raw_missing`; all other checks continue
- [ ] Stop the hub → collector buffers to `lmdb`; `du -sh /var/lib/analyselaptop/data/hot.lmdb/` grows; restart hub → buffered metrics flush within one retry cycle
- [ ] `python3-bpfcc` absent → eBPF checks skip; log shows `ebpf_unavailable`; all other checks continue

### B5. Systemd service (.33)

```bash
sudo systemctl enable --now analyselaptop-collector
sudo systemctl status analyselaptop-collector
```

- [ ] Service starts and reaches `active (running)`
- [ ] SIGHUP hot-reload (`systemctl kill -s HUP analyselaptop-collector`) applies a config change without restart
- [ ] Service survives a node reboot: `sudo reboot` → re-check `systemctl status` after boot

### B6. Live box read-only smoke (.32, console only)

- [ ] Existing collector still healthy in hub: `curl -s http://<hub-ip>:8080/api/collectors | jq '.[] | select(.id=="pi-bedroom")'`
- [ ] `icmp_rtt_ms` and `wifi_rssi_dbm` metrics still flowing in hub
- [ ] **No config changes made to `.32`**

### B7. Cert auto-renewal (.33)

- [ ] Artificially set cert expiry to <14 days (test PKI) → collector log shows `cert_expiry_soon` then `cert_renewed` without manual intervention
- [ ] New cert has a fresh expiry; gRPC connection continues without interruption

### B8. Binary update procedure (.33)

```bash
systemctl stop analyselaptop-collector
cp dist/analyselaptop-collector /usr/local/bin/analyselaptop-collector
sudo setcap cap_net_raw+ep /usr/local/bin/analyselaptop-collector
systemctl start analyselaptop-collector
```

- [ ] New binary version string matches expected release
- [ ] Metrics resume within one cycle after restart
- [ ] No cert re-enrolment required (cert persists across binary swap)

---

## Sign-off

| Box | Commit | OS | Date | Tester | Deviations |
|---|---|---|---|---|---|
| `.33` (lab amd64) | | | | | |
| Pi arm64 | | | | | |
| `.32` (live, read-only) | | | | | |

File follow-up issues for anything that required manual intervention or
deviated from the documented procedure.
