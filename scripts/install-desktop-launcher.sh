#!/usr/bin/env bash
# Installs a double-clickable launcher on the current user's Ubuntu desktop that
# starts the probe services and opens the dashboard (scripts/start-probe.sh).
#
# Run as your NORMAL desktop user (not root/sudo) so it lands on your Desktop
# and is trusted for your session:
#   ./scripts/install-desktop-launcher.sh
set -euo pipefail

[[ ${EUID:-$(id -u)} -ne 0 ]] || { echo "Run as your normal desktop user, not root." >&2; exit 2; }

repo_dir=$(readlink -f "$(dirname "$0")/..")
start_script="$repo_dir/scripts/start-probe.sh"
[[ -f $start_script ]] || { echo "Missing $start_script" >&2; exit 2; }
chmod +x "$start_script" 2>/dev/null || true

desktop_dir=$(xdg-user-dir DESKTOP 2>/dev/null || true)
[[ -n ${desktop_dir:-} ]] || desktop_dir="$HOME/Desktop"
apps_dir="$HOME/.local/share/applications"
mkdir -p "$desktop_dir" "$apps_dir"

make_entry() {
  cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Network Probe Dashboard
Comment=Start the probe services and open the dashboard
Exec=$start_script
Icon=utilities-system-monitor
Terminal=false
Categories=Network;System;Monitor;
Keywords=probe;network;dashboard;monitor;
EOF
  chmod +x "$1"
}

desktop_entry="$desktop_dir/analyse-probe.desktop"
apps_entry="$apps_dir/analyse-probe.desktop"
make_entry "$desktop_entry"
make_entry "$apps_entry"

# GNOME (Ubuntu default) will not run a desktop launcher on a double-click until
# it is marked trusted; without this it opens as a text file.
gio set "$desktop_entry" metadata::trusted true 2>/dev/null || true
update-desktop-database "$apps_dir" 2>/dev/null || true

echo "Installed launcher:"
echo "  $desktop_entry   (double-click on the desktop)"
echo "  $apps_entry      (also appears in the Activities app grid)"
echo
echo "Double-click the desktop icon. If GNOME shows an 'Untrusted' prompt the"
echo "first time, choose 'Trust and Launch'."
