#!/usr/bin/env bash
# Double-clickable "start the probe" helper for the Ubuntu desktop.
# Ensures the two probe systemd services are running and opens the dashboard in
# the default browser. Installed onto the desktop by install-desktop-launcher.sh.
#
# It needs no arguments. Starting an inactive service needs privilege, so it
# uses pkexec (a graphical password prompt) only when a service is actually
# down; if the services are already running (the normal case, they start at
# boot) it just opens the browser. It never reads or displays the access token
# - retrieve that once with `sudo cat /etc/network-probe/dashboard-token`.
set -uo pipefail

PORT=8088
SERVICES=(network-probe-dashboard network-probe-monitor)

notify() { command -v notify-send >/dev/null 2>&1 && notify-send "Network Probe" "$1" || true; }

# Start any inactive service (pkexec prompts graphically; sudo as a fallback).
need_start=()
for s in "${SERVICES[@]}"; do
  systemctl is-active --quiet "$s" 2>/dev/null || need_start+=("$s")
done
if ((${#need_start[@]})); then
  notify "Starting: ${need_start[*]}"
  if command -v pkexec >/dev/null 2>&1; then
    pkexec systemctl start "${need_start[@]}" || notify "Could not start: ${need_start[*]}"
  else
    sudo systemctl start "${need_start[@]}" 2>/dev/null || notify "Could not start: ${need_start[*]}"
  fi
fi

# Dashboard URL: the service's bind address (PROBE_BIND), else this host's
# primary IP, else loopback. Follows the box even after a DHCP address change.
# `systemctl show -p Environment` prints one line, and the FIRST token keeps an
# `Environment=` prefix (e.g. `Environment=PROBE_BIND=1.2.3.4 PROBE_PORT=...`),
# so match PROBE_BIND anywhere in the token, not just at line start.
bind=$(systemctl show network-probe-dashboard -p Environment 2>/dev/null | tr ' ' '\n' | sed -n 's/.*PROBE_BIND=//p' | head -1)
if [[ -z ${bind:-} || $bind == 0.0.0.0 ]]; then
  bind=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
host=${bind:-127.0.0.1}
url="http://${host}:${PORT}/"

# Give the service a moment to accept connections, then open the browser.
for _ in $(seq 1 10); do
  curl -sf --max-time 2 "http://${host}:${PORT}/healthz" >/dev/null 2>&1 && break
  sleep 1
done

notify "Opening $url"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$url" >/dev/null 2>&1 &
else
  for b in google-chrome chromium firefox; do
    command -v "$b" >/dev/null 2>&1 && { "$b" "$url" >/dev/null 2>&1 & break; }
  done
fi
