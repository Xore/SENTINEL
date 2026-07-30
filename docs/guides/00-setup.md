# Setup — v2 Collector

This guide covers installing and bootstrapping the v2 Python collector on a new node.
The collector is a **Python 3.12 asyncio process** shipped as a PyInstaller single-file
binary. It has no web UI of its own — all data is pushed to the hub via OTLP/gRPC.

> **Target platforms:** Linux amd64, Linux arm64 (Raspberry Pi 5 or better), Windows amd64.
> 32-bit ARM is out of scope — the Pi 5 is arm64-only. Where a Pi 5 lacks headroom for a
> site's probe load, deploy a small-form-factor x86-64 PC instead
> ([ADR 0012](../architecture/decisions/0012-collector-reference-hardware.md)).
> **Full design:** [`docs/collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md)

---

## Prerequisites

### Linux (Debian/Ubuntu/Raspberry Pi OS)

```bash
# Python 3.12 and system tools
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip \
    iw ethtool iproute2 dnsutils snmp mtr-tiny curl git

# Optional: eBPF flow tracking (Phase C13 only — requires kernel ≥5.8)
sudo apt-get install -y python3-bpfcc
```

### Windows

- Python 3.12 from [python.org](https://www.python.org/downloads/) (add to PATH)
- `iw` / `ethtool` not required — Windows checks use `netsh` and `psutil` only

---

## Node roles

| Role | What runs on the node | Pushes to |
|---|---|---|
| **collector** | `analyselaptop-collector` binary | Hub ingest (OTLP/gRPC) |
| **hub** | Ingest service + analyse service + API + frontend | — (receives from collectors) |

This guide covers the **collector** role. Hub setup is in
[`docs/collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md) §12.

---

## Quick start (pre-built binary)

### 1. Download the binary

```bash
# Linux amd64
curl -L -o analyselaptop-collector \
  https://github.com/Xore/analyseLaptop/releases/latest/download/analyselaptop-collector-linux-amd64
chmod +x analyselaptop-collector

# Linux arm64 (Raspberry Pi)
curl -L -o analyselaptop-collector \
  https://github.com/Xore/analyseLaptop/releases/latest/download/analyselaptop-collector-linux-arm64
chmod +x analyselaptop-collector
```

### 2. Create config file

```yaml
# /etc/analyselaptop/collector.yaml
collector_id: pi-bedroom
site_id: home
scan_level_max: 2

backend:
  url: https://<hub-ip>:4317
  pki_dir: /var/lib/analyselaptop/pki
  retry_max: 10
  retry_backoff_s: 2.0

wifi:
  enabled: true
  interface: wlan0
  scan_interval_s: 60
  ap_change_alert: true

bcast_mcast:
  enabled: true
  interface: eth0
  window_s: 30
  top_n: 10
  interval_s: 300

log_level: INFO
data_dir: /var/lib/analyselaptop/data
```

### 3. Grant capabilities

The collector needs `CAP_NET_RAW` for ICMP probes, MTR hop-tracing, and
broadcast/multicast capture. Grant it to the binary (preferred over running as root):

```bash
sudo setcap cap_net_raw+ep ./analyselaptop-collector
```

For eBPF flow tracking (Phase C13, optional):
```bash
sudo setcap cap_net_raw,cap_bpf,cap_perfmon+ep ./analyselaptop-collector
```

### 4. PKI enrolment

Before the first run, enrol the collector with the hub to receive its mTLS certificate:

```bash
mkdir -p /var/lib/analyselaptop/pki
./analyselaptop-collector enroll \
  --hub https://<hub-ip>:4317 \
  --enroll-token <token-from-hub>
```

This writes `collector.key` and `collector.crt` into `pki_dir`. The collector
auto-renews the cert when fewer than 14 days remain.

### 5. Run

```bash
./analyselaptop-collector --config /etc/analyselaptop/collector.yaml
```

Structured JSON logs go to stdout. On first startup the scheduler runs a full
cycle; metrics appear in the hub within one cycle (default ≤30 s).

---

## Systemd service (Linux)

```ini
# /etc/systemd/system/analyselaptop-collector.service
[Unit]
Description=analyseLaptop Collector v2
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=analyselaptop
ExecStart=/usr/local/bin/analyselaptop-collector --config /etc/analyselaptop/collector.yaml
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
AmbientCapabilities=CAP_NET_RAW
# Add CAP_BPF CAP_PERFMON here if eBPF is enabled

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd -r -s /sbin/nologin analyselaptop
sudo cp analyselaptop-collector /usr/local/bin/
sudo systemctl daemon-reload
sudo systemctl enable --now analyselaptop-collector
sudo systemctl status analyselaptop-collector
```

---

## Build from source

```bash
git clone https://github.com/Xore/analyseLaptop.git
cd analyseLaptop/collector

# Development venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Run tests
pytest tests/ -v
mypy . --ignore-missing-imports
ruff check .

# Build single-file binary (Linux amd64)
pyinstaller --onefile --name analyselaptop-collector __main__.py
# Output: dist/analyselaptop-collector

# Build for arm64 via Docker buildx
docker buildx build \
  --platform linux/arm64 \
  -f Dockerfile.collector-arm64 \
  --output type=local,dest=dist/arm64 \
  .
```

---

## Verify the collector is running

```bash
# Service status
systemctl status analyselaptop-collector

# Live logs
journalctl -u analyselaptop-collector -f

# Check metrics are reaching the hub (from hub node)
curl -s http://<hub-ip>:8080/api/collectors | jq '.[] | select(.id=="pi-bedroom")'
```

---

## Capability reference

| Capability | Required for | Notes |
|---|---|---|
| `CAP_NET_RAW` | ICMP probes, MTR hop-tracing, bcast/mcast capture | Always required |
| `CAP_NET_ADMIN` | Wi-Fi `iw scan` (some kernels) | Only if Wi-Fi scan enabled |
| `CAP_BPF` | eBPF flow tracking (Phase C13) | Linux kernel ≥5.8 only |
| `CAP_PERFMON` | eBPF flow tracking (Phase C13) | Linux kernel ≥5.8 only |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `PermissionError` on ICMP socket | `CAP_NET_RAW` not set | `sudo setcap cap_net_raw+ep ./analyselaptop-collector` |
| `ImportError: bcc` | `python3-bpfcc` not installed | `sudo apt install python3-bpfcc` or disable eBPF in config |
| Cert error on gRPC connect | `pki_dir` cert not enrolled | Run `enroll` command first |
| PyInstaller binary slow to start on Pi | Self-extraction to `/tmp` | Expected on cold start; `TimeoutStartSec=30` in systemd unit |
| Wi-Fi scan returns empty | `CAP_NET_ADMIN` missing | `sudo setcap cap_net_raw,cap_net_admin+ep ./analyselaptop-collector` |
