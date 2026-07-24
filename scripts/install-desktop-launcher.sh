#!/usr/bin/env bash
# Installs double-clickable launchers on the current user's Ubuntu desktop:
#   - Network Probe Dashboard   -> starts the services + opens the dashboard
#   - Select IDS Capture Adapter -> picks which NIC Suricata captures on
#
# Run as your NORMAL desktop user (not root/sudo) so they land on your Desktop
# and are trusted for your session:
#   ./scripts/install-desktop-launcher.sh
set -euo pipefail

[[ ${EUID:-$(id -u)} -ne 0 ]] || { echo "Run as your normal desktop user, not root." >&2; exit 2; }

repo_dir=$(readlink -f "$(dirname "$0")/..")
start_script="$repo_dir/scripts/start-probe.sh"
ids_select_script="$repo_dir/scripts/ids-adapter-select.sh"
[[ -f $start_script ]] || { echo "Missing $start_script" >&2; exit 2; }
chmod +x "$start_script" "$ids_select_script" 2>/dev/null || true

desktop_dir=$(xdg-user-dir DESKTOP 2>/dev/null || true)
[[ -n ${desktop_dir:-} ]] || desktop_dir="$HOME/Desktop"
apps_dir="$HOME/.local/share/applications"
mkdir -p "$desktop_dir" "$apps_dir"

# make_entry <file> <Name> <Comment> <Exec> <Icon> <Keywords>
make_entry() {
  cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=$2
Comment=$3
Exec=$4
Icon=$5
Terminal=false
Categories=Network;System;Monitor;
Keywords=$6
EOF
  chmod +x "$1"
  gio set "$1" metadata::trusted true 2>/dev/null || true
}

install_pair() {  # basename Name Comment Exec Icon Keywords
  make_entry "$desktop_dir/$1" "$2" "$3" "$4" "$5" "$6"
  make_entry "$apps_dir/$1"    "$2" "$3" "$4" "$5" "$6"
}

install_pair analyse-probe.desktop \
  "Network Probe Dashboard" "Start the probe services and open the dashboard" \
  "$start_script" "utilities-system-monitor" "probe;network;dashboard;monitor;"

install_pair analyse-ids-adapter.desktop \
  "Select IDS Capture Adapter" "Choose which NIC Suricata (the IDS) captures on, or set it to auto" \
  "$ids_select_script" "network-wired" "ids;suricata;adapter;interface;capture;nic;"

update-desktop-database "$apps_dir" 2>/dev/null || true

echo "Installed launchers on $desktop_dir:"
echo "  analyse-probe.desktop        (Network Probe Dashboard)"
echo "  analyse-ids-adapter.desktop  (Select IDS Capture Adapter)"
echo "  ...and in the Activities app grid ($apps_dir)"
echo
echo "Double-click a desktop icon. If GNOME shows an 'Untrusted' prompt the"
echo "first time, choose 'Trust and Launch'."
