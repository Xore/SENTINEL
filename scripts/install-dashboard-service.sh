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
apt-get install -y python3-venv python3-pip tshark wireshark nmap ethtool iw jq curl git dnsutils snmp traceroute mtr-tiny chrony
getent group wireshark >/dev/null || groupadd --system wireshark
id "$service_user" >/dev/null 2>&1 || useradd --system --home-dir "$state_dir" --create-home --shell /usr/sbin/nologin "$service_user"
usermod -aG wireshark "$service_user"
install -d -o "$service_user" -g "$service_user" -m 0750 "$state_dir" "$state_dir/captures" "$state_dir/snapshots"
install -d -o root -g "$service_user" -m 0750 "$config_dir"
if [[ ! -e $config_dir/targets.csv ]]; then install -o root -g "$service_user" -m 0640 "$repo_dir/config/targets.example.csv" "$config_dir/targets.csv"; fi

# Bind address: loopback by default; PROBE_EXPOSE=lan binds the current IPv4
# address of the default-route (LAN) interface. Auth is a configurable
# username/password login (default admin/admin, stored as a salted hash in the
# state dir; sessions are in-memory so a restart signs everyone out). We keep it
# ON for LAN exposure and OFF for loopback-only (local desktop) by default.
bind_address=127.0.0.1
auth_disabled=1
if [[ ${PROBE_EXPOSE:-} == lan ]]; then
  lan_iface=$(ip route show default | awk '{print $5; exit}')
  bind_address=$(ip -4 -brief address show dev "$lan_iface" | awk '{print $3}' | cut -d/ -f1)
  [[ -n $bind_address ]] || { echo "Could not determine the LAN address on ${lan_iface:-?}." >&2; exit 2; }
  auth_disabled=0
fi
# The credential store must live where the unprivileged service can write it
# (ProtectSystem=strict keeps /etc read-only; only the state dir is writable).
auth_file=$state_dir/dashboard-auth.json

python3 -m venv "$venv_dir"
"$venv_dir/bin/pip" install --upgrade pip
"$venv_dir/bin/pip" install -r "$repo_dir/dashboard/requirements.txt"
find "$repo_dir/scripts" -maxdepth 1 -type f -name '*.sh' -exec chmod 0755 {} +

# Deployment topology: single-process by default (one systemd unit serving both
# the API and the UI on port 8088). PROBE_SPLIT=1 runs the frontend/backend split
# (#35): a backend unit on loopback:8090 (the API + all collection, carrying the
# auth env) and a thin frontend proxy on the public bind:8088 (dashboard.frontend)
# that serves the static shell locally and reverse-proxies /api to the backend.
# Auth is delegated to the backend session login in BOTH modes — the frontend adds
# no auth layer, it just forwards the np_session cookie.
split_mode=0
[[ ${PROBE_SPLIT:-} == 1 ]] && split_mode=1
backend_port=8090

# The backend [Service] env is identical in both modes; only the bind differs.
backend_env() {
  local bind=$1
  cat <<EOF
Environment=PROBE_BIND=$bind
Environment=PROBE_PORT=$backend_port
Environment=PROBE_AUTH_FILE=$auth_file
Environment=PROBE_AUTH_DISABLED=$auth_disabled
Environment=PROBE_CAPTURE_DIR=$state_dir/captures
Environment=PROBE_SNAPSHOT_DIR=$state_dir/snapshots
Environment=PROBE_TARGET_FILE=$config_dir/targets.csv
Environment=PROBE_SETTINGS_FILE=$state_dir/settings.json
EOF
}

# Shared hardening block (same for every unit we write).
hardening() {
  cat <<EOF
# NoNewPrivileges must stay off: capture jobs spawn dumpcap, which gains
# CAP_NET_RAW/CAP_NET_ADMIN through file capabilities (wireshark group).
NoNewPrivileges=false
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$repo_dir $config_dir
ReadWritePaths=$state_dir
EOF
}

units_dir=/etc/systemd/system
tmp_files=()
cleanup() { [[ ${#tmp_files[@]} -gt 0 ]] && rm -f -- "${tmp_files[@]}"; }
trap cleanup EXIT

if [[ $split_mode -eq 1 ]]; then
  # --- Backend: API + collection on loopback:8090 (never exposed directly) ---
  be_tmp=$(mktemp); tmp_files+=("$be_tmp")
  cat > "$be_tmp" <<EOF
[Unit]
Description=Fieldline Network Probe Backend (API)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=$service_user
Group=$service_user
SupplementaryGroups=wireshark
WorkingDirectory=$repo_dir
$(backend_env 127.0.0.1)
ExecStart=$venv_dir/bin/waitress-serve --listen=127.0.0.1:$backend_port dashboard.app:app
Restart=on-failure
RestartSec=3
$(hardening)
[Install]
WantedBy=multi-user.target
EOF
  install -o root -g root -m 0644 "$be_tmp" "$units_dir/network-probe-backend.service"

  # --- Frontend: static shell + reverse proxy on the public bind:8088 ---
  fe_tmp=$(mktemp); tmp_files+=("$fe_tmp")
  cat > "$fe_tmp" <<EOF
[Unit]
Description=Fieldline Network Probe Dashboard (frontend proxy)
After=network-online.target network-probe-backend.service
Wants=network-online.target
[Service]
Type=simple
User=$service_user
Group=$service_user
WorkingDirectory=$repo_dir
Environment=PROBE_BIND=$bind_address
Environment=PROBE_FRONTEND_PORT=8088
Environment=PROBE_BACKEND_URL=http://127.0.0.1:$backend_port
ExecStart=$venv_dir/bin/waitress-serve --listen=$bind_address:8088 dashboard.frontend:app
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$repo_dir
ReadWritePaths=$state_dir
[Install]
WantedBy=multi-user.target
EOF
  install -o root -g root -m 0644 "$fe_tmp" "$units_dir/network-probe-dashboard.service"

  systemctl daemon-reload
  systemctl enable network-probe-backend.service network-probe-dashboard.service
  systemctl restart network-probe-backend.service
  systemctl restart network-probe-dashboard.service
  sleep 2
  systemctl --no-pager --full status network-probe-backend.service || true
  systemctl --no-pager --full status network-probe-dashboard.service || true
  echo "Split mode: backend on 127.0.0.1:$backend_port, frontend proxy on http://$bind_address:8088"
else
  # --- Single process: API + UI in one unit on port 8088 ---
  unit_tmp=$(mktemp); tmp_files+=("$unit_tmp")
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
Environment=PROBE_AUTH_FILE=$auth_file
Environment=PROBE_AUTH_DISABLED=$auth_disabled
Environment=PROBE_CAPTURE_DIR=$state_dir/captures
Environment=PROBE_SNAPSHOT_DIR=$state_dir/snapshots
Environment=PROBE_TARGET_FILE=$config_dir/targets.csv
Environment=PROBE_SETTINGS_FILE=$state_dir/settings.json
ExecStart=$venv_dir/bin/waitress-serve --listen=$bind_address:8088 dashboard.app:app
Restart=on-failure
RestartSec=3
$(hardening)
[Install]
WantedBy=multi-user.target
EOF
  install -o root -g root -m 0644 "$unit_tmp" "$units_dir/network-probe-dashboard.service"
  # Split mode may have been installed previously; make single-mode authoritative.
  if systemctl list-unit-files network-probe-backend.service >/dev/null 2>&1 \
     && [[ -e $units_dir/network-probe-backend.service ]]; then
    systemctl disable --now network-probe-backend.service 2>/dev/null || true
    rm -f "$units_dir/network-probe-backend.service"
  fi
  systemctl daemon-reload
  systemctl enable network-probe-dashboard.service
  systemctl restart network-probe-dashboard.service
  sleep 2
  systemctl --no-pager --full status network-probe-dashboard.service || true
  echo "Dashboard installed at http://$bind_address:8088"
fi
if [[ $auth_disabled == 0 ]]; then
  echo "LAN exposure is active: sign in with the default credentials admin / admin,"
  echo "then change the password under Settings -> Account. Credentials hash lives in $auth_file."
  echo "Note: HTTP only - use it on trusted management networks; do not port-forward to the internet."
else
  echo "Bound to loopback: auth is disabled for local access (set PROBE_EXPOSE=lan to require login)."
fi
echo "Edit approved targets in $config_dir/targets.csv, then restart the service."
