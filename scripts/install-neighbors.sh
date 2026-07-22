#!/usr/bin/env bash
# Installs lldpd so the probe can read LLDP (and CDP/EDP/FDP) neighbours -
# which switch, which port, which VLAN the probe is plugged into.
#
# Configured RECEIVE-ONLY by default: lldpd listens for neighbour frames but
# does not transmit its own, which keeps the probe passive on OT networks.
# The control socket is made group-readable by the dashboard account so the
# unprivileged web process can run `lldpctl` (no sudo).
#
# Review this script, then run:  sudo ./scripts/install-neighbors.sh --apply
set -euo pipefail

if [[ ${1:-} != --apply ]]; then
  echo "Installs lldpd (receive-only) for LLDP/CDP neighbour discovery."
  echo "Review this script, then run: sudo $0 --apply" >&2
  exit 2
fi
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run with sudo." >&2; exit 2; }

read_group=probe-dashboard
getent group "$read_group" >/dev/null || read_group=""

export DEBIAN_FRONTEND=noninteractive
apt-get install -y lldpd

# Receive-only: listen for neighbours, never advertise (passive/OT-safe).
install -d -m 0755 /etc/lldpd.d
cat > /etc/lldpd.d/50-rx-only.conf <<'EOF'
# Passive probe: receive neighbour advertisements, do not transmit.
configure lldp status rx-only
EOF

# lldpcli is setuid and executable only by its owning group (adm on Debian/
# Ubuntu). The unprivileged dashboard account must be in that group to run it
# (it already holds 'wireshark' for capture, so this is a comparable, narrow
# addition - it only lets it query neighbours).
if [[ -n $read_group ]] && [[ -e /usr/sbin/lldpcli ]]; then
  exec_group=$(stat -c '%G' /usr/sbin/lldpcli)
  if [[ -n $exec_group && $exec_group != UNKNOWN ]]; then
    usermod -aG "$exec_group" "$read_group"
    echo "Added $read_group to '$exec_group' so it can run lldpcli."
    echo "Restart the dashboard for the new group to take effect: systemctl restart network-probe-dashboard"
  fi
fi

# Make the control socket readable by the dashboard group after each (re)start.
if [[ -n $read_group ]]; then
  mkdir -p /etc/systemd/system/lldpd.service.d
  cat > /etc/systemd/system/lldpd.service.d/10-socket-group.conf <<EOF
[Service]
ExecStartPost=/bin/sh -c 'for i in 1 2 3 4 5; do [ -S /run/lldpd.socket ] && break; sleep 1; done; chgrp $read_group /run/lldpd.socket 2>/dev/null || true; chmod g+rw /run/lldpd.socket 2>/dev/null || true'
EOF
  systemctl daemon-reload
fi

systemctl enable lldpd
systemctl restart lldpd
sleep 2
systemctl --no-pager --full status lldpd | head -8 || true
echo
echo "lldpd installed (receive-only). Neighbours appear in the dashboard's Neighbours view / /api/lldp"
echo "LLDP frames arrive roughly every 30s, so the table fills in shortly after a switch sends one."
