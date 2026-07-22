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

# Enable extended HTTP logging in the EVE http record so the dashboard alert
# drill-down can show the domain/subdomain, path, method, status, every
# request/response header AND the request/response body text (e.g. POSTed form
# fields, JSON payloads). This edits only the eve-log `- http:` output block; it
# does not change detection.
#
# Scope of the body text: Suricata only reassembles/buffers an HTTP body when a
# rule inspects it, so `http-body`/`http-body-printable` surface the body on
# ALERTED transactions - which is exactly the alert-drill-down case the operator
# cares about - not on every passive plain-HTTP event (that would be a firehose
# and defeats the point of a light passive probe). Bodies come from Suricata's
# own reassembly (bounded by request-body-limit/response-body-limit, default
# 100kb) as printable text - no on-disk file extraction/filestore, so the probe
# stays passive and light. Body text is only ever available for cleartext HTTP;
# HTTPS stays opaque (only the TLS handshake/SNI is visible).
python3 - <<'PY'
import re
path = "/etc/suricata/suricata.yaml"
try:
    text = open(path).read()
except OSError:
    raise SystemExit(0)
# Replace the eve `- http:` list entry (and its current indented children) with
# an extended block that also dumps all request+response headers and bodies.
pattern = re.compile(r"(\n([ \t]*)- http:\n)(?:\2[ \t]+.*\n)*")
def repl(m):
    ind = m.group(2)
    child = ind + "    "
    return (f"\n{ind}- http:\n"
            f"{child}extended: yes\n"
            f"{child}dump-all-headers: both\n"
            f"{child}http-body: yes\n"
            f"{child}http-body-printable: yes\n")
new, n = pattern.subn(repl, text, count=1)
if n:
    text = new
    print("Extended HTTP EVE logging enabled (all headers + printable bodies).")
else:
    print("Could not find an eve `- http:` block to extend; leaving config as-is.")

# Make sure the app-layer actually reassembles bodies so they can be logged. The
# stock config ships these enabled with 100kb limits, but normalise them in case
# a prior edit disabled request/response-body inspection.
for key in ("request-body-limit", "response-body-limit"):
    if re.search(rf"^\s*#?\s*{key}:", text, flags=re.MULTILINE) is None:
        continue
    text = re.sub(rf"^(\s*)#?\s*{key}:.*$", rf"\g<1>{key}: 100kb",
                  text, count=1, flags=re.MULTILINE)
open(path, "w").write(text)
PY

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
