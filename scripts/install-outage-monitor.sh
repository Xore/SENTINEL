#!/usr/bin/env bash
# Installs the continuous outage monitor as a systemd service.
# Requires install-dashboard-service.sh to have run first (service user,
# venv and state directory are shared with the dashboard).
set -euo pipefail

if [[ ${1:-} != --apply ]]; then
  echo "Installs the outage-monitor systemd service (shared user/venv with the dashboard)."
  echo "Review this script, then run: sudo $0 --apply" >&2
  exit 2
fi
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run with sudo." >&2; exit 2; }

repo_dir=$(readlink -f "$(dirname "$0")/..")
service_user=probe-dashboard
state_dir=/var/lib/network-probe
config_dir=/etc/network-probe
venv_dir=/opt/network-probe-venv

id "$service_user" >/dev/null 2>&1 || { echo "Run install-dashboard-service.sh first." >&2; exit 2; }
[[ -x $venv_dir/bin/python ]] || { echo "Missing $venv_dir; run install-dashboard-service.sh first." >&2; exit 2; }

install -d -o "$service_user" -g "$service_user" -m 0750 "$state_dir"
if [[ ! -e $config_dir/monitor-targets.csv ]]; then
  install -o root -g "$service_user" -m 0640 "$repo_dir/config/monitor-targets.example.csv" "$config_dir/monitor-targets.csv"
  echo "Seeded $config_dir/monitor-targets.csv - EDIT IT with the real gateway/server addresses."
fi

# Snapshot interface: first wired interface that is up, unless overridden.
snapshot_iface=${PROBE_MONITOR_SNAPSHOT_IFACE:-$(ip -brief link | awk '$1 !~ /^(lo|wl)/ && $2 == "UP" {print $1; exit}')}

unit_tmp=$(mktemp)
trap 'rm -f -- "$unit_tmp"' EXIT
cat > "$unit_tmp" <<EOF
[Unit]
Description=Fieldline Network Probe Outage Monitor
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=$service_user
Group=$service_user
SupplementaryGroups=wireshark
WorkingDirectory=$repo_dir
Environment=PROBE_MONITOR_DB=$state_dir/monitor.db
Environment=PROBE_MONITOR_TARGETS=$config_dir/monitor-targets.csv
Environment=PROBE_MONITOR_SNAPSHOT_IFACE=${snapshot_iface:-}
ExecStart=$venv_dir/bin/python $repo_dir/monitor/outage_monitor.py
Restart=on-failure
RestartSec=5
# NoNewPrivileges must stay off: the outage snapshot spawns dumpcap, which
# gains CAP_NET_RAW/CAP_NET_ADMIN through file capabilities (wireshark group).
NoNewPrivileges=false
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$repo_dir $config_dir
ReadWritePaths=$state_dir
[Install]
WantedBy=multi-user.target
EOF
install -o root -g root -m 0644 "$unit_tmp" /etc/systemd/system/network-probe-monitor.service

# Unprivileged ICMP for the service user (ping uses SOCK_DGRAM ICMP).
sysctl_file=/etc/sysctl.d/99-probe-ping.conf
echo 'net.ipv4.ping_group_range = 0 2147483647' > "$sysctl_file"
sysctl -p "$sysctl_file" >/dev/null

systemctl daemon-reload
systemctl enable --now network-probe-monitor.service
sleep 2
systemctl --no-pager --full status network-probe-monitor.service || true
echo "Outage monitor installed. Data: $state_dir/monitor.db - plots at http://127.0.0.1:8088/monitor"
