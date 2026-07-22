#!/usr/bin/env bash
set -euo pipefail

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run as root: sudo $0" >&2; exit 2; }
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || {
  echo "This installer is intentionally limited to Ubuntu 24.04; detected ${PRETTY_NAME:-unknown}." >&2
  exit 2
}

packages=(tshark wireshark nmap ethtool iw jq curl git dnsutils snmp traceroute mtr-tiny chrony python3-venv python3-pip)
echo "Packages to install from configured Ubuntu repositories: ${packages[*]}"
echo "No services, repositories, firewall rules, or interfaces will be changed by this script."
read -r -p "Continue [type YES]: " confirmation
[[ $confirmation == YES ]] || { echo "Cancelled."; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y "${packages[@]}"
echo "Installed. Configure dumpcap privileges according to site policy, then reboot."
