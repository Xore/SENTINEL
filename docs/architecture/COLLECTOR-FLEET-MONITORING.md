# Collector Fleet Monitoring

> **Context:** This document covers monitoring the health of 50+ remote `analyselaptop-collector` systemd services — not the network targets they probe.  
> **v2 collector design:** [`../collector/COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md) — the v2 binary bundles all host-metric collection natively; `node_exporter` is no longer required on collector nodes.  
> **v2 extended architecture:** [`ARCHITECTURE-V2-EXTENDED.md`](ARCHITECTURE-V2-EXTENDED.md) — Section 10.2 (Collector Health Scoring) and Section 8 (Alerting: vmalert rules) extend the patterns described here.

---

## 1. Three Layers of Fleet Health

Every collector node has three independent failure modes. Each layer catches a different class of fault:

```
Layer 1 — Heartbeat (application-level)
  └─ Is the collector binary actually running and sending data?
  └─ Detected by: missing OTLP push → no `last_seen` update in PostgreSQL
     AND: collector_heartbeat_total counter stale in VictoriaMetrics

Layer 2 — systemd unit state (OS-level)
  └─ Is the systemd service active/inactive/failed?
  └─ Is it crash-looping (restart count rising)?
  └─ Detected by: v2 collector bundles host_systemd_unit_active + host_systemd_restart_total
     natively via os_health/linux.py — no node_exporter required

Layer 3 — Host vitals (hardware/OS-level)
  └─ Is the node reachable at all? CPU/memory/disk/network?
  └─ Detected by: v2 collector bundles host_cpu_usage_pct, host_mem_available_bytes,
     host_disk_free_bytes, host_net_rx/tx_bytes_total natively — no node_exporter required
```

All three layers are covered by the **v2 collector binary alone**. The v2 collector reads `/proc/stat`, `/proc/meminfo`, `/proc/net/dev`, `syscall.Statfs`, and `systemctl show` directly and emits them as OTLP metrics alongside probe results. On Windows it uses `Get-CimInstance Win32_OperatingSystem`.

> **node_exporter is optional in v2.** It may still be deployed on nodes that need to feed a separate Prometheus/Grafana stack, but it is not required for the analyselaptop fleet monitoring pipeline. See [Section 9](#9-optional-node_exporter-fallback) for the fallback pattern.

Layer 1 is already built into the v2 architecture (ingest service writes `last_seen` to PostgreSQL on every OTLP push).  
Layers 2 and 3 are served by the v2 collector's native OS health collection — `os_health/linux.py` / `os_health/windows.py` (see [`COLLECTOR-V2-REFACTOR.md`](../collector/COLLECTOR-V2-REFACTOR.md) Section 6.1).

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

## 3. Layer 2: systemd Unit State — Native v2 Collector Metrics

In v2, the collector emits systemd unit health as OTLP gauges. No `node_exporter` or DBus scrape is needed on the hub side:

| OTLP Metric | Labels | Meaning |
|---|---|---|
| `host_systemd_unit_active` | `collector_id, site_id, unit` | 1 = active, 0 = not active |
| `host_systemd_restart_count_30m` | `collector_id, site_id, unit` | Restarts in last 30 min window |
| `host_systemd_start_time_s` | `collector_id, site_id, unit` | Last start time (Unix epoch) |

These are emitted from `os_health/processes.py` on Linux (via `systemctl show -p ActiveState,NRestarts,ActiveEnterTimestamp analyselaptop-collector.service`).

### Mapping from `node_exporter` metrics

| Old (`node_exporter`) | New (v2 collector) |
|---|---|
| `node_systemd_unit_state{state="active"}` | `host_systemd_unit_active{unit="analyselaptop-collector.service"}` |
| `node_systemd_unit_state{state="failed"}` | `host_systemd_unit_active == 0` (check `host_systemd_unit_failed` label) |
| `node_systemd_service_restart_total` | `host_systemd_restart_count_30m` |
| `node_systemd_service_start_time_seconds` | `host_systemd_start_time_s` |

---

## 4. Layer 3: Host Vitals — Native v2 Collector Metrics

The v2 collector emits all host vitals from its own `os_health/linux.py` / `os_health/windows.py`. No sidecar needed:

| OTLP Metric | Labels | Source |
|---|---|---|
| `host_cpu_usage_pct` | `collector_id, site_id` | `/proc/stat` |
| `host_load1` / `host_load5` / `host_load15` | `collector_id, site_id` | `/proc/loadavg` |
| `host_mem_available_bytes` | `collector_id, site_id` | `/proc/meminfo` |
| `host_mem_total_bytes` | `collector_id, site_id` | `/proc/meminfo` |
| `host_disk_free_bytes` | `collector_id, site_id, mountpoint` | `syscall.Statfs` |
| `host_uptime_s` | `collector_id, site_id` | `/proc/uptime` |
| `host_net_rx_bytes_total` | `collector_id, site_id, interface` | `/proc/net/dev` |
| `host_net_tx_bytes_total` | `collector_id, site_id, interface` | `/proc/net/dev` |
| `host_net_rx_errors_total` | `collector_id, site_id, interface` | `/proc/net/dev` |
| `collector_health_score` | `collector_id, site_id` | `health/score.py` (self-computed) |
| `collector_cert_days_left` | `collector_id, site_id` | `pki/renew.py` |
| `collector_cycle_duration_ms` | `collector_id, site_id` | `__main__.py` loop timer |

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

      # --- systemd unit state (v2 native metric) ---
      - alert: CollectorServiceFailed
        expr: |
          host_systemd_unit_active{
            unit="analyselaptop-collector.service"
          } == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "analyselaptop-collector.service not active on {{ $labels.collector_id }}"
          runbook: "Run: journalctl -u analyselaptop-collector -n 50"

      # --- Crash-loop detection (v2 native metric) ---
      - alert: CollectorCrashLooping
        expr: host_systemd_restart_count_30m{unit="analyselaptop-collector.service"} > 3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Collector {{ $labels.collector_id }} restarted >3 times in 30 min"
          runbook: "Run: journalctl -u analyselaptop-collector -n 100"

      # --- Host vitals (v2 native metrics) ---
      - alert: CollectorNodeHighLoad
        expr: host_load1 > 4
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High CPU load on collector {{ $labels.collector_id }}"

      - alert: CollectorNodeLowMemory
        expr: |
          host_mem_available_bytes / host_mem_total_bytes < 0.10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Collector {{ $labels.collector_id }} has <10% free RAM"

      - alert: CollectorNodeDiskFull
        expr: |
          host_disk_free_bytes{mountpoint="/var/lib/analyselaptop"} < 100 * 1024 * 1024
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Collector local store on {{ $labels.collector_id }} has <100 MB free"

      # --- PKI cert expiry ---
      - alert: CollectorCertExpiringSoon
        expr: collector_cert_days_left < 14
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Collector {{ $labels.collector_id }} cert expires in <14 days"
          runbook: "The collector should auto-renew; check PKI enrollment endpoint"

      # --- Collector health score ---
      - alert: CollectorHealthDegraded
        expr: collector_health_score < 0.6
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
| `analyselaptop-collector` v2 | Python PyInstaller bundle (~22–26 MB) | Ansible + systemd | None (outbound `4317` only) |

> **node_exporter is not part of the collector node deployment.** The v2 collector binary bundles all host metrics natively.

No additional inbound firewall rules beyond the existing outbound `4317/tcp` to the hub. No additional binaries. No additional systemd units.

---

## 9. Optional: node_exporter

`node_exporter` may still be useful if you run a separate Prometheus/Grafana stack alongside analyselaptop and want a unified host-metrics feed into that stack. It is not part of the standard analyselaptop collector role.
