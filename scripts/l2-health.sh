#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <interface> [duration-seconds=30]" >&2
  exit 2
fi
iface=$1
duration=${2:-30}
[[ -d /sys/class/net/$iface ]] || { echo "Unknown interface: $iface" >&2; exit 2; }
[[ $duration =~ ^[0-9]+$ ]] && (( duration >= 5 && duration <= 300 )) || { echo "Duration must be 5-300 seconds" >&2; exit 2; }
command -v dumpcap >/dev/null || { echo "dumpcap is required" >&2; exit 2; }
command -v tshark >/dev/null || { echo "tshark is required" >&2; exit 2; }

temp_dir=$(mktemp -d)
trap 'rm -rf -- "$temp_dir"' EXIT
pcap="$temp_dir/l2-health.pcapng"
before_drop=$(cat "/sys/class/net/$iface/statistics/rx_dropped")
before_err=$(cat "/sys/class/net/$iface/statistics/rx_errors")
dumpcap -q -i "$iface" -a "duration:$duration" -w "$pcap"
after_drop=$(cat "/sys/class/net/$iface/statistics/rx_dropped")
after_err=$(cat "/sys/class/net/$iface/statistics/rx_errors")

total=$(tshark -n -r "$pcap" -T fields -e frame.number 2>/dev/null | wc -l)
bytes=$(tshark -n -r "$pcap" -T fields -e frame.len 2>/dev/null | awk '{s+=$1} END {print s+0}')
count_filter() { tshark -n -r "$pcap" -Y "$1" -T fields -e frame.number 2>/dev/null | wc -l || true; }

echo "metric,value,unit"
echo "duration,$duration,seconds"
echo "frames,$total,frames"
echo "average_frames_per_second,$((total / duration)),frames_per_second"
echo "average_bits_per_second,$((bytes * 8 / duration)),bits_per_second"
echo "ethernet_broadcast,$(count_filter 'eth.dst == ff:ff:ff:ff:ff:ff'),frames"
echo "ethernet_multicast,$(count_filter 'eth.dst[0] & 1'),frames"
echo "arp,$(count_filter 'arp'),frames"
echo "stp,$(count_filter 'stp'),frames"
echo "lldp_or_cdp,$(count_filter 'lldp || cdp'),frames"
echo "tcp_retransmission,$(count_filter 'tcp.analysis.retransmission || tcp.analysis.fast_retransmission'),frames"
echo "tcp_reset,$(count_filter 'tcp.flags.reset == 1'),frames"
echo "s7,$(count_filter 's7comm || s7comm_plus'),frames"
echo "opcua,$(count_filter 'opcua'),frames"
echo "profinet,$(count_filter 'pn_dcp || pn_io'),frames"
echo "nic_rx_drops_delta,$((after_drop - before_drop)),events"
echo "nic_rx_errors_delta,$((after_err - before_err)),events"
echo
echo "top_source_mac,frames"
tshark -n -r "$pcap" -T fields -e eth.src 2>/dev/null | awk 'NF {c[$1]++} END {for (v in c) print v "," c[v]}' | sort -t, -k2,2nr | head -20 || true
echo
echo "top_broadcast_source_mac,frames"
tshark -n -r "$pcap" -Y 'eth.dst == ff:ff:ff:ff:ff:ff' -T fields -e eth.src 2>/dev/null | awk 'NF {c[$1]++} END {for (v in c) print v "," c[v]}' | sort -t, -k2,2nr | head -20 || true
