#!/usr/bin/env bash
# Installs the generic privileged reconciler as a root systemd service.
#
# The reconciler (scripts/reconciler.py) reconciles actual system state toward
# desired state the unprivileged dashboard writes as JSON, running the appliers
# in scripts/reconcile.d/. It is what lets the website change privileged, network
# settings safely - including a timed AUTO-ROLLBACK so a change that would lock
# you out of a Wi-Fi-only box reverts itself unless you confirm in time.
#
# Review this script, then run:  sudo ./scripts/install-reconciler.sh --apply
set -euo pipefail

[[ ${1:-} == --apply ]] || { echo "Installs the privileged reconciler daemon."; echo "Review, then run: sudo $0 --apply" >&2; exit 2; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run with sudo." >&2; exit 2; }

repo_dir=$(readlink -f "$(dirname "$0")/..")
daemon="$repo_dir/scripts/reconciler.py"
appliers="$repo_dir/scripts/reconcile.d"
[[ -f $daemon ]] || { echo "Missing $daemon" >&2; exit 2; }
chmod +x "$daemon"

# Pick an interpreter: prefer the app venv, fall back to system python3.
py="$repo_dir/.venv/bin/python"
[[ -x $py ]] || py=$(command -v python3 || true)
[[ -n ${py:-} ]] || { echo "No python3 found (and no .venv). Install python3." >&2; exit 2; }

# Desired-state dir lives in the dashboard's state dir so the website can write
# it; the daemon (root) reads it and writes result state to a runtime dir.
desired_dir=/var/lib/network-probe/reconcile
mkdir -p "$desired_dir"
chmod 0755 "$desired_dir"

# Hand the desired dir to the dashboard service account so the website can drop
# desired-state files. No secrets here (world-readable), only intent.
dash_user=$(systemctl show network-probe-dashboard -p User --value 2>/dev/null || true)
if [[ -n ${dash_user:-} ]] && id "$dash_user" >/dev/null 2>&1; then
  chown "$dash_user":"$dash_user" "$desired_dir" 2>/dev/null \
    && echo "Desired-state dir owned by '$dash_user' (dashboard-writable)."
fi

unit=/etc/systemd/system/network-probe-reconciler.service
cat > "$unit" <<UNIT
[Unit]
Description=Network Probe privileged reconciler (enacts dashboard-requested system changes with auto-rollback)
After=network.target

[Service]
Type=simple
Environment=PROBE_RECONCILE_DESIRED_DIR=$desired_dir
Environment=PROBE_RECONCILE_STATE_DIR=/run/network-probe-reconcile
Environment=PROBE_RECONCILE_APPLIER_DIR=$appliers
ExecStart=$py $daemon daemon
Restart=on-failure
RestartSec=10
RuntimeDirectory=network-probe-reconcile
RuntimeDirectoryMode=0755
# It changes privileged settings (network etc.), so it needs root; keep the
# blast radius small with sane hardening that still allows those changes.
NoNewPrivileges=no
ProtectHome=yes

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable network-probe-reconciler.service
systemctl restart network-probe-reconciler.service
sleep 1

echo
echo "Reconciler installed and running."
echo "  desired-state dir : $desired_dir  (dashboard writes <name>.desired.json)"
echo "  result-state dir  : /run/network-probe-reconcile"
echo "  appliers          : $appliers"
echo
echo "Status (no root needed):  $py $daemon status"
