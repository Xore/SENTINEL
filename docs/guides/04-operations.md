# Operations runbook — v2 Collector

Day-to-day tasks for running the v2 collector in production.

---

## Service management

```bash
# Status
systemctl status analyselaptop-collector

# Live logs (structured JSON)
journalctl -u analyselaptop-collector -f

# Restart (e.g. after config change)
systemctl restart analyselaptop-collector

# Reload config without restart (SIGHUP hot-reload)
systemctl kill -s HUP analyselaptop-collector

# Stop / disable
systemctl stop analyselaptop-collector
systemctl disable analyselaptop-collector
```

---

## Config changes

1. Edit `/etc/analyselaptop/collector.yaml`.
2. Validate the YAML is syntactically correct:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('/etc/analyselaptop/collector.yaml'))"
   ```
3. Hot-reload (preferred — no downtime):
   ```bash
   systemctl kill -s HUP analyselaptop-collector
   ```
4. If the change affects the transport or PKI config, a full restart is safer:
   ```bash
   systemctl restart analyselaptop-collector
   ```

---

## PKI certificate management

The collector auto-renews its mTLS certificate when fewer than 14 days remain.
To check the current cert expiry:

```bash
openssl x509 -in /var/lib/analyselaptop/pki/collector.crt -noout -enddate
```

To force a manual re-enrolment (e.g. after a hub PKI rotation):

```bash
systemctl stop analyselaptop-collector
rm /var/lib/analyselaptop/pki/collector.{key,crt}
./analyselaptop-collector enroll \
  --hub https://<hub-ip>:4317 \
  --enroll-token <new-token>
systemctl start analyselaptop-collector
```

---

## Binary updates

```bash
# Download new binary
curl -L -o /tmp/analyselaptop-collector-new \
  https://github.com/Xore/analyseLaptop/releases/latest/download/analyselaptop-collector-linux-amd64
chmod +x /tmp/analyselaptop-collector-new

# Verify it starts cleanly
/tmp/analyselaptop-collector-new --version

# Swap binary and restart
systemctl stop analyselaptop-collector
cp /tmp/analyselaptop-collector-new /usr/local/bin/analyselaptop-collector
# Re-grant capabilities after binary swap
sudo setcap cap_net_raw+ep /usr/local/bin/analyselaptop-collector
systemctl start analyselaptop-collector
systemctl status analyselaptop-collector
```

> **Note:** `setcap` must be re-run after every binary swap because the capability
> is stored on the inode, not in the config.

---

## Checking collector health

### From the hub API

```bash
# List all registered collectors and their health scores
curl -s http://<hub-ip>:8080/api/collectors | jq '.[]'

# Check a specific collector
curl -s http://<hub-ip>:8080/api/collectors | \
  jq '.[] | select(.id=="pi-bedroom")'
```

### From the collector node itself

```bash
# Recent log lines (look for ERROR or WARNING level)
journalctl -u analyselaptop-collector --since "1 hour ago" | grep -E 'ERROR|WARNING'

# Local store disk usage
du -sh /var/lib/analyselaptop/data/

# Cert expiry
openssl x509 -in /var/lib/analyselaptop/pki/collector.crt -noout -enddate
```

### Key log fields to watch

| Field | Value to investigate |
|---|---|
| `level` | `error` or `warning` |
| `event` | `cycle_overrun` — check cycle took longer than `scan_level_max` allows |
| `event` | `backend_unreachable` — collector buffering locally; check hub and network |
| `event` | `cert_expiry_soon` — auto-renew triggered; watch for `cert_renewed` |
| `event` | `ebpf_unavailable` — `bcc` import failed; eBPF checks skipped |
| `event` | `cap_net_raw_missing` — ICMP/MTR/bcast checks skipped; re-grant `setcap` |

---

## Local buffer management

The collector stores up to 24 h of metrics locally when the hub is unreachable
(`lmdb` hot buffer + `sqlite3` cold store in `data_dir`).

```bash
# Check hot buffer size (lmdb)
du -sh /var/lib/analyselaptop/data/hot.lmdb/

# Check cold store size (sqlite3)
du -sh /var/lib/analyselaptop/data/cold.db

# If the hub has been unreachable for >24 h, the oldest samples are discarded.
# No manual action needed — the ring buffer self-manages.
```

If disk space is critically low:
```bash
systemctl stop analyselaptop-collector
rm -rf /var/lib/analyselaptop/data/hot.lmdb
rm -f /var/lib/analyselaptop/data/cold.db
systemctl start analyselaptop-collector
# Note: all buffered history is lost; hub will see a gap
```

---

## Adding or removing check targets

1. Edit `collector.yaml` — add/remove entries under the relevant check section
   (e.g. `mtr.targets`, `snmp.targets`, `tcp.targets`).
2. Hot-reload: `systemctl kill -s HUP analyselaptop-collector`.
3. Verify the new target appears in hub metrics within one cycle (~30 s).

---

## Disabling a check type temporarily

```yaml
# In collector.yaml — disable bcast/mcast capture
bcast_mcast:
  enabled: false

# Disable eBPF flow tracking
ebpf:
  enabled: false
```

Hot-reload after any change: `systemctl kill -s HUP analyselaptop-collector`.

---

## Routine maintenance checklist

| Frequency | Task |
|---|---|
| Daily | Check `collector_health_score` on hub — should be >0.8 |
| Daily | Check `collector_cert_days_left` — alert if <14 |
| Weekly | Review `ERROR`/`WARNING` log lines |
| Weekly | Check local buffer disk usage |
| Monthly | Verify binary version matches latest release |
| Monthly | Review `collector.yaml` — remove stale targets, confirm scan levels |
| On binary update | Re-run `setcap` after binary swap |
| On PKI rotation | Force re-enrolment as above |
