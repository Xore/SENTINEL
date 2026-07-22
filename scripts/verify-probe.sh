#!/usr/bin/env bash
set -uo pipefail

failures=0
checks=0
check() {
  checks=$((checks + 1))
  if "$@" >/dev/null 2>&1; then printf 'PASS  %s\n' "$*"; else printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); fi
}

echo "Network probe verification"
check command -v ip
check command -v dumpcap
check command -v tshark
check command -v nmap
check command -v tracepath
check command -v iw
check command -v ethtool
check command -v python3
venv_python=/opt/network-probe-venv/bin/python; [[ -x $venv_python ]] || venv_python=python3; check "$venv_python" -c 'import flask, waitress'
check test -r /proc/net/dev
check test -d /sys/class/net
if command -v dumpcap >/dev/null 2>&1; then check dumpcap -D; fi
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files network-probe-dashboard.service >/dev/null 2>&1; then
  check systemctl is-enabled network-probe-dashboard.service
  check systemctl is-active network-probe-dashboard.service
fi
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files network-probe-monitor.service >/dev/null 2>&1; then
  check systemctl is-enabled network-probe-monitor.service
  check systemctl is-active network-probe-monitor.service
  # The state dir is 0750 for the service user; fall back to sudo when possible.
  if [[ -r /var/lib/network-probe ]]; then
    check test -s /var/lib/network-probe/monitor.db
  elif sudo -n true 2>/dev/null; then
    check sudo -n test -s /var/lib/network-probe/monitor.db
  fi
fi
if command -v curl >/dev/null 2>&1; then
  probe_bind=$(systemctl show network-probe-dashboard.service -p Environment 2>/dev/null | grep -o 'PROBE_BIND=[^ ]*' | head -1 | cut -d= -f2)
  check curl -sf --max-time 5 "http://${probe_bind:-127.0.0.1}:8088/healthz"
fi
echo "$((checks - failures))/$checks checks passed"
(( failures == 0 ))
