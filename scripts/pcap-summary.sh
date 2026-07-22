#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -r $1 ]]; then
  echo "Usage: $0 capture.pcapng" >&2
  exit 2
fi
command -v capinfos >/dev/null || { echo "capinfos is required (package: tshark)." >&2; exit 2; }
command -v tshark >/dev/null || { echo "tshark is required (package: tshark)." >&2; exit 2; }
pcap=$1

echo "=== Capture properties ==="
capinfos -a -e -d -c -i -z "$pcap"

echo "=== Protocol hierarchy ==="
tshark -n -r "$pcap" -q -z io,phs

echo "=== Top Ethernet sources ==="
tshark -n -r "$pcap" -T fields -e eth.src 2>/dev/null | awk 'NF {count[$1]++} END {for (v in count) print count[v] "," v}' | sort -t, -k1,1nr | head -20 || true

echo "=== Frame classes (frames, average frames/second) ==="
duration=$(capinfos -Tm "$pcap" | awk -F, 'NR==2 {print $14}')
[[ $duration =~ ^[0-9]+([.][0-9]+)?$ ]] || duration=0
for item in broadcast multicast arp stp lldp_cdp wifi_management s7 opcua profinet retransmission; do
  case $item in
    broadcast) filter='eth.dst == ff:ff:ff:ff:ff:ff' ;;
    multicast) filter='eth.dst[0] & 1' ;;
    arp) filter='arp' ;;
    stp) filter='stp' ;;
    lldp_cdp) filter='lldp || cdp' ;;
    wifi_management) filter='wlan.fc.type == 0' ;;
    s7) filter='s7comm || s7comm_plus' ;;
    opcua) filter='opcua' ;;
    profinet) filter='pn_dcp || pn_io' ;;
    retransmission) filter='tcp.analysis.retransmission || tcp.analysis.fast_retransmission' ;;
  esac
  count=$(tshark -n -r "$pcap" -Y "$filter" -T fields -e frame.number 2>/dev/null | wc -l || true)
  rate=$(awk -v c="$count" -v d="$duration" 'BEGIN {if (d>0) printf "%.2f", c/d; else print "n/a"}')
  printf '%s,%s,%s\n' "$item" "$count" "$rate"
done
