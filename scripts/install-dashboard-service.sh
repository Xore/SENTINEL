#!/usr/bin/env bash
set -euo pipefail

if [[ ${1:-} != --apply ]]; then
  echo "This creates a service account, installs packages and enables the local dashboard."
  echo "Review this script, then run: sudo $0 --apply" >&2
  exit 2
fi
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run with sudo." >&2; exit 2; }
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || { echo "Supported target is Ubuntu 24.04 LTS; found ${PRETTY_NAME:-unknown}." >&2; exit 2; }

repo_dir=$(readlink -f "$(dirname "$0")/..")
service_user=probe-dashboard
state_dir=/var/lib/network-probe
config_dir=/etc/network-probe
venv_dir=/opt/network-probe-venv

export DEBIAN_FRONTEND=noninteractive
echo 'wireshark-common wireshark-common/install-setuid boolean true' | debconf-set-selections
apt-get update
apt-get install -y python3-venv python3-pip tshark wireshark nmap ethtool iw jq curl git dnsutils snmp traceroute chrony
getent group wireshark >/dev/null || groupadd --system wireshark
id "$service_user" >/dev/null 2>&1 || useradd --system --home-dir "$state_dir" --create-home --shell /usr/sbin/nologin "$service_user"
usermod -aG wireshark "$service_user"
install -d -o "$service_user" -g "$service_user" -m 0750 "$state_dir" "$state_dir/captures" "$state_dir/snapshots"
install -d -o root -g "$service_user" -m 0750 "$config_dir"
if [[ ! -e $config_dir/targets.csv ]]; then install -o root -g "$service_user" -m 0640 "$repo_dir/config/targets.example.csv" "$config_dir/targets.csv"; fi

python3 -m venv "$venv_dir"
"$venv_dir/bin/pip" install --upgrade pip
"$venv_dir/bin/pip" install -r "$repo_dir/dashboard/requirements.txt"
find "$repo_dir/scripts" -maxdepth 1 -type f -name '*.sh' -exec chmod 0755 {} +

unit_tmp=$(mktemp)
trap 'rm -f -- "$unit_tmp"' EXIT
cat > "$unit_tmp" <<EOF
[Unit]
Description=Fieldline Network Probe Dashboard
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=$service_user
Group=$service_user
SupplementaryGroups=wireshark
WorkingDirectory=$repo_dir
Environment=PROBE_BIND=127.0.0.1
Environment=PROBE_PORT=8088
Environment=PROBE_CAPTURE_DIR=$state_dir/captures
Environment=PROBE_SNAPSHOT_DIR=$state_dir/snapshots
Environment=PROBE_TARGET_FILE=$config_dir/targets.csv
ExecStart=$venv_dir/bin/waitress-serve --listen=127.0.0.1:8088 dashboard.app:app
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$repo_dir $config_dir
ReadWritePaths=$state_dir
[Install]
WantedBy=multi-user.target
EOF
install -o root -g root -m 0644 "$unit_tmp" /etc/systemd/system/network-probe-dashboard.service
systemctl daemon-reload
systemctl enable --now network-probe-dashboard.service
sleep 2
systemctl --no-pager --full status network-probe-dashboard.service || true
echo "Dashboard installed at http://127.0.0.1:8088 (use an SSH tunnel or approved VPN)."
echo "Edit approved targets in $config_dir/targets.csv, then restart the service."
