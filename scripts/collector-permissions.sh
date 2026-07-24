#!/usr/bin/env bash
# Reproducible permission/user setup for a Network Probe collector node.
#
# Keeping this in one auditable script (rather than ad-hoc commands) means the
# exact privileges a collector is granted are reviewable and repeatable. A
# collector is deliberately low-privilege: it only READS /sys/class/net and runs
# `ip` and `ping`, so it needs no capabilities beyond what a normal user has.
#
#   sudo ./collector-permissions.sh --apply [service_user]
#
# Idempotent: safe to re-run. Default service user is 'probe-collector'.
set -euo pipefail

if [[ ${1:-} != --apply ]]; then
  echo "Creates the collector service user and its config dir with correct perms."
  echo "Review this script, then run: sudo $0 --apply [service_user]" >&2
  exit 2
fi
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run with sudo." >&2; exit 2; }

service_user=${2:-probe-collector}
config_dir=/etc/network-probe
state_dir=/var/lib/network-probe-collector

# System account with no login shell and no home password - it only runs the
# agent under systemd.
if ! id "$service_user" >/dev/null 2>&1; then
  useradd --system --home-dir "$state_dir" --create-home --shell /usr/sbin/nologin "$service_user"
  echo "Created system user $service_user."
else
  echo "User $service_user already exists."
fi

install -d -o root -g "$service_user" -m 0750 "$config_dir"
install -d -o "$service_user" -g "$service_user" -m 0750 "$state_dir"

# The agent needs no extra groups or capabilities on Ubuntu: ping is granted
# CAP_NET_RAW via file capabilities system-wide, and reading /sys and running
# `ip` require no privilege. We deliberately grant nothing more.
echo "Permissions applied for collector user '$service_user'."
echo "  config dir: $config_dir (root:$service_user 0750)"
echo "  state dir : $state_dir ($service_user:$service_user 0750)"
