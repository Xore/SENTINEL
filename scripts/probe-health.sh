#!/usr/bin/env bash
set -uo pipefail

capture_iface=${1:-}
if [[ -z $capture_iface || ! -d /sys/class/net/$capture_iface ]]; then
  echo "Usage: $0 <capture-interface>" >&2
  exit 2
fi

echo "Probe health at $(date --iso-8601=seconds)"
echo
uptime
free -h
df -hT / /var 2>/dev/null | awk '!seen[$7]++'
echo
ip -brief address show dev "$capture_iface"
echo "Capture interface counters"
ip -s link show dev "$capture_iface"
if ip -brief address show dev "$capture_iface" | grep -Eq '([0-9]{1,3}\.){3}[0-9]{1,3}|[[:xdigit:]]+:'; then
  echo "WARN: capture interface appears to have a layer-3 address"
fi
echo
if command -v docker >/dev/null 2>&1; then
  docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || true
elif command -v podman >/dev/null 2>&1; then
  podman ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || true
fi
