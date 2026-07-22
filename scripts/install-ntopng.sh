#!/usr/bin/env bash
# Installs ntopng as a passive flow / traffic-analysis probe with its own web UI.
#
# ntopng does deep flow inspection on a monitored interface and serves a rich
# per-host / per-flow dashboard on its own port (default 3000). It captures
# passively (libpcap, receive-only) - it never injects or alters traffic. Point
# it at the no-IP capture interface (SPAN/TAP) when you have one; otherwise it
# watches the management interface, which still sees traffic to/from the probe
# plus broadcast/multicast.
#
# It keeps its own login (first sign-in forces you to change the default admin
# password) and is reachable from the probe dashboard's Overview → "ntopng
# flows" chip once running.
#
# Review this script, then run:  sudo ./scripts/install-ntopng.sh --apply [iface]
set -euo pipefail

iface_arg=""
if [[ ${1:-} == --apply ]]; then iface_arg=${2:-}; else
  echo "Installs ntopng (passive flow analysis) with its web UI on port 3000."
  echo "Review this script, then run: sudo $0 --apply [interface]" >&2
  exit 2
fi
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run with sudo." >&2; exit 2; }
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || { echo "Intended for Ubuntu 24.04; detected ${PRETTY_NAME:-unknown}." >&2; exit 2; }

# Default to the first UP wired interface (capture NIC if present, else mgmt).
iface=${iface_arg:-$(ip -brief link | awk '$1 !~ /^(lo|wl)/ && $2 == "UP" {print $1; exit}')}
[[ -n $iface && -d /sys/class/net/$iface ]] || { echo "No usable interface (pass one explicitly)." >&2; exit 2; }

echo "ntopng will monitor: $iface"

export DEBIAN_FRONTEND=noninteractive
# redis is ntopng's datastore; both are in the Ubuntu archive.
apt-get install -y ntopng redis-server
systemctl enable --now redis-server
systemctl stop ntopng 2>/dev/null || true

# Minimal, explicit configuration (ntopng reads /etc/ntopng/ntopng.conf).
install -d -m 0755 /etc/ntopng
cat > /etc/ntopng/ntopng.conf <<CONF
# Managed by scripts/install-ntopng.sh - passive flow probe.
-i=$iface
# Web UI port (the probe dashboard links here). ntopng has its own login;
# the first sign-in forces changing the default admin password.
-w=3000
# Local redis installed above.
-r=127.0.0.1:6379
# Do not resolve numeric IPs to names aggressively (quieter, no extra DNS).
-n=0
# Keep the daemon from also opening an unauthenticated port.
--disable-login=0
CONF
chmod 0644 /etc/ntopng/ntopng.conf

systemctl restart ntopng
sleep 3
systemctl --no-pager --full status ntopng | head -12 || true

mgmt_ip=$(ip -4 -brief addr show "$(ip route | awk '/default/{print $5; exit}')" 2>/dev/null | awk '{print $3}' | cut -d/ -f1)
echo
echo "ntopng installed and watching $iface."
echo "Web UI:   http://${mgmt_ip:-<probe-ip>}:3000/   (first login forces a password change; default admin/admin)"
echo "Dashboard: the Overview tab shows a 'ntopng flows' chip once the tool is detected."
echo "To watch a SPAN/TAP capture NIC instead, re-run: sudo $0 --apply <capture-iface>"
