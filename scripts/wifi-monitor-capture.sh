#!/usr/bin/env bash
# Bounded Wi-Fi monitor-mode capture and management-frame summary.
#
# Puts a wireless interface into monitor mode, dwells on one channel (or hops a
# short list), captures 802.11 management/control frames with dumpcap, then
# restores the interface to managed mode and prints a summary of the beaconing
# APs and the client stations seen (from probe requests and data frames).
#
# This needs CAP_NET_ADMIN to switch modes and set the channel, so run it with
# sudo. It is an operator tool, deliberately NOT wired to a dashboard button
# (the web process stays unprivileged). It only captures - it never transmits.
#
# Usage: sudo wifi-monitor-capture.sh <iface> <channel[,channel...]> [seconds=30]
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: sudo $0 <iface> <channel[,channel...]> [seconds=30]" >&2
  exit 2
fi
iface=$1
channels=$2
duration=${3:-30}
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run with sudo (monitor mode needs CAP_NET_ADMIN)." >&2; exit 2; }
[[ -d /sys/class/net/$iface ]] || { echo "Unknown interface: $iface" >&2; exit 2; }
[[ $duration =~ ^[0-9]+$ ]] && (( duration >= 5 && duration <= 120 )) || { echo "seconds must be 5-120" >&2; exit 2; }
[[ $channels =~ ^[0-9]+(,[0-9]+)*$ ]] || { echo "channels must be comma-separated numbers, e.g. 1,6,11" >&2; exit 2; }
for tool in iw dumpcap tshark; do command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 2; }; done

IFS=',' read -r -a chan_list <<< "$channels"
temp_dir=$(mktemp -d)
pcap="$temp_dir/wifi-monitor.pcapng"

restore() {
  # Best-effort return to managed mode so normal Wi-Fi keeps working.
  ip link set "$iface" down 2>/dev/null || true
  iw dev "$iface" set type managed 2>/dev/null || true
  ip link set "$iface" up 2>/dev/null || true
  rm -rf -- "$temp_dir"
}
trap restore EXIT

echo "Switching $iface to monitor mode..." >&2
ip link set "$iface" down
iw dev "$iface" set monitor control 2>/dev/null || iw dev "$iface" set type monitor
ip link set "$iface" up

# Split the capture time across the requested channels (dwell per channel).
per=$(( duration / ${#chan_list[@]} )); (( per < 1 )) && per=1
for chan in "${chan_list[@]}"; do
  if ! iw dev "$iface" set channel "$chan" 2>/dev/null; then
    echo "warning: could not set channel $chan (may be a DFS/6GHz channel)" >&2
    continue
  fi
  echo "Capturing channel $chan for ${per}s..." >&2
  dumpcap -q -i "$iface" -a "duration:$per" -w "$temp_dir/ch${chan}.pcapng" 2>/dev/null || true
done
# Merge per-channel files (mergecap ships with wireshark-common).
mergecap -w "$pcap" "$temp_dir"/ch*.pcapng 2>/dev/null || cp "$temp_dir"/ch*.pcapng "$pcap" 2>/dev/null || true
[[ -s $pcap ]] || { echo "no frames captured (radio blocked or no traffic)" >&2; exit 1; }

frames=$(tshark -n -r "$pcap" -T fields -e frame.number 2>/dev/null | wc -l)
echo "channels,${channels}"
echo "seconds,${duration}"
echo "frames,${frames}"
echo
echo "# Access points seen (from beacons): bssid,ssid,channel,signal_dbm,beacons"
tshark -n -r "$pcap" -Y 'wlan.fc.type_subtype == 0x08' \
  -T fields -e wlan.bssid -e wlan.ssid -e wlan_radio.channel -e wlan_radio.signal_dbm 2>/dev/null \
  | awk 'NF>=1 {key=$1; ssid[key]=$2; chan[key]=$3; sig[key]=$4; n[key]++}
         END {for (b in n) printf "%s,%s,%s,%s,%s\n", b, ssid[b], chan[b], sig[b], n[b]}' \
  | sort -t, -k5,5nr | head -40 || true
echo
echo "# Client stations seen (probe requests + data frames): station_mac,frames"
tshark -n -r "$pcap" -Y 'wlan.fc.type_subtype == 0x04 || wlan.fc.type == 2' \
  -T fields -e wlan.sa 2>/dev/null \
  | awk 'NF {c[$1]++} END {for (m in c) print m "," c[m]}' \
  | sort -t, -k2,2nr | head -40 || true
