#!/usr/bin/env bash
set -uo pipefail

echo "Probe preflight (read-only)"
printf 'Time: '; date --iso-8601=seconds
printf 'OS: '; . /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}" || echo unknown
printf 'Kernel: '; uname -r
printf 'Architecture: '; uname -m
printf 'CPU threads: '; nproc
printf 'Memory: '; free -h | awk '/^Mem:/ {print $2 " total, " $7 " available"}'
echo
echo "Block devices"
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,MODEL
echo
echo "Interfaces and addresses"
ip -brief link
ip -brief address
echo
echo "Default routes (management interface should be the only routed interface)"
ip route show default || true
echo
echo "Virtualization/container prerequisites"
for command_name in git curl jq docker podman ethtool tcpdump nmap iw; do
  if command -v "$command_name" >/dev/null 2>&1; then
    printf '%-10s %s\n' "$command_name" "present"
  else
    printf '%-10s %s\n' "$command_name" "missing"
  fi
done
echo
echo "Checks requiring review"
(( $(nproc) >= 8 )) || echo "WARN: fewer than 8 CPU threads"
memory_kib=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
(( memory_kib >= 25165824 )) || echo "WARN: less than 24 GiB RAM (below Malcolm minimum)"
[[ $(uname -m) == x86_64 ]] || echo "WARN: expected x86-64"
echo "Review that the capture NIC has no address or default route. No changes were made."
