# Infrastructure as Code — Deployment Strategy

> **Date:** 2026-07-25
> **Updated:** 2026-07-25 — Added Wi-Fi analysis Docker Compose configuration (§5.4).
> **Status:** Proposed
> **Scope:** Full v2 stack — backend hub (ingest / analyse / api / nginx / federation-agent), storage (VictoriaMetrics + PostgreSQL), frontend (SvelteKit static), and collector fleet (50+ nodes, each running the Python collector as a Docker container).
> **Collector v2 design:** See [`../collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md) for the full Python collector feature set and `requirements.txt`.

---

## 1. Tooling Decision

Two tools cover the entire stack. No additional orchestration layer is needed at this scale.

| Tool | Scope | Why |
|---|---|---|
| **Docker Compose** | Define and run all services — hub backend AND collector nodes | Declarative service graph; healthcheck-aware startup; works identically on amd64 and arm64; single `docker compose up -d` brings everything live |
| **GitHub Actions** | CI/CD — build images, run tests, push to GHCR, deploy hub, deploy collector fleet via SSH | Self-hosted runner on the hub handles `docker compose pull && up -d`; SSH-based collector deploys keep fleet management inside one pipeline |

**What is explicitly NOT used:**
- **Terraform:** Hub server is provisioned manually once (or with the cloud provider's web UI). At single-hub scale, Terraform state management adds complexity with no operational benefit.
- **Ansible:** Collector fleet is managed via SSH + `docker compose` commands invoked directly from GitHub Actions. No agent, no playbook runner, no inventory YAML.
- **Kubernetes / Helm / Swarm:** Overkill for a single-hub, 50-collector network probe.

---

## 2. Repository Layout

```
analyseLaptop/
├── deploy/
│   ├── hub/                          # Hub server stack
│   │   ├── docker-compose.yml        # Base: all hub services
│   │   ├── docker-compose.prod.yml   # Production overrides (resource limits, log drivers)
│   │   ├── docker-compose.dev.yml    # Dev overrides (bind mounts, no TLS, ports exposed)
│   │   ├── nginx/
│   │   │   ├── nginx.conf
│   │   │   └── ssl/                  # TLS cert/key (provisioned by bootstrap-hub.sh)
│   │   ├── postgres/
│   │   │   └── init.sql              # Schema init on first run
│   │   └── .env.example              # All required vars with dummy values — committed
│   │
│   ├── collector/                    # Collector node stack
│   │   ├── docker-compose.yml        # Base: analyselaptop-collector (all nodes)
│   │   ├── docker-compose.wifi.yml   # Wi-Fi override: NET_ADMIN cap + WIFI_INTERFACE env
│   │   ├── docker-compose.prod.yml   # Production overrides (resource limits, log drivers)
│   │   └── .env.example              # BACKEND_URL, COLLECTOR_ID, SITE_ID, SCAN_LEVEL_MAX,
│   │                                 # WIFI_ENABLED, WIFI_INTERFACE
│   │
│   └── scripts/
│       ├── bootstrap-hub.sh          # One-time: install Docker, create dirs, write secrets
│       ├── bootstrap-collector.sh    # One-time per node: install Docker, write .env
│       └── rotate-secrets.sh         # Rotate PG password + JWT secret in place
│
├── .github/
│   └── workflows/
│       ├── ci.yml                    # Lint, test, build on every PR
│       ├── build-images.yml          # Build + push all images to GHCR on merge to main
│       ├── deploy-hub.yml            # Pull new images + rolling restart on hub
│       └── deploy-collectors.yml     # SSH to each collector node: pull + restart
│
├── backend/
│   ├── ingest/                       # Go service
│   ├── analyse/                      # Python service
│   ├── api/                          # Go service
│   └── federation-agent/             # Python service (site-server side)
│
└── collector/                        # Python collector package
    ├── Dockerfile
    ├── requirements.txt
    └── src/
```

---

## 3. One-Time Hub Bootstrap

The hub server requires Docker and a secrets directory. Run once over SSH after provisioning the VM manually:

```bash
# deploy/scripts/bootstrap-hub.sh
#!/usr/bin/env bash
set -euo pipefail

# Install Docker (idempotent)
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  usermod -aG docker "$USER"
fi

# Create secrets directory (never inside repo or Docker volume)
mkdir -p /run/analyselaptop/secrets/pki
chmod 700 /run/analyselaptop/secrets

# Generate secrets (skip if already exist)
[ -f /run/analyselaptop/secrets/pg_password ] || \
  openssl rand -base64 32 > /run/analyselaptop/secrets/pg_password
[ -f /run/analyselaptop/secrets/jwt_secret ] || \
  openssl rand -base64 64 > /run/analyselaptop/secrets/jwt_secret

# Generate self-signed TLS cert for Nginx (replace with Let's Encrypt cert in production)
[ -f /run/analyselaptop/secrets/tls.crt ] || \
  openssl req -x509 -nodes -days 365 -newkey rsa:4096 \
    -keyout /run/analyselaptop/secrets/tls.key \
    -out    /run/analyselaptop/secrets/tls.crt \
    -subj   "/CN=analyselaptop-hub"

chmod 600 /run/analyselaptop/secrets/*
chmod 600 /run/analyselaptop/secrets/pki/* 2>/dev/null || true

echo "Bootstrap complete. Copy deploy/hub/.env.example to deploy/hub/.env and fill in values."
```

> **TLS in production:** Replace the self-signed cert with a Let's Encrypt cert obtained via `certbot certonly --standalone` before first deploy. Copy the resulting `fullchain.pem` and `privkey.pem` to `/run/analyselaptop/secrets/`. Nginx config references these paths.

---

## 4. Hub Stack — Docker Compose

### Base compose file

```yaml
# deploy/hub/docker-compose.yml
services:

  victoriametrics:
    image: victoriametrics/victoria-metrics:v1.101.0
    restart: unless-stopped
    volumes:
      - vm_data:/victoria-metrics-data
    command:
      - -retentionPeriod=90d
      - -storageDataPath=/victoria-metrics-data
    networks: [backend]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:8428/health"]
      interval: 15s
      timeout: 5s
      retries: 3

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB_FILE:       /run/secrets/pg_db
      POSTGRES_USER_FILE:     /run/secrets/pg_user
      POSTGRES_PASSWORD_FILE: /run/secrets/pg_password
    secrets: [pg_db, pg_user, pg_password]
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./postgres/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    networks: [backend]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$(cat /run/secrets/pg_user) -d $$(cat /run/secrets/pg_db)"]
      interval: 10s
      timeout: 5s
      retries: 5

  ingest:
    image: ghcr.io/xore/analyselaptop/ingest:${IMAGE_TAG:-latest}
    restart: unless-stopped
    secrets: [pg_user, pg_password, pg_db]
    environment:
      VM_ENDPOINT: http://victoriametrics:8428
      PG_HOST:     postgres
      PKI_DIR:     /run/secrets/pki
    volumes:
      - pki_data:/run/secrets/pki
    ports:
      - "0.0.0.0:4317:4317"   # OTLP/gRPC — mTLS-gated; collector-facing only
    networks: [backend, collector_facing]
    depends_on:
      postgres:        { condition: service_healthy }
      victoriametrics: { condition: service_healthy }

  analyse:
    image: ghcr.io/xore/analyselaptop/analyse:${IMAGE_TAG:-latest}
    restart: unless-stopped
    secrets: [pg_user, pg_password, pg_db]
    environment:
      VM_ENDPOINT:        http://victoriametrics:8428
      PG_HOST:            postgres
      ANALYSE_INTERVAL_S: "60"
    networks: [backend]
    depends_on:
      postgres:        { condition: service_healthy }
      victoriametrics: { condition: service_healthy }

  api:
    image: ghcr.io/xore/analyselaptop/api:${IMAGE_TAG:-latest}
    restart: unless-stopped
    secrets: [pg_user, pg_password, pg_db, jwt_secret]
    environment:
      VM_ENDPOINT: http://victoriametrics:8428
      PG_HOST:     postgres
    networks: [backend, frontend_facing]
    depends_on:
      postgres:        { condition: service_healthy }
      victoriametrics: { condition: service_healthy }

  federation-agent:
    image: ghcr.io/xore/analyselaptop/federation-agent:${IMAGE_TAG:-latest}
    restart: unless-stopped
    secrets: [pg_user, pg_password, pg_db]
    environment:
      VM_ENDPOINT:         http://victoriametrics:8428
      PG_HOST:             postgres
      GLOBAL_INGEST_URL:   ${GLOBAL_INGEST_URL:-}       # empty = federation disabled
      SITE_ID:             ${SITE_ID:-local}
      FEDERATION_INTERVAL: "60"
    networks: [backend]
    depends_on:
      postgres:        { condition: service_healthy }
      victoriametrics: { condition: service_healthy }

  nginx:
    image: nginx:1.27-alpine
    restart: unless-stopped
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - /run/analyselaptop/secrets/tls.crt:/etc/nginx/ssl/tls.crt:ro
      - /run/analyselaptop/secrets/tls.key:/etc/nginx/ssl/tls.key:ro
      - frontend_dist:/usr/share/nginx/html:ro
    ports:
      - "0.0.0.0:443:443"
    networks: [frontend_facing]
    depends_on: [api]

volumes:
  vm_data:
  pg_data:
  pki_data:
  frontend_dist:

networks:
  backend:          # VictoriaMetrics, PostgreSQL, ingest, analyse, api, federation-agent
  collector_facing: # ingest port 4317 only
  frontend_facing:  # nginx + api only

secrets:
  pg_db:
    file: /run/analyselaptop/secrets/pg_db
  pg_user:
    file: /run/analyselaptop/secrets/pg_user
  pg_password:
    file: /run/analyselaptop/secrets/pg_password
  jwt_secret:
    file: /run/analyselaptop/secrets/jwt_secret
  pki_ca_key:
    file: /run/analyselaptop/secrets/pki/ca.key
```

### Production override

```yaml
# deploy/hub/docker-compose.prod.yml
# Usage: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
services:
  victoriametrics:
    deploy:
      resources:
        limits: { memory: 1g }
    logging:
      driver: json-file
      options: { max-size: "50m", max-file: "5" }

  postgres:
    deploy:
      resources:
        limits: { memory: 512m }

  ingest:
    deploy:
      resources:
        limits: { memory: 256m }

  analyse:
    deploy:
      resources:
        limits: { memory: 512m }   # scikit-learn / PyTorch can spike

  api:
    deploy:
      resources:
        limits: { memory: 128m }

  federation-agent:
    deploy:
      resources:
        limits: { memory: 128m }

  nginx:
    deploy:
      resources:
        limits: { memory: 64m }
```

### Secrets: file-based, never env vars

Docker Compose `secrets:` mounts files under `/run/secrets/` inside each container. They do not appear in `docker inspect`, logs, or crash dumps. Applications read the file content at startup.

```bash
# deploy/scripts/rotate-secrets.sh
#!/usr/bin/env bash
set -euo pipefail
cd /run/analyselaptop/secrets

openssl rand -base64 32 > pg_password.new && mv pg_password.new pg_password
openssl rand -base64 64 > jwt_secret.new  && mv jwt_secret.new  jwt_secret
chmod 600 pg_password jwt_secret

cd "$(git rev-parse --show-toplevel)"
docker compose -f deploy/hub/docker-compose.yml -f deploy/hub/docker-compose.prod.yml \
  restart postgres api federation-agent
echo "Secrets rotated. Re-enroll collectors if PKI CA was also rotated."
```

---

## 5. Collector Nodes — Docker Compose

Every collector node runs the Python collector as a single Docker container managed by `docker compose`. Docker must be installed on each node (handled by `bootstrap-collector.sh`).

### 5.1 One-time node bootstrap

```bash
# deploy/scripts/bootstrap-collector.sh
# Run once on each new collector node (SSH from operator workstation or CI)
#!/usr/bin/env bash
set -euo pipefail

COLLECTOR_ID="${1:?Usage: bootstrap-collector.sh <collector-id> <backend-url> <site-id> [wifi-iface]}"
BACKEND_URL="${2:?}"
SITE_ID="${3:?}"
WIFI_IFACE="${4:-}"   # optional; pass wlan0 / wlan1 if the node has a Wi-Fi adapter

# Install Docker (idempotent)
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  usermod -aG docker "$USER"
fi

# State + PKI directories
mkdir -p /var/lib/analyselaptop/pki /var/lib/analyselaptop/data
chmod 750 /var/lib/analyselaptop

# Write .env for docker compose (collector-specific values)
cat > /var/lib/analyselaptop/.env <<EOF
COLLECTOR_ID=${COLLECTOR_ID}
BACKEND_URL=${BACKEND_URL}
SITE_ID=${SITE_ID}
SCAN_LEVEL_MAX=2
IMAGE_TAG=latest
# Wi-Fi — set WIFI_ENABLED=true and WIFI_INTERFACE=<iface> on nodes with a wireless adapter
WIFI_ENABLED=${WIFI_IFACE:+true}
WIFI_ENABLED=${WIFI_IFACE:-false}
WIFI_INTERFACE=${WIFI_IFACE:-wlan0}
EOF
chmod 600 /var/lib/analyselaptop/.env

echo "Node bootstrap complete."
echo "  Wi-Fi probe: ${WIFI_IFACE:-disabled (no iface given)}"
echo "  Run: docker compose -f /opt/analyselaptop/docker-compose.yml up -d"
```

### 5.2 Base collector compose file

```yaml
# deploy/collector/docker-compose.yml
services:
  collector:
    image: ghcr.io/xore/analyselaptop/collector:${IMAGE_TAG:-latest}
    restart: unless-stopped
    network_mode: host        # Required: raw socket access for ICMP, AF_PACKET, Wi-Fi
    pid: host                 # Required: /proc/<pid> access for process metrics
    volumes:
      - /var/lib/analyselaptop:/var/lib/analyselaptop   # state, PKI, data store
      - /sys/fs/bpf:/sys/fs/bpf                         # eBPF pin filesystem
      - /sys/kernel/debug:/sys/kernel/debug:ro           # eBPF debug (if needed)
    environment:
      COLLECTOR_ID:    ${COLLECTOR_ID}
      BACKEND_URL:     ${BACKEND_URL}
      SITE_ID:         ${SITE_ID}
      SCAN_LEVEL_MAX:  ${SCAN_LEVEL_MAX:-2}
      PKI_DIR:         /var/lib/analyselaptop/pki
      DATA_DIR:        /var/lib/analyselaptop/data
      WIFI_ENABLED:    ${WIFI_ENABLED:-false}
      WIFI_INTERFACE:  ${WIFI_INTERFACE:-wlan0}
    cap_add:
      - NET_RAW       # ICMP raw sockets, AF_PACKET (broadcast/multicast capture)
      - BPF           # eBPF program loading
      - PERFMON       # eBPF perf events
      - SYS_PTRACE    # /proc/<pid> access for process metrics
    # NET_ADMIN is NOT in the base compose — it is added only via docker-compose.wifi.yml
    # on nodes that have a wireless adapter. See §5.4.
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:9090/healthz')"]
      interval: 30s
      timeout: 5s
      retries: 3
```

> **`network_mode: host`** is required because the collector uses raw sockets (ICMP), AF_PACKET (broadcast capture), and reads `/proc/net/dev` for interface metrics. Bridge networking would block these. The container does **not** expose any inbound ports — all traffic is outbound to `BACKEND_URL:4317`.

### 5.3 Production override

```yaml
# deploy/collector/docker-compose.prod.yml
services:
  collector:
    deploy:
      resources:
        limits:
          memory: 256m    # Sufficient for Python + scapy + bcc + asyncio loop
          cpus: "0.5"     # Conservative on Pi 3B / Pi 4
    logging:
      driver: json-file
      options: { max-size: "20m", max-file: "3" }
```

---

### 5.4 Wi-Fi Analysis — Docker Compose Configuration

The collector's Wi-Fi analysis module (`checks/net_wifi_linux.py`) uses the `iw` CLI tool to read link state and perform passive AP scans. This requires specific Linux capabilities and the `iw` package inside the container image. This section documents all configuration requirements for Wi-Fi-enabled collector nodes.

#### Why NET_ADMIN is required for Wi-Fi

`iw` communicates with the kernel via **nl80211** (netlink family 802.11). The kernel requires `CAP_NET_ADMIN` for nl80211 operations that change interface state (`iw dev wlan0 scan`) or read protected wireless attributes. Without it, `iw scan` returns `Operation not permitted` even when running as root inside the container.

| `iw` operation | Capability needed | What it reads |
|---|---|---|
| `iw dev wlan0 link` | none (read-only link state) | BSSID, SSID, signal (dBm), bitrate |
| `iw dev wlan0 scan` | **CAP_NET_ADMIN** | Active AP list, RSSI per AP, channel, security |
| `iw dev wlan0 station dump` | **CAP_NET_ADMIN** | Peer station stats (mesh / AP mode only) |
| Monitor mode (`iw dev wlan0 set type monitor`) | **CAP_NET_ADMIN** | Passive 802.11 frame capture (not used by default) |

Active scanning (`iw scan`) transmits probe request frames on each channel. It is the standard method for discovering all visible APs and their RSSI. This is the default mode used by `net_wifi_linux.py`.

#### Wi-Fi compose override file

Rather than adding `NET_ADMIN` to the base compose (which would give it to all nodes including wired-only ones), it is applied as a named override file that is only included on Wi-Fi-capable nodes.

```yaml
# deploy/collector/docker-compose.wifi.yml
# Applied on nodes with a Wi-Fi adapter:
#   docker compose \
#     -f docker-compose.yml \
#     -f docker-compose.wifi.yml \
#     -f docker-compose.prod.yml \
#     up -d
services:
  collector:
    cap_add:
      - NET_ADMIN     # Required for: iw scan (nl80211), iw station dump, monitor mode setup
    environment:
      WIFI_ENABLED:   "true"
      WIFI_INTERFACE: ${WIFI_INTERFACE:-wlan0}   # Override in .env per node
```

#### `iw` in the collector Dockerfile

The `iw` package must be present in the collector image. It is a small (~150 KB) CLI tool and should be installed unconditionally — nodes without Wi-Fi simply never invoke it.

```dockerfile
# collector/Dockerfile  — relevant excerpt
FROM python:3.12-slim

# System tools required by collector checks
RUN apt-get update && apt-get install -y --no-install-recommends \
      iw            `# Wi-Fi: iw dev <iface> link + scan (net_wifi_linux.py)` \
      iproute2      `# ip link, ip route reads` \
      iputils-ping  `# fallback ping (ICMP check uses raw socket; this is for diagnostics)` \
      libcap2-bin   `# setcap (applied at image build for capability drops)` \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app
WORKDIR /app

ENTRYPOINT ["python3", "-m", "collector"]
```

#### Per-node `.env` for Wi-Fi nodes

```bash
# /var/lib/analyselaptop/.env  — Wi-Fi-capable node example
COLLECTOR_ID=probe-site-a
BACKEND_URL=https://hub.internal:4317
SITE_ID=site-a
SCAN_LEVEL_MAX=2
IMAGE_TAG=latest

# Wi-Fi
WIFI_ENABLED=true
WIFI_INTERFACE=wlan0      # Run `iw dev` on the node to confirm the interface name
                           # Common values: wlan0 (Pi built-in), wlan1 (USB dongle)
```

```bash
# /var/lib/analyselaptop/.env  — wired-only node example
COLLECTOR_ID=probe-ot-floor1
BACKEND_URL=https://hub.internal:4317
SITE_ID=ot-floor1
SCAN_LEVEL_MAX=2
IMAGE_TAG=latest

# Wi-Fi disabled — NET_ADMIN not added (docker-compose.wifi.yml not used)
WIFI_ENABLED=false
WIFI_INTERFACE=wlan0      # Value ignored when WIFI_ENABLED=false
```

#### Collector inventory JSON — Wi-Fi flag

Add `"wifi_iface"` to each entry in `deploy/collector-inventory.json`. The deploy workflow uses this field to decide whether to include `docker-compose.wifi.yml` in the compose command:

```json
[
  { "id": "probe-site-a",   "host": "192.168.1.50", "user": "pi",        "arch": "arm64", "wifi_iface": "wlan0"  },
  { "id": "probe-site-b",   "host": "10.20.1.5",    "user": "ubuntu",    "arch": "amd64", "wifi_iface": "wlan1"  },
  { "id": "probe-ot-floor1","host": "10.10.0.20",   "user": "collector", "arch": "arm64", "wifi_iface": null    }
]
```

`wifi_iface: null` → wired-only node → `docker-compose.wifi.yml` is NOT included → `NET_ADMIN` is NOT granted.

#### Updated deploy-collectors.yml — Wi-Fi-aware compose command

The SSH deploy step must detect `wifi_iface` and conditionally include the Wi-Fi override:

```yaml
# .github/workflows/deploy-collectors.yml — updated deploy step
- name: Deploy to collector nodes
  env:
    IMAGE_TAG: ${{ github.sha }}
    TARGET_ID: ${{ github.event.inputs.collector_id }}
  run: |
    jq -c '.[]' deploy/collector-inventory.json | while IFS= read -r node; do
      ID=$(echo "$node"         | jq -r '.id')
      HOST=$(echo "$node"       | jq -r '.host')
      USER=$(echo "$node"       | jq -r '.user')
      WIFI=$(echo "$node"       | jq -r '.wifi_iface // empty')

      [ -n "$TARGET_ID" ] && [ "$ID" != "$TARGET_ID" ] && continue

      # Build the compose file list: base + optional wifi override + prod
      COMPOSE_FILES="-f /opt/analyselaptop/docker-compose.yml"
      [ -n "$WIFI" ] && COMPOSE_FILES="$COMPOSE_FILES -f /opt/analyselaptop/docker-compose.wifi.yml"
      COMPOSE_FILES="$COMPOSE_FILES -f /opt/analyselaptop/docker-compose.prod.yml"

      echo "=== Deploying to $ID ($HOST) wifi=${WIFI:-none} ==="
      ssh -i ~/.ssh/deploy_key "$USER@$HOST" bash -s <<REMOTE
        set -euo pipefail

        IMAGE_TAG=${IMAGE_TAG} docker compose ${COMPOSE_FILES} pull collector
        IMAGE_TAG=${IMAGE_TAG} docker compose ${COMPOSE_FILES} up -d --no-deps collector

        for i in \$(seq 1 6); do
          STATUS=\$(docker inspect --format='{{.State.Health.Status}}' \
            "\$(docker compose ${COMPOSE_FILES} ps -q collector)" 2>/dev/null || echo "starting")
          [ "\$STATUS" = "healthy" ] && echo "  ✓ Healthy" && exit 0
          echo "  Waiting (\$i/6) — \$STATUS"; sleep 5
        done
        echo "  ✗ Health check failed on ${ID}" >&2; exit 1
REMOTE
      echo "=== $ID done ==="
    done
```

#### Wi-Fi check behaviour in net_wifi_linux.py

The collector reads `WIFI_ENABLED` at startup. When `false`, the Wi-Fi check module is never loaded:

```python
# collector/config.py — WifiConfig (from COLLECTOR-V2-REFACTOR.md §9, extended)
class WifiConfig(BaseModel):
    enabled: bool = False          # Disabled by default; set via WIFI_ENABLED=true in .env
    interface: str = "wlan0"       # Set via WIFI_INTERFACE in .env
    scan_interval_s: int = 60      # Active scan every 60 s (transmits probe requests)
    ap_change_alert: bool = True   # Emit wifi_ap_changes_total counter on BSSID change
    rssi_warn_dbm: int = -75       # wifi_rssi_dbm < rssi_warn_dbm → log warning
```

Metrics emitted when Wi-Fi is enabled (see COLLECTOR-V2-REFACTOR.md §10):

```
wifi_rssi_dbm{collector_id, site_id, interface, bssid, ssid}   gauge   # Signal strength dBm
wifi_link_speed_mbps{collector_id, site_id, interface}         gauge   # Negotiated PHY rate
wifi_channel{collector_id, site_id, interface, bssid}          gauge   # Current channel number
wifi_ap_changes_total{collector_id, site_id, interface}        counter # BSSID/roaming events
wifi_scan_aps_visible{collector_id, site_id, interface}        gauge   # APs seen in last scan
```

#### Monitor mode — NOT used by default

Passive 802.11 frame capture (monitor mode) is **not** enabled in the default configuration. It would require:
1. Putting the adapter into monitor mode: `iw dev wlan0 set type monitor` (`CAP_NET_ADMIN`)
2. Bringing the monitor interface up: `ip link set wlan0mon up` (`CAP_NET_ADMIN`)
3. Capturing with scapy or tcpdump on the monitor interface (`CAP_NET_RAW`)

Monitor mode disconnects the adapter from its associated AP, meaning the node loses its Wi-Fi network path. This is only viable if the node has a **second** Wi-Fi adapter dedicated to monitoring, or if it is connected to the hub via Ethernet. It is tracked as a future capability in [`../collector/ROADMAP.md`](../collector/ROADMAP.md).

#### Capability summary for collector nodes

| Capability | Base compose | + wifi override | Why |
|---|---|---|---|
| `NET_RAW` | ✅ | ✅ | ICMP raw sockets, AF_PACKET broadcast capture (scapy) |
| `NET_ADMIN` | ❌ | ✅ | `iw scan` nl80211, eBPF socket filters, monitor mode setup |
| `BPF` | ✅ | ✅ | eBPF program loading (flow_tracker.py) |
| `PERFMON` | ✅ | ✅ | eBPF perf event maps |
| `SYS_PTRACE` | ✅ | ✅ | `/proc/<pid>/` access for process metrics |

---

## 6. GitHub Actions — CI/CD Pipelines

### Pipeline overview

```
PR opened
  └─▶ ci.yml            — lint, test, build check (no push)

Merge to main
  └─▶ build-images.yml  — build all images (collector + backend), push to GHCR
        └─▶ (on success) deploy-hub.yml        — self-hosted runner: pull + rolling restart
        └─▶ (on success) deploy-collectors.yml — SSH to each node: pull + restart
```

### `ci.yml` — test all services on every PR

```yaml
# .github/workflows/ci.yml
name: CI
on:
  pull_request:
    branches: [main]

jobs:
  test-collector:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r collector/requirements.txt
      - run: pytest collector/tests/ -v
      - run: ruff check collector/src/

  test-ingest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: '1.23' }
      - run: go test ./backend/ingest/... -race -count=1

  test-api:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: '1.23' }
      - run: go test ./backend/api/... -race -count=1

  test-analyse:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r backend/analyse/requirements.txt
      - run: pytest backend/analyse/tests/ -v

  test-federation-agent:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r backend/federation-agent/requirements.txt
      - run: pytest backend/federation-agent/tests/ -v

  build-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '22' }
      - run: npm ci && npm run build
        working-directory: frontend

  secret-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### `build-images.yml` — build + push to GHCR on merge to main

```yaml
# .github/workflows/build-images.yml
name: Build and Push Images
on:
  push:
    branches: [main]
    tags: ['v*']

env:

  REGISTRY: ghcr.io
  OWNER:    ${{ github.repository_owner }}

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        include:
          - service: ingest
            context: backend/ingest
          - service: analyse
            context: backend/analyse
          - service: api
            context: backend/api
          - service: federation-agent
            context: backend/federation-agent
          - service: collector
            context: collector
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.OWNER }}/analyselaptop/${{ matrix.service }}
          tags: |
            type=sha,prefix=,suffix=,format=short
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=raw,value=latest,enable=${{ github.ref == 'refs/heads/main' }}
      - uses: docker/build-push-action@v6
        with:
          context: ${{ matrix.context }}
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to:   type=gha,mode=max
          platforms: linux/amd64,linux/arm64   # arm64 for Raspberry Pi collector nodes
```

### `deploy-hub.yml` — rolling zero-downtime deploy on the hub

```yaml
# .github/workflows/deploy-hub.yml
name: Deploy Hub
on:
  workflow_run:
    workflows: ["Build and Push Images"]
    types: [completed]
    branches: [main]

jobs:
  deploy:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: self-hosted   # Self-hosted runner on the hub server
    environment: production
    concurrency:
      group: hub-deploy
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4

      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Pull updated images
        run: |
          docker compose \
            -f deploy/hub/docker-compose.yml \
            -f deploy/hub/docker-compose.prod.yml \
            pull
        env:
          IMAGE_TAG: ${{ github.sha }}

      - name: Pre-deploy health check
        run: curl -sf http://localhost:8428/health

      - name: Rolling restart — ingest
        run: |
          docker compose \
            -f deploy/hub/docker-compose.yml \
            -f deploy/hub/docker-compose.prod.yml \
            up -d --no-deps ingest
        env:
          IMAGE_TAG: ${{ github.sha }}

      - name: Wait for ingest healthy
        run: |
          for i in $(seq 1 12); do
            STATUS=$(docker inspect --format='{{.State.Health.Status}}' \
              "$(docker compose -f deploy/hub/docker-compose.yml ps -q ingest)")
            [ "$STATUS" = "healthy" ] && break
            echo "Waiting ($i/12) — status: $STATUS"; sleep 5
          done

      - name: Rolling restart — analyse, api, federation-agent
        run: |
          docker compose \
            -f deploy/hub/docker-compose.yml \
            -f deploy/hub/docker-compose.prod.yml \
            up -d --no-deps analyse api federation-agent
        env:
          IMAGE_TAG: ${{ github.sha }}

      - name: Post-deploy health check
        run: curl -sf https://localhost/api/v1/health --insecure

      - name: Prune old images
        run: docker image prune -f --filter "until=48h"
```

### `deploy-collectors.yml` — see §5.4 for the Wi-Fi-aware version

The complete `deploy-collectors.yml` workflow, including the conditional `docker-compose.wifi.yml` inclusion based on `wifi_iface` in the inventory, is documented in §5.4 above.

---

## 7. Collector Fleet Update Flow

```
GitHub Actions — build-images.yml
  └─▶ Builds collector:${SHA} image for linux/amd64 + linux/arm64
  └─▶ Pushes to GHCR

GitHub Actions — deploy-collectors.yml (auto-triggered on build success)
  For each node in collector-inventory.json (sequentially):
    1. SSH to node
    2. Determine compose files: base [+ wifi override] + prod  ← based on wifi_iface field
    3. docker compose pull collector          ← pulls new image from GHCR
    4. docker compose up -d --no-deps collector  ← zero-downtime restart
    5. Wait up to 30s for healthcheck=healthy
    6. On failure: exit 1 — subsequent nodes NOT updated (fail-fast)
    7. On success: proceed to next node

Manual single-node update:
  GitHub Actions → deploy-collectors.yml → workflow_dispatch → collector_id=probe-site-a
```

Sequential (not parallel) updates ensure at most one collector is unavailable at a time. Change to `xargs -P 5` in the shell loop to update 5 nodes in parallel if speed matters more than blast radius.

---

## 8. Secrets Management

| Secret | Where stored | How injected | Rotation |
|---|---|---|---|
| PostgreSQL password | `/run/analyselaptop/secrets/pg_password` on hub | Docker Compose `secrets:` → `/run/secrets/pg_password` | `rotate-secrets.sh` + restart postgres, api, federation-agent |
| JWT signing key | `/run/analyselaptop/secrets/jwt_secret` | Docker Compose `secrets:` | `rotate-secrets.sh` + restart api |
| TLS cert + key | `/run/analyselaptop/secrets/tls.{crt,key}` | Bind-mounted into nginx (read-only) | Replace files + `docker compose restart nginx` |
| PKI CA key | `/run/analyselaptop/secrets/pki/ca.key` (mode 0600) | Bind-mounted into ingest | Generate new CA + re-enroll all collectors |
| Collector `.env` | `/var/lib/analyselaptop/.env` on each node (mode 0600) | `docker compose --env-file` | Update file + `docker compose up -d` |
| Collector PKI leaf cert | `/var/lib/analyselaptop/pki/` on each node | Volume mount into container | Auto-renews when `days_remaining < 14` (collector `pki/renew.py`) |
| Collector SSH deploy key | GitHub secret `COLLECTOR_SSH_KEY` | `deploy-collectors.yml` ssh-agent | Rotate in GitHub + update `authorized_keys` on nodes |
| GitHub Runner token | GitHub repo secret `RUNNER_TOKEN` | `docker run -e` at runner start | Regenerate in GitHub settings |
| GHCR push token | `GITHUB_TOKEN` (automatic) | GitHub Actions env | Auto-rotated per workflow run |

**Rules:**
- No secrets in `.env` files that touch Git. `.env.example` with dummy values is committed; real `.env` is gitignored.
- No `environment:` blocks for sensitive values. All secrets via Docker Compose `secrets:` or collector-local files.
- Secret files: `chmod 600`, owned by root (hub) or collector user (nodes).
- `gitleaks` scan on every PR catches accidental commits.

---

## 9. Observability of the Stack Itself

| What to monitor | How | Metric / source |
|---|---|---|
| Hub Docker service health | `docker compose ps` + healthcheck status in VM | `analyselaptop_service_up{service}` |
| VictoriaMetrics self-metrics | `/metrics` scraped by VM itself | `vm_app_uptime_seconds`, disk usage |
| PostgreSQL | `pg_stat_activity` via analyse service | Hub-internal |
| **Collector fleet liveness** | `collector_heartbeat_total` stale >5 min → vmalert `CollectorSilent` | **Python collector native** |
| **Collector host health** | `host_cpu_usage_pct`, `host_mem_available_bytes`, `host_disk_free_bytes` | **Python collector native** |
| **Collector container state** | `docker inspect` health status via deploy workflow | `healthy` / `unhealthy` |
| **Collector health score** | `collector_health_score < 0.6` → vmalert `CollectorHealthDegraded` | **Python collector native** |
| **Wi-Fi probe state** | `wifi_rssi_dbm` absent for >2 intervals → vmalert `WifiProbeStale` | **Python collector native** |
| Certificate expiry | `collector_cert_days_left < 14` → vmalert `CollectorCertExpiringSoon` | **Python collector native** |
| GitHub Actions run status | GitHub notifications + optional webhook to alert system | GitHub |

---

## 10. Open Questions

| # | Question | Decision point |
|---|---|---|
| Q1 | Collector node Docker install: `get.docker.com` vs distro package | Distro package preferred for long-term stability on Pi OS / Ubuntu; `get.docker.com` is faster for one-offs |
| Q2 | Collector inventory source: static JSON vs dynamic (PG `collectors` table) | Dynamic inventory (query PG via API) would auto-register new nodes — worth implementing at >20 collectors |
| Q3 | Air-gapped deployments | Replace GHCR pull with a local Docker registry mirror (`registry:2` container on hub); change `image:` to point at `hub-ip:5000/analyselaptop/collector` |
| Q4 | TLS for Nginx | Self-signed cert in bootstrap is fine for internal/OT deployments; replace with Let's Encrypt (`certbot`) for public-facing hubs |
| Q5 | v1 → v2 migration | v1 nodes run standalone Python or binary outside Docker; migrate by running `bootstrap-collector.sh` and enrolling the node in the new PKI. No node_exporter removal needed (v2 collector container bundles all host metrics). |
| Q6 | Wi-Fi monitor mode | Requires a second Wi-Fi adapter dedicated to passive capture; tracked in ROADMAP.md. Not included in base configuration. |
| Q7 | Wi-Fi interface name stability | On some Pi OS versions, `wlan0` can become `wlan1` after a kernel update. Use `SUBSYSTEM=="net", ACTION=="add", ATTR{address}=="<mac>", NAME="wlan0"` udev rule to pin the name. Document in bootstrap-collector.sh. |
