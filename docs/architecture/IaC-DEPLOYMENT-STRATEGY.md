# Infrastructure as Code — Deployment Strategy

> **Date:** 2026-07-25  
> **Updated:** 2026-07-25 — v2 collector bundles host metrics natively; `node_exporter` removed from collector role.  
> **Status:** Proposed  
> **Scope:** Full v2 stack — backend hub (ingest / analyse / api / nginx), storage (VictoriaMetrics + PostgreSQL), frontend (SvelteKit static), and collector fleet (50+ nodes).  
> This document is the IaC plan. Actual files live under `deploy/`.  
> **Collector v2 design:** See [`../collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md) for the full collector feature set and go.mod.

---

## 1. Tooling Decision

Three tools cover the full stack cleanly. Each one is scoped to what it does best:

| Tool | Scope | Why |
|---|---|---|
| **Terraform** | Provision server infrastructure (VM, firewall, DNS, TLS cert) | Declarative; state-tracked; idempotent; de facto standard for infra provisioning in 2025–2026 |
| **Ansible** | Configure OS, install Docker, deploy collector binaries via systemd on edge nodes | Agentless SSH push; ideal for heterogeneous ARM/amd64 edge nodes without Docker; Ansible + systemd is the documented pattern for edge collector deployment |
| **Docker Compose** | Define and run the backend stack on the hub server | Native dependency graph, healthcheck-aware startup; single-node production is the primary Docker Compose use case |
| **GitHub Actions** | CI/CD — build images, run tests, push to GHCR, trigger deploys | Already in use; self-hosted runner on the hub server handles the `docker compose pull && up -d` step |

**What is explicitly NOT used:**
- **Kubernetes:** Overkill for a single-hub, 50-collector network probe. k8s adds etcd, CNI, and scheduler complexity with zero benefit at this scale.
- **Helm:** No Kubernetes, no Helm.
- **Docker Swarm:** Single-server stack does not need Swarm orchestration. `docker compose` is sufficient and simpler.
- **Pulumi/CDK:** Team is already familiar with Terraform HCL; no advantage in switching to a general-purpose language IaC tool at this scale.

---

## 2. Repository Layout

```
analyse Laptop/
├── deploy/
│   ├── terraform/                  # Hub server provisioning
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   ├── providers.tf
│   │   └── modules/
│   │       ├── server/             # VM / bare-metal server resource
│   │       ├── firewall/           # Firewall rules: 443, 4317, 22 only
│   │       └── dns/                # A/AAAA record for the hub
│   │
│   ├── ansible/                    # Collector fleet configuration
│   │   ├── inventory/
│   │   │   ├── hosts.yml           # Collector host list (generated or manual)
│   │   │   └── group_vars/
│   │   │       ├── all.yml         # Common vars: backend URL, PKI endpoint
│   │   │       ├── linux_arm64.yml
│   │   │       └── linux_amd64.yml
│   │   ├── roles/
│   │   │   ├── collector/          # Install binary, systemd unit, enroll cert
│   │   │   ├── ebpf_caps/          # Set CAP_BPF + CAP_NET_ADMIN + CAP_PERFMON
│   │   │   └── firewall/           # UFW: allow only outbound 4317 to hub
│   │   ├── playbooks/
│   │   │   ├── deploy-collector.yml
│   │   │   ├── update-collector.yml
│   │   │   └── revoke-collector.yml
│   │   └── ansible.cfg
│   │
│   ├── compose/                    # Hub stack
│   │   ├── docker-compose.yml      # Base (all services)
│   │   ├── docker-compose.prod.yml # Production overrides (resource limits, log drivers)
│   │   ├── docker-compose.dev.yml  # Dev overrides (bind mounts, no TLS, ports exposed)
│   │   ├── nginx/
│   │   │   ├── nginx.conf
│   │   │   └── ssl/                # TLS cert/key (provisioned by Terraform / Let's Encrypt)
│   │   └── .env.example            # All required vars with dummy values — committed
│   │
│   └── scripts/
│       ├── bootstrap-hub.sh        # One-time: install Docker, create dirs, set perms
│       ├── enroll-collector.sh     # Run on each new collector node
│       └── rotate-secrets.sh       # Rotate PG password + JWT secret in place
│
├── .github/
│   └── workflows/
│       ├── ci.yml                  # Build + test all services on PR
│       ├── build-images.yml        # Build + push to GHCR on merge to main
│       ├── deploy-hub.yml          # Pull new images + docker compose up -d on hub
│       └── deploy-collector.yml    # Trigger Ansible playbook for collector fleet update
│
└── collector/
    └── dist/                       # Cross-compiled binaries (linux/arm64, linux/amd64, etc.)
```

---

## 3. Terraform — Hub Server Provisioning

### What it manages

- **Server resource:** VM (Hetzner/DigitalOcean/bare-metal) or physical NUC. Terraform manages the lifecycle: create, resize, destroy.
- **Firewall:** Only three inbound ports are ever open:
  - `22/tcp` — SSH, restricted to operator IPs
  - `443/tcp` — HTTPS (Nginx → SvelteKit frontend + API)
  - `4317/tcp` — OTLP/gRPC (collector ingest, mTLS-gated)
  - Everything else: deny inbound by default.
- **DNS:** A/AAAA record for `monitor.internal` or the operator's domain.
- **TLS certificate:** ACME / Let's Encrypt via `terraform-provider-acme` for the Nginx cert, OR a self-signed cert for air-gapped deployments (`tls_self_signed_cert` resource).

### State backend

For a single-operator project, Terraform state lives in a local backend committed to a **private** repository (not this one) or in Terraform Cloud free tier. The `.terraform.lock.hcl` is committed; `terraform.tfstate` is NOT committed to this repo.

```hcl
# deploy/terraform/providers.tf
terraform {
  required_version = ">= 1.9"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.48"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    acme = {
      source  = "vancluever/acme"
      version = "~> 2.0"
    }
  }
  # Remote state — replace with local {} for air-gapped
  backend "s3" {
    bucket = "analyselaptop-tfstate"
    key    = "hub/terraform.tfstate"
    region = "eu-central-1"
    # OR: use Terraform Cloud / HCP Terraform free tier
  }
}
```

```hcl
# deploy/terraform/modules/firewall/main.tf  (Hetzner example)
resource "hcloud_firewall" "hub" {
  name = "analyselaptop-hub"

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = var.operator_ips  # Never 0.0.0.0/0
  }
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]  # Management VPN in production
  }
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "4317"
    source_ips = var.collector_source_ips  # CIDR blocks containing collectors
  }
}
```

### Terraform workflow

```bash
terraform -chdir=deploy/terraform init
terraform -chdir=deploy/terraform plan -var-file=prod.tfvars
terraform -chdir=deploy/terraform apply -var-file=prod.tfvars
```

Terraform provisions the server and outputs its IP. The bootstrap script (`deploy/scripts/bootstrap-hub.sh`) is then run once over SSH to install Docker and create the required directories and file permissions.

---

## 4. Docker Compose — Hub Stack

### Base compose file

```yaml
# deploy/compose/docker-compose.yml
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
      VM_ENDPOINT:    http://victoriametrics:8428
      PG_HOST:        postgres
      PKI_DIR:        /run/secrets/pki
    volumes:
      - pki_data:/run/secrets/pki
    ports:
      - "0.0.0.0:4317:4317"   # OTLP/gRPC — mTLS-gated; collector-facing
    networks: [backend, collector_facing]
    depends_on:
      postgres:        { condition: service_healthy }
      victoriametrics: { condition: service_healthy }

  analyse:
    image: ghcr.io/xore/analyselaptop/analyse:${IMAGE_TAG:-latest}
    restart: unless-stopped
    secrets: [pg_user, pg_password, pg_db]
    environment:
      VM_ENDPOINT: http://victoriametrics:8428
      PG_HOST:     postgres
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

  nginx:
    image: nginx:1.27-alpine
    restart: unless-stopped
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
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
  backend:          # VM + PG + ingest + analyse + api — no external exposure
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
# deploy/compose/docker-compose.prod.yml
# Apply with: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
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
        limits: { memory: 512m }   # scikit-learn PCA can spike

  api:
    deploy:
      resources:
        limits: { memory: 128m }

  nginx:
    deploy:
      resources:
        limits: { memory: 64m }
```

### Secrets: file-based, never env vars

Docker Compose file-based secrets mount under `/run/secrets/` — they do not appear in `docker inspect`, in logs, or in crash dumps.

```bash
# deploy/scripts/bootstrap-hub.sh (excerpt)
mkdir -p /run/analyselaptop/secrets/pki
chmod 700 /run/analyselaptop/secrets

# Generate and write secrets (first run only — skip if files exist)
[ -f /run/analyselaptop/secrets/pg_password ] || \
  openssl rand -base64 32 > /run/analyselaptop/secrets/pg_password
[ -f /run/analyselaptop/secrets/jwt_secret ] || \
  openssl rand -base64 64 > /run/analyselaptop/secrets/jwt_secret

chmod 600 /run/analyselaptop/secrets/*
```

Secret files live in `/run/analyselaptop/secrets/` on the host — outside the repo, outside any Docker volume. They are provisioned once at bootstrap, rotated via `deploy/scripts/rotate-secrets.sh`.

---

## 5. Ansible — Collector Fleet

Collectors are **Go static binaries** (~22–26 MB, v2) managed by systemd. They do not run inside Docker (Docker on a Pi 3B adds ~30 MB RAM overhead for zero benefit; the binary is self-contained).

The v2 collector binary bundles all host-metric collection natively (`os_health_linux.go`, `os_health_windows.go`). **`node_exporter` is NOT deployed on collector nodes.** See [`COLLECTOR-FLEET-MONITORING.md`](COLLECTOR-FLEET-MONITORING.md) and [`../collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md) Section 6.1.

### Inventory

```yaml
# deploy/ansible/inventory/hosts.yml
all:
  children:
    collectors:
      hosts:
        probe-site-a:
          ansible_host: 192.168.1.50
          ansible_user: pi
          arch: arm64
          site: site-a
        probe-site-b:
          ansible_host: 10.20.1.5
          ansible_user: ubuntu
          arch: amd64
          site: site-b
        probe-ot-floor1:
          ansible_host: 10.10.0.20
          ansible_user: collector
          arch: arm64
          site: ot-floor1
          scan_level_max: 1   # OT node: active L1 only
```

### Collector role — key tasks

```yaml
# deploy/ansible/roles/collector/tasks/main.yml
- name: Create collector user (no login shell)
  user:
    name: collector
    system: true
    shell: /usr/sbin/nologin
    home: /var/lib/analyselaptop
    create_home: true

- name: Create state directory
  file:
    path: /var/lib/analyselaptop
    state: directory
    owner: collector
    group: collector
    mode: '0750'

- name: Deploy collector binary
  copy:
    src: "{{ playbook_dir }}/../../collector/dist/collector-linux-{{ arch }}"
    dest: /usr/local/bin/analyselaptop-collector
    owner: root
    group: root
    mode: '0755'
  notify: restart collector

- name: Deploy systemd unit
  template:
    src: collector.service.j2
    dest: /etc/systemd/system/analyselaptop-collector.service
    mode: '0644'
  notify:
    - daemon-reload
    - restart collector

- name: Set eBPF capabilities on binary
  capabilities:
    path: /usr/local/bin/analyselaptop-collector
    capability: "cap_bpf,cap_net_admin,cap_net_raw,cap_perfmon+eip"
    state: present
  when: ebpf_enabled | default(true)

- name: Enroll collector PKI cert (first run only)
  command: /usr/local/bin/analyselaptop-collector --enroll \
    --backend {{ backend_ingest_url }} \
    --id {{ inventory_hostname }}
  args:
    creates: /var/lib/analyselaptop/pki/collector.crt

# NOTE: No node_exporter tasks.
# The v2 collector binary emits host metrics (CPU, memory, disk, systemd unit
# state, interface counters) natively via os_health_linux.go / os_health_windows.go.
# Deploying node_exporter on collector nodes is not required.
# See: docs/collector/COLLECTOR-V2-REFACTOR.md Section 6.1
```

```ini
# deploy/ansible/roles/collector/templates/collector.service.j2
[Unit]
Description=analyseLaptop Collector Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=collector
Group=collector
ExecStart=/usr/local/bin/analyselaptop-collector \
  --backend-url {{ backend_ingest_url }} \
  --collector-id {{ inventory_hostname }} \
  --pki-dir /var/lib/analyselaptop/pki \
  --scan-level-max {{ scan_level_max | default(2) }} \
  --data-dir /var/lib/analyselaptop/data
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/analyselaptop
PrivateTmp=true
CapabilityBoundingSet=CAP_BPF CAP_NET_ADMIN CAP_NET_RAW CAP_PERFMON

[Install]
WantedBy=multi-user.target
```

### Playbooks

```bash
# Initial deploy to all collectors
ansible-playbook -i inventory/hosts.yml playbooks/deploy-collector.yml

# Rolling update (one at a time, health-check gated)
ansible-playbook -i inventory/hosts.yml playbooks/update-collector.yml \
  --serial 1 --extra-vars "image_tag=v2.0.0"

# Revoke a collector cert (e.g., decommissioned node)
ansible-playbook -i inventory/hosts.yml playbooks/revoke-collector.yml \
  --limit probe-site-a
```

---

## 6. GitHub Actions — CI/CD Pipelines

### Overview

```
PR opened
  └─▶ ci.yml          — lint, test, build (no push)

Merge to main
  └─▶ build-images.yml — build all backend images, push to GHCR
        └─▶ (on success) deploy-hub.yml — self-hosted runner on hub pulls + restarts

Release tag vX.Y.Z
  └─▶ build-images.yml — same, tagged
  └─▶ deploy-collector.yml — build collector binaries, update collector/dist/
        └─▶ (manual trigger) ansible-playbook update-collector.yml
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
      - uses: actions/setup-go@v5
        with: { go-version: '1.23' }
      - run: go test ./collector/... -race -count=1
      - run: go vet ./collector/...

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

  build-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '22' }
      - run: npm ci
        working-directory: frontend
      - run: npm run build
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
        service: [ingest, analyse, api]
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
          context: backend/${{ matrix.service }}
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to:   type=gha,mode=max
          platforms: linux/amd64,linux/arm64

  build-collector:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: '1.23' }
      - name: Cross-compile collector binaries (v2)
        run: |
          # Linux/amd64 and arm64: full build including eBPF-excluded files
          GOOS=linux  GOARCH=amd64 go build -o collector/dist/collector-linux-amd64  ./collector
          GOOS=linux  GOARCH=arm64 go build -o collector/dist/collector-linux-arm64  ./collector
          GOOS=windows GOARCH=amd64 go build -o collector/dist/collector-windows-amd64.exe ./collector
          # Note: eBPF files (ebpf/*.go) are build-tagged linux+cgo and excluded from Windows
      - uses: actions/upload-artifact@v4
        with:
          name: collector-binaries
          path: collector/dist/
          retention-days: 30
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
    runs-on: self-hosted   # Runner on the hub server itself
    environment: production
    concurrency:
      group: hub-deploy
      cancel-in-progress: false  # Never cancel a running deploy
    steps:
      - uses: actions/checkout@v4

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Pull new images
        run: |
          docker compose \
            -f deploy/compose/docker-compose.yml \
            -f deploy/compose/docker-compose.prod.yml \
            pull
        env:
          IMAGE_TAG: ${{ github.sha }}

      - name: Health-check pre-deploy
        run: curl -sf http://localhost:8428/health  # VictoriaMetrics

      - name: Rolling restart — ingest
        run: |
          docker compose \
            -f deploy/compose/docker-compose.yml \
            -f deploy/compose/docker-compose.prod.yml \
            up -d --no-deps ingest
        env:
          IMAGE_TAG: ${{ github.sha }}

      - name: Wait for ingest healthy
        run: |
          for i in $(seq 1 12); do
            docker inspect --format='{{.State.Health.Status}}' \
              $(docker compose ps -q ingest) | grep -q healthy && break
            echo "Waiting... $i"; sleep 5
          done

      - name: Rolling restart — analyse + api
        run: |
          docker compose \
            -f deploy/compose/docker-compose.yml \
            -f deploy/compose/docker-compose.prod.yml \
            up -d --no-deps analyse api
        env:
          IMAGE_TAG: ${{ github.sha }}

      - name: Health-check post-deploy
        run: curl -sf https://localhost/api/v1/health --insecure

      - name: Prune old images
        run: docker image prune -f --filter "until=48h"
```

### Self-hosted runner setup (one-time)

```bash
# On the hub server, alongside the stack
docker run -d \
  --name github-runner \
  --restart unless-stopped \
  -e RUNNER_REPOSITORY_URL=https://github.com/Xore/analyseLaptop \
  -e GITHUB_ACCESS_TOKEN=${RUNNER_TOKEN} \
  -e RUNNER_NAME=hub-runner \
  -e RUNNER_LABELS=self-hosted,hub \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /run/analyselaptop:/run/analyselaptop:ro \
  ghcr.io/actions/actions-runner:latest
```

The runner mounts the Docker socket (to run `docker compose` commands) and the secrets directory read-only. It does **not** have write access to secret files.

---

## 7. Collector Fleet Update Flow

```
GitHub Actions build-images.yml
  └─▶ Uploads collector binaries as artifact

Operator runs (manually or on schedule):
  ansible-playbook deploy/ansible/playbooks/update-collector.yml \
    --serial 5 \
    --extra-vars "collector_version=v2.0.0"

  For each collector (5 at a time):
    1. Download binary from GitHub Release or artifact
    2. Copy to /usr/local/bin/analyselaptop-collector (atomic mv)
    3. systemctl restart analyselaptop-collector
    4. Wait 10s
    5. systemctl is-active analyselaptop-collector  → abort on failure
    6. Check backend sees collector heartbeat within 60s (collector_heartbeat_total)
    7. Check collector_health_score > 0.8 in VictoriaMetrics
    8. Proceed to next batch
```

`--serial 5` means at most 5 of 50 collectors are offline simultaneously (10%).

---

## 8. Secrets Management Summary

| Secret | Where stored | How injected | Rotation |
|---|---|---|---|
| PostgreSQL password | `/run/analyselaptop/secrets/pg_password` on hub | Docker Compose `secrets:` → `/run/secrets/` | `rotate-secrets.sh` + `docker compose restart postgres api` |
| JWT signing key | `/run/analyselaptop/secrets/jwt_secret` | Docker Compose `secrets:` | `rotate-secrets.sh` + `docker compose restart api` |
| PKI CA key | `/run/analyselaptop/secrets/pki/ca.key` (mode 0600) | Bind-mounted into ingest at `/run/secrets/pki/` | Generate new CA + re-enroll all collectors |
| Collector leaf cert | `/var/lib/analyselaptop/pki/` on each collector | `--pki-dir` flag on collector binary | **Auto-renews when `days_remaining < 14`** (v2 `pki/renew.go`) |
| GitHub Runner token | GitHub repo secret `RUNNER_TOKEN` | `docker run -e` at runner start | Regenerate in GitHub settings |
| GHCR push token | `GITHUB_TOKEN` (automatic) | GitHub Actions env | Auto-rotated per workflow run |

**Rules:**
- No secrets in `.env` files that touch Git. `.env.example` with dummy values is committed; real `.env` is gitignored.
- No `environment:` blocks for secrets. All sensitive values via `secrets:` → `/run/secrets/` file reads.
- Secret files: `chmod 600`, owned by root. Applications read the file at startup.
- `gitleaks` scan runs on every PR (`ci.yml`).

---

## 9. Observability of the IaC Stack Itself

| What to monitor | How | Metric source |
|---|---|---|
| Docker service health | `docker compose ps` + `docker events` | Hub-local |
| VictoriaMetrics self-metrics | `/metrics` endpoint scraped by VM itself | `vm_app_uptime_seconds`, etc. |
| PostgreSQL | `pg_stat_activity` via Postgres exporter OR analyse service query | Hub service |
| **Collector fleet liveness** | `collector_heartbeat_total` stale >5 min → vmalert CollectorSilent | **v2 collector native** |
| **Collector host health** | `host_cpu_usage_pct`, `host_mem_available_bytes`, `host_disk_free_bytes` | **v2 collector native** (no node_exporter) |
| **Collector systemd unit state** | `host_systemd_unit_active{unit="analyselaptop-collector.service"}` | **v2 collector native** (no node_exporter) |
| **Collector health score** | `collector_health_score < 0.6` → vmalert CollectorHealthDegraded | **v2 collector native** |
| Certificate expiry | `collector_cert_days_left < 14` → vmalert CollectorCertExpiringSoon | **v2 collector native** |
| GitHub Actions run status | GitHub's native notifications + optional webhook to the alert system | GitHub |

> **node_exporter is not in this table.** All metrics previously sourced from `node_exporter` on collector nodes are now emitted by the v2 collector binary itself. See [`COLLECTOR-FLEET-MONITORING.md`](COLLECTOR-FLEET-MONITORING.md) for the full metric mapping.

---

## 10. Open IaC Questions

| # | Question | Decision point |
|---|---|---|
| Q1 | Terraform cloud provider: Hetzner vs DigitalOcean vs bare-metal NUC | Operator environment; Terraform abstracts this — change the provider block, not the modules |
| Q2 | Ansible inventory source: static YAML vs dynamic (PG `collectors` table) | Dynamic inventory script reading PG `collectors` table would auto-register new nodes — worth building at >20 collectors |
| Q3 | Collector update: GitHub Releases binary download vs Ansible `copy` from CI artifact | GitHub Releases preferred for auditability; artifact download requires GH_TOKEN on each collector |
| Q4 | Air-gapped deployments: replace GHCR pull with local registry mirror | Straightforward: change `image:` to point at local registry; Terraform can provision a local registry container |
| Q5 | v1 → v2 collector migration window | During migration (phases M1–M4), v1 nodes still need `node_exporter` for fleet monitoring. See `COLLECTOR-V2-REFACTOR.md` Section 12 for the migration plan. Remove `node_exporter` Ansible tasks after phase M5. |
