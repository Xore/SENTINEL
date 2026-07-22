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
echo "$((checks - failures))/$checks checks passed"
(( failures == 0 ))
