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

# Bind address: loopback by default; PROBE_EXPOSE=lan binds the current IPv4
# address of the default-route (LAN) interface. LAN exposure requires the
# generated access token (HTTP Basic auth, any username).
bind_address=127.0.0.1
if [[ ${PROBE_EXPOSE:-} == lan ]]; then
  lan_iface=$(ip route show default | awk '{print $5; exit}')
  bind_address=$(ip -4 -brief address show dev "$lan_iface" | awk '{print $3}' | cut -d/ -f1)
  [[ -n $bind_address ]] || { echo "Could not determine the LAN address on ${lan_iface:-?}." >&2; exit 2; }
  token_file=$config_dir/dashboard-token
  if [[ ! -s $token_file ]]; then
    umask 077
    openssl rand -hex 16 > "$token_file"
    umask 022
    chown root:"$service_user" "$token_file"
    chmod 640 "$token_file"
    echo "Generated dashboard access token in $token_file"
  fi
fi

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
Environment=PROBE_BIND=$bind_address
Environment=PROBE_PORT=8088
Environment=PROBE_AUTH_TOKEN_FILE=$config_dir/dashboard-token
Environment=PROBE_CAPTURE_DIR=$state_dir/captures
Environment=PROBE_SNAPSHOT_DIR=$state_dir/snapshots
Environment=PROBE_TARGET_FILE=$config_dir/targets.csv
ExecStart=$venv_dir/bin/waitress-serve --listen=$bind_address:8088 dashboard.app:app
Restart=on-failure
RestartSec=3
# NoNewPrivileges must stay off: capture jobs spawn dumpcap, which gains
# CAP_NET_RAW/CAP_NET_ADMIN through file capabilities (wireshark group).
NoNewPrivileges=false
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
systemctl enable network-probe-dashboard.service
systemctl restart network-probe-dashboard.service
sleep 2
systemctl --no-pager --full status network-probe-dashboard.service || true
echo "Dashboard installed at http://$bind_address:8088"
if [[ $bind_address != 127.0.0.1 ]]; then
  echo "LAN exposure is active: sign in with any username and the token from $config_dir/dashboard-token."
  echo "Note: HTTP only - use it on trusted management networks; do not port-forward to the internet."
fi
echo "Edit approved targets in $config_dir/targets.csv, then restart the service."
