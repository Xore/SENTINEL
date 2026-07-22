#!/usr/bin/env bash
set -euo pipefail

output_dir=${1:-./snapshots}
mkdir -p "$output_dir"
chmod 0700 "$output_dir"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
output="$output_dir/network_snapshot_${stamp}.txt"
section() { printf '\n===== %s =====\n' "$1"; }

{
  echo "snapshot_utc=$stamp"
  echo "hostname=$(hostname)"
  echo "kernel=$(uname -a)"
  if [[ -r /etc/os-release ]]; then . /etc/os-release; echo "os=${PRETTY_NAME:-unknown}"; fi
  section "UPTIME AND LOAD"; uptime
  section "MEMORY"; free -h
  section "FILESYSTEM"; df -hT
  section "BLOCK DEVICES"; lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,MODEL
  section "LINKS"; ip -details -statistics link
  section "ADDRESSES"; ip -brief address
  section "ROUTES"; ip -details route show table all
  section "NEIGHBORS"; ip -statistics neighbor show
  section "POLICY RULES"; ip rule show
  section "LISTENING SOCKETS"; ss -lntup
  section "DNS"; command -v resolvectl >/dev/null && resolvectl status || cat /etc/resolv.conf
  section "TIME"; timedatectl status; command -v chronyc >/dev/null && chronyc tracking || true; command -v chronyc >/dev/null && chronyc sources -v || true
  section "NETWORK MANAGER DEVICES"; command -v nmcli >/dev/null && nmcli -f GENERAL.DEVICE,GENERAL.TYPE,GENERAL.STATE,GENERAL.CONNECTION device show || true
  section "ETHERNET DETAILS"
  for iface_path in /sys/class/net/*; do
    iface=$(basename "$iface_path")
    [[ $iface == lo ]] && continue
    echo "--- $iface ---"
    command -v ethtool >/dev/null && ethtool "$iface" 2>&1 || true
    command -v ethtool >/dev/null && ethtool -S "$iface" 2>&1 || true
  done
  section "WI-FI"
  command -v iw >/dev/null && iw dev || true
  if command -v iw >/dev/null; then
    while read -r iface; do
      [[ -n $iface ]] || continue
      echo "--- $iface ---"
      iw dev "$iface" info
      iw dev "$iface" link
      iw dev "$iface" station dump 2>&1 || true
      iw dev "$iface" survey dump 2>&1 || true
    done < <(iw dev | awk '$1=="Interface" {print $2}')
  fi
  section "INSTALLED ANALYSIS TOOLS"
  for tool in dumpcap tshark wireshark nmap tracepath dig chronyc iw ethtool ntopng zeek suricata; do
    printf '%-12s' "$tool"; command -v "$tool" 2>/dev/null || echo missing
  done
} > "$output" 2>&1

sha256sum "$output" > "${output}.sha256"
chmod 0600 "$output" "${output}.sha256"
echo "$output"
