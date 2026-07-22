#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 5 ]]; then
  echo "Usage: sudo $0 <interface> <output-dir> [seconds-per-file=300] [file-count=24] [MiB-per-file=2048]" >&2
  exit 2
fi

iface=$1
output_dir=$2
seconds=${3:-300}
file_count=${4:-24}
size_mib=${5:-2048}

[[ -d /sys/class/net/$iface ]] || { echo "Interface does not exist: $iface" >&2; exit 2; }
command -v dumpcap >/dev/null || { echo "dumpcap is required (package: tshark)." >&2; exit 2; }
[[ $seconds =~ ^[0-9]+$ && $file_count =~ ^[0-9]+$ && $size_mib =~ ^[0-9]+$ ]] || { echo "Rotation values must be positive integers." >&2; exit 2; }
(( seconds > 0 && file_count > 0 && size_mib > 0 )) || { echo "Rotation values must be greater than zero." >&2; exit 2; }

if ip -brief address show dev "$iface" | grep -Eq '([0-9]{1,3}\.){3}[0-9]{1,3}|[[:xdigit:]]+:'; then
  echo "Refusing capture: $iface has a layer-3 address. Use a dedicated no-IP capture interface." >&2
  exit 1
fi

mkdir -p "$output_dir"
chmod 0700 "$output_dir"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
prefix="$output_dir/probe_${iface}_${stamp}"
metadata="${prefix}.metadata.txt"

{
  echo "start_utc=$stamp"
  echo "hostname=$(hostname)"
  echo "interface=$iface"
  echo "interface_mac=$(cat /sys/class/net/$iface/address)"
  echo "kernel=$(uname -r)"
  echo "rotation_seconds=$seconds"
  echo "rotation_files=$file_count"
  echo "rotation_mib=$size_mib"
  ip -details link show dev "$iface"
} > "$metadata"

echo "Capturing on $iface. Stop with Ctrl-C; ring buffer is bounded to $file_count files."
dumpcap -q -i "$iface" -a "files:$file_count" -b "duration:$seconds" -b "files:$file_count" -b "filesize:$((size_mib * 1024))" -w "${prefix}.pcapng"

echo "end_utc=$(date -u +%Y%m%dT%H%M%SZ)" >> "$metadata"
sha256sum "${prefix}"*.pcapng "$metadata" > "${prefix}.sha256"
chmod 0600 "${prefix}"*
echo "Capture complete: $prefix*"
