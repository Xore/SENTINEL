# Collector Fleet Monitoring

> **Context:** This document covers monitoring the health of 50+ remote `analyselaptop-collector` systemd services — not the network targets they probe.  
> **v2 extended architecture:** [`ARCHITECTURE-V2-EXTENDED.md`](ARCHITECTURE-V2-EXTENDED.md) — Section 10.2 (Collector Health Scoring) and Section 8 (Alerting: vmalert rules) extend the patterns described here.

---

## 1. Three Layers of Fleet Health

Every collector node has three independent failure modes. Each layer catches a different class of fault:

```
Layer 1 — Heartbeat (application-level)
  └─ Is the collector binary actually running and sending data?
  └─ Detected by: missing OTLP push → no `last_seen` update in PostgreSQL

Layer 2 — systemd unit state (OS-level)
  └─ Is the systemd service active/inactive/failed?
  └─ Is it crash-looping (restart count rising)?
  └─ Detected by: node_exporter --collector.systemd scrape → VictoriaMetrics

Layer 3 — Host vitals (hardware/OS-level)
  └─ Is the node reachable at all? CPU/memory/disk/network?
  └─ Detected by: node_exporter full scrape → VictoriaMetrics
```

Layer 1 is already built into the v2 architecture (ingest service writes `last_seen` to PostgreSQL on every OTLP push).  
Layers 2 and 3 require deploying `node_exporter` on each collector node.

---

## 2. Layer 1: Heartbeat via `last_seen`

### How it works

The ingest service updates `collectors.last_seen = now()` on every OTLP batch received from a collector. The API service and the analysis service can both query this column.

```sql
-- Stale collectors: no push for >5 minutes
SELECT id, name, site, last_seen,
       now() - last_seen AS silence_duration
FROM   collectors
WHERE  state = 'active'
  AND  last_seen < now() - INTERVAL '5 minutes'
ORDER  BY silence_duration DESC;
```

### PostgreSQL NOTIFY on staleness

A lightweight background goroutine in the API service polls this query every 60 s and pushes a `collector_stale` event via WebSocket to the frontend fleet table. The analysis service also checks it before deciding whether to include a collector in PCA input (stale collectors are excluded from the multi-metric anomaly matrix).

### Heartbeat alert rule (VictoriaMetrics MetricsQL)

The collector pushes a `collector_heartbeat_total` counter with each OTLP batch. This allows a PromQL-style alert that does not depend on PostgreSQL:

```promql
# Alert: collector has not pushed in 5 minutes
abs(time() - max by (collector_id) (
  timestamp(last_over_time(collector_heartbeat_total[6m]))
)) > 300
```

Store this as a VictoriaMetrics `vmalert` rule (see `ARCHITECTURE-V2-EXTENDED.md` Section 8.1 for the full vmalert + Alertmanager integration).

---

## 3. Layer 2: systemd Unit State via `node_exporter`

### Deploy `node_exporter` via Ansible

`node_exporter` is a static binary like the collector — deploy it the same way, under the same Ansible role structure.

```yaml
# deploy/ansible/roles/collector/tasks/node_exporter.yml
- name: Deploy node_exporter binary
  copy:
    src: "node_exporter-linux-{{ arch }}"
    dest: /usr/local/bin/node_exporter
    owner: root
    group: root
    mode: '0755'
  notify: restart node_exporter

- name: Deploy node_exporter systemd unit
  template:
    src: node_exporter.service.j2
    dest: /etc/systemd/system/node_exporter.service
    mode: '0644'
  notify:
    - daemon-reload
    - restart node_exporter

- name: Enable node_exporter
  systemd:
    name: node_exporter
    enabled: true
    state: started
```

```ini
# deploy/ansible/roles/collector/templates/node_exporter.service.j2
[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
Type=simple
User=nobody
Group=nogroup
ExecStart=/usr/local/bin/node_exporter \
  --collector.systemd \
  --collector.systemd.unit-include="analyselaptop-collector\.service" \
  --collector.systemd.enable-restarts-metrics \
  --collector.systemd.enable-start-time-metrics \
  --collector.netdev \
  --collector.meminfo \
  --collector.cpu \
  --collector.diskstats \
  --collector.filesystem \
  --collector.loadavg \
  --web.listen-address=127.0.0.1:9100 \
  --web.disable-exporter-metrics
Restart=always
RestartSec=10
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

**Key flags:**
- `--collector.systemd.unit-include` — only export metrics for `analyselaptop-collector.service`; avoids DBus overhead for every unit on the node.
- `--collector.systemd.enable-restarts-metrics` — exposes `node_systemd_service_restart_total` for crash-loop detection.
- `--web.listen-address=127.0.0.1:9100` — node_exporter listens on loopback only. The collector binary reads it locally and includes host metrics in its OTLP push.

### Key `node_exporter` metrics for the collector unit

| Metric | Meaning |
|---|---|
| `node_systemd_unit_state{name="analyselaptop-collector.service", state="active"} == 1` | Service is running |
| `node_systemd_unit_state{name="analyselaptop-collector.service", state="failed"} == 1` | Service has failed |
| `node_systemd_service_restart_total` | Cumulative restart count |
| `node_systemd_service_start_time_seconds` | Last start time (unix epoch) |
| `node_load1` | 1-minute load average (host overloaded?) |
| `node_memory_MemAvailable_bytes` | Free memory |
| `node_filesystem_avail_bytes` | Disk available (local hot/cold store) |
| `node_network_transmit_bytes_total{device="eth0"}` | Outbound traffic (collector is sending?) |

### Scrape topology: push not pull

Collector nodes are edge devices — they may be behind NAT, OT firewalls, or isolated VLANs. The hub **cannot** scrape them outbound.

**Solution: collector binary pushes node_exporter metrics as part of its OTLP batch.**

The collector binary reads the `node_exporter` `/metrics` endpoint on `127.0.0.1:9100` at each push interval, wraps the host metrics into the OTLP batch alongside probe metrics, and ships them to the hub ingest service. This means:

- Zero new open ports on the collector node.
- No firewall rule changes beyond the existing `4317/tcp` outbound.
- The ingest service receives both probe metrics and host metrics in the same authenticated, mTLS-protected channel.
- VictoriaMetrics stores them all under the same `collector_id` label.

Alternatively, for nodes where embedding is not yet implemented: deploy `Prometheus Pushgateway` on the hub on `127.0.0.1:9091` and have each collector node run a cron/systemd timer that does:

```bash
curl -s http://localhost:9100/metrics | \
  curl --data-binary @- \
  --header 'Content-Type: text/plain; version=0.0.4' \
  "https://hub:9091/metrics/job/node_exporter/instance/${HOSTNAME}"
```

This is a short-term bridge until the collector binary embeds the node_exporter read.

---

## 4. Layer 3: Host Vitals

The same `node_exporter` scrape that delivers systemd metrics also delivers CPU, memory, disk, and network counters. All are stored in VictoriaMetrics under `{collector_id=..., job="node_exporter"}` labels.

---

## 5. Alert Rules

All rules are stored as VictoriaMetrics `vmalert` YAML files. Deploy at `deploy/compose/vmalert/rules/collector-fleet.yml`.

For the full vmalert + Alertmanager integration (deduplication, grouping, PagerDuty/Slack routing), see [`ARCHITECTURE-V2-EXTENDED.md`](ARCHITECTURE-V2-EXTENDED.md) Section 8.

```yaml
# deploy/compose/vmalert/rules/collector-fleet.yml
groups:
  - name: collector_fleet
    interval: 60s
    rules:

      # --- Heartbeat ---
      - alert: CollectorSilent
        expr: |
          (time() - max by (collector_id) (
            timestamp(last_over_time(collector_heartbeat_total[6m]))
          )) > 300
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Collector {{ $labels.collector_id }} has not pushed for >5 min"
          runbook: "Check systemd status; check network path to hub:4317"

      # --- systemd unit state ---
      - alert: CollectorServiceFailed
        expr: |
          node_systemd_unit_state{
            name="analyselaptop-collector.service",
            state="failed"
          } == 1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "analyselaptop-collector.service FAILED on {{ $labels.instance }}"
          runbook: "Run: journalctl -u analyselaptop-collector -n 50"

      - alert: CollectorServiceNotActive
        expr: |
          node_systemd_unit_state{
            name="analyselaptop-collector.service",
            state="active"
          } == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "analyselaptop-collector.service not active on {{ $labels.instance }}"

      # --- Crash-loop detection ---
      - alert: CollectorCrashLooping
        expr: |
          increase(
            node_systemd_service_restart_total{
              name="analyselaptop-collector.service"
            }[30m]
          ) > 3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Collector {{ $labels.instance }} restarted >3 times in 30 min"
          runbook: "Run: journalctl -u analyselaptop-collector -n 100"

      # --- Host vitals ---
      - alert: CollectorNodeHighLoad
        expr: node_load1{job="node_exporter"} > 4
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High CPU load on collector node {{ $labels.instance }}"

      - alert: CollectorNodeLowMemory
        expr: |
          node_memory_MemAvailable_bytes{job="node_exporter"} /
          node_memory_MemTotal_bytes{job="node_exporter"} < 0.10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Collector node {{ $labels.instance }} has <10% free RAM"

      - alert: CollectorNodeDiskFull
        expr: |
          node_filesystem_avail_bytes{
            job="node_exporter",
            mountpoint="/var/lib/analyselaptop"
          } < 100 * 1024 * 1024
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Collector local store on {{ $labels.instance }} has <100 MB free"

      # --- PKI cert expiry ---
      - alert: CollectorCertExpiringSoon
        expr: |
          (analyselaptop_collector_cert_expiry_seconds - time()) < 14 * 86400
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Collector {{ $labels.collector_id }} cert expires in <14 days"
          runbook: "The collector should auto-renew; check PKI enrollment endpoint"

      # --- Collector health score (v2 extended) ---
      - alert: CollectorHealthDegraded
        expr: analyselaptop_collector_health_score < 0.6
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Collector {{ $labels.collector_id }} health score {{ $value | humanize }} < 0.6"
          runbook: "Check heartbeat gap, cycle overrun, metric gaps, cert expiry, eBPF state"
```

---

## 6. Ansible Ad-hoc Fleet Health Checks

For immediate operational checks (not automated alerting), Ansible ad-hoc commands are the fastest path:

```bash
# Is the collector service active on all nodes?
ansible collectors -i deploy/ansible/inventory/hosts.yml \
  -m systemd -a "name=analyselaptop-collector" \
  --one-line | grep -v 'ActiveState.*active'

# Last 20 log lines from failed nodes
ansible collectors -i deploy/ansible/inventory/hosts.yml \
  -m command -a "journalctl -u analyselaptop-collector -n 20 --no-pager"

# Disk space on local hot/cold store path
ansible collectors -i deploy/ansible/inventory/hosts.yml \
  -m command -a "df -h /var/lib/analyselaptop" --one-line

# PKI cert expiry on all nodes
ansible collectors -i deploy/ansible/inventory/hosts.yml \
  -m command -a \
  "openssl x509 -enddate -noout -in /var/lib/analyselaptop/pki/collector.crt" \
  --one-line

# Force restart a single node
ansible probe-site-a -i deploy/ansible/inventory/hosts.yml \
  -m systemd -a "name=analyselaptop-collector state=restarted" --become
```

---

## 7. Frontend: Fleet Status Table

The API service (`GET /api/v1/collectors`) returns per-collector health fields that the SvelteKit fleet table consumes:

```json
{
  "id": "probe-site-a",
  "site": "site-a",
  "state": "active",
  "last_seen": "2026-07-25T17:32:10Z",
  "silence_s": 0,
  "cert_expires_in_days": 28,
  "health_score": 0.94,
  "host": {
    "load1": 0.34,
    "mem_free_pct": 72,
    "disk_free_mb": 4200,
    "systemd_state": "active",
    "restart_count_30m": 0
  },
  "alerts": []
}
```

Row colour coding in the fleet table:

| Condition | Colour |
|---|---|
| `state=active`, `health_score >= 0.8`, no alerts | Green |
| `health_score 0.6–0.8` OR `restart_count_30m > 0` | Yellow |
| `systemd_state=failed` OR `health_score < 0.6` OR `silence_s > 1800` | Red |
| `cert_expires_in_days < 14` | Orange badge |

---

## 8. What Gets Deployed Per Collector Node

| Component | Binary | Managed by | Port exposed |
|---|---|---|---|
| `analyselaptop-collector` | Go static binary | Ansible + systemd | None (outbound `4317` only) |
| `node_exporter` | Static binary | Ansible + systemd | `127.0.0.1:9100` (loopback only) |
| Metrics push | Collector reads `9100` locally, includes in OTLP batch | Part of collector binary | None |

No additional inbound firewall rules beyond the existing outbound `4317/tcp` to the hub.
