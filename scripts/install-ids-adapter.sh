#!/usr/bin/env bash
# Installs the Suricata capture-adapter manager as a root systemd service so the
# IDS follows a usable NIC automatically (see scripts/ids-adapter-manager.sh).
#
# Seeds a persistent config (mode + interface + recheck interval), installs and
# enables the daemon, and applies once. Safe to re-run.
#
# Review this script, then run:  sudo ./scripts/install-ids-adapter.sh --apply
set -euo pipefail

[[ ${1:-} == --apply ]] || { echo "Installs the IDS adapter auto-switch daemon."; echo "Review, then run: sudo $0 --apply" >&2; exit 2; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run with sudo." >&2; exit 2; }
command -v suricata >/dev/null || { echo "Suricata is not installed - run scripts/install-ids.sh --apply first." >&2; exit 2; }

repo_dir=$(readlink -f "$(dirname "$0")/..")
manager="$repo_dir/scripts/ids-adapter-manager.sh"
[[ -f $manager ]] || { echo "Missing $manager" >&2; exit 2; }
chmod +x "$manager"

# Config lives in the dashboard's state dir so the website can also write it
# (the manager reads /var/lib/network-probe/ids-adapter.json). The dashboard
# account owns the dir; the config file stays world-readable (no secrets).
config=/var/lib/network-probe/ids-adapter.json
install -d -m 0755 /var/lib/network-probe 2>/dev/null || mkdir -p /var/lib/network-probe

# Seed config only if absent, so a re-run keeps the operator's saved choice.
# Default: auto (follow the best up NIC), recheck every 60s.
if [[ ! -f $config ]]; then
  cat > "$config" <<'JSON'
{
  "mode": "auto",
  "interfaces": [],
  "recheck_seconds": 60
}
JSON
  chmod 0644 "$config"
  echo "Seeded $config (mode=auto, recheck=60s)."
else
  echo "Keeping existing $config."
fi

# Hand the config to the dashboard service account (if present) so the website
# can edit the IDS adapter directly - the root daemon re-reads it every cycle
# and enacts the change. No secrets here, so it stays world-readable.
dash_user=$(systemctl show network-probe-dashboard -p User --value 2>/dev/null || true)
if [[ -n ${dash_user:-} ]] && id "$dash_user" >/dev/null 2>&1; then
  chown "$dash_user":"$dash_user" "$config" 2>/dev/null \
    && echo "Config owned by '$dash_user' (dashboard-editable)."
fi

unit=/etc/systemd/system/network-probe-ids-adapter.service
cat > "$unit" <<UNIT
[Unit]
Description=Suricata capture-adapter manager (auto-switch IDS to a usable NIC)
After=network.target suricata.service
Wants=suricata.service

[Service]
Type=simple
ExecStart=$manager daemon
Restart=on-failure
RestartSec=10
RuntimeDirectory=network-probe-ids
RuntimeDirectoryMode=0755
# It reconfigures + restarts Suricata, so it needs root; keep its blast radius
# small with a few sane hardening knobs that still allow systemctl + config edit.
NoNewPrivileges=no
ProtectHome=yes

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable network-probe-ids-adapter.service
systemctl restart network-probe-ids-adapter.service
sleep 2

echo
echo "IDS adapter manager installed and running."
"$manager" status 2>/dev/null | sed 's/^/  /' || true
echo
echo "Change the adapter from the desktop (Select IDS Capture Adapter) or with:"
echo "  sudo $manager set auto                    # follow the best up NIC"
echo "  sudo $manager set all                     # capture on every up NIC"
echo "  sudo $manager set <if1>,<if2> [secs]      # pin a set of NICs, recheck every <secs>"
