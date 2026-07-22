#!/usr/bin/env bash
# Installs Suricata as a passive signature-based IDS for the probe and wires its
# EVE JSON alert stream so the dashboard can read it.
#
# Passive/IDS only - AF_PACKET capture, never inline/IPS, so it cannot block or
# alter traffic. Point it at the no-IP capture interface (SPAN/TAP) when you
# have one; otherwise it watches the management interface, which still sees
# traffic to/from the probe plus broadcast/multicast.
#
# Review this script, then run:  sudo ./scripts/install-ids.sh --apply [iface]
set -euo pipefail

iface_arg=""
if [[ ${1:-} == --apply ]]; then iface_arg=${2:-}; else
  echo "Installs Suricata (passive IDS) and exposes its EVE alerts to the dashboard."
  echo "Review this script, then run: sudo $0 --apply [interface]" >&2
  exit 2
fi
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run with sudo." >&2; exit 2; }
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || { echo "Intended for Ubuntu 24.04; detected ${PRETTY_NAME:-unknown}." >&2; exit 2; }

# Default to the first UP wired interface (capture NIC if present, else mgmt).
iface=${iface_arg:-$(ip -brief link | awk '$1 !~ /^(lo|wl)/ && $2 == "UP" {print $1; exit}')}
[[ -n $iface && -d /sys/class/net/$iface ]] || { echo "No usable interface (pass one explicitly)." >&2; exit 2; }
read_group=probe-dashboard
getent group "$read_group" >/dev/null || read_group=""   # dashboard may not be installed yet

echo "Suricata will monitor: $iface"
[[ -n $read_group ]] && echo "EVE alerts will be readable by group: $read_group"

export DEBIAN_FRONTEND=noninteractive
apt-get install -y suricata jq
systemctl stop suricata 2>/dev/null || true

# Select the monitored interface (Debian/Ubuntu unit reads /etc/default/suricata).
if grep -q '^IFACE=' /etc/default/suricata 2>/dev/null; then
  sed -i "s/^IFACE=.*/IFACE=$iface/" /etc/default/suricata
else
  echo "IFACE=$iface" >> /etc/default/suricata
fi
# Keep the af-packet section's first interface in sync (used by `suricata -T`
# and by the unit on some releases).
sed -i "0,/^\(\s*\)- interface:.*/s//\1- interface: $iface/" /etc/suricata/suricata.yaml

# Drop capabilities to the dashboard's group after opening the capture socket,
# so eve.json is readable by the unprivileged web process.
if [[ -n $read_group ]]; then
  if grep -qE '^\s*#?\s*run-as:' /etc/suricata/suricata.yaml; then
    python3 - "$read_group" <<'PY'
import re, sys
group = sys.argv[1]
path = "/etc/suricata/suricata.yaml"
text = open(path).read()
block = f"run-as:\n  user: root\n  group: {group}\n"
text = re.sub(r'^\s*#?\s*run-as:.*(?:\n\s+#?\s*(?:user|group):.*)*',
              block.rstrip(), text, count=1, flags=re.MULTILINE)
open(path, "w").write(text)
PY
  fi
  install -d -o root -g "$read_group" -m 0750 /var/log/suricata
fi

# Pull the Emerging Threats Open ruleset.
echo "Updating rules (ET Open)..."
suricata-update --no-test 2>&1 | tail -5 || echo "suricata-update reported issues; continuing with any existing rules."

# Validate the configuration before enabling the service.
if ! suricata -T -c /etc/suricata/suricata.yaml -i "$iface" 2>&1 | tail -5; then
  echo "Suricata config test FAILED - not enabling the service." >&2
  exit 1
fi

systemctl enable suricata
systemctl restart suricata
sleep 3
systemctl --no-pager --full status suricata | head -12 || true

# Make the live eve.json group-readable (rotated files inherit dir perms).
[[ -n $read_group && -f /var/log/suricata/eve.json ]] && chgrp "$read_group" /var/log/suricata/eve.json && chmod 0640 /var/log/suricata/eve.json || true

echo
echo "Suricata IDS installed and watching $iface."
echo "Alerts: /var/log/suricata/eve.json  ·  dashboard: Security tab / /api/ids/alerts"
echo "To watch a SPAN/TAP capture NIC instead, re-run: sudo $0 --apply <capture-iface>"
