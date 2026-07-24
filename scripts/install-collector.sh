#!/usr/bin/env bash
# Install a Network Probe *collector* node: the slim push-agent only (no local
# dashboard/backend). It gathers passive signals and pushes them to a standalone
# aggregator you have already enrolled this collector on.
#
#   sudo AGGREGATOR_URL=http://192.168.50.32:8088 \
#        INGEST_KEY=<key shown once at enrollment> \
#        [COLLECTOR_ID=col-abcd1234] [INTERVAL=30] [VERIFY_TLS=true] \
#        ./install-collector.sh --apply
#
# Re-running is safe (idempotent): it rewrites the config + unit and restarts.
set -euo pipefail

if [[ ${1:-} != --apply ]]; then
  echo "Installs the collector agent + systemd unit and points it at an aggregator."
  echo "Review this script, then run with the env vars above: sudo $0 --apply" >&2
  exit 2
fi
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run with sudo." >&2; exit 2; }
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || {
  echo "Supported target is Ubuntu 24.04 LTS; found ${PRETTY_NAME:-unknown}." >&2; exit 2; }

: "${AGGREGATOR_URL:?set AGGREGATOR_URL=http://<aggregator-ip>:8088}"
: "${INGEST_KEY:?set INGEST_KEY=<the key shown once when you enrolled this collector>}"
# The signing secret authorizes self-updates. Optional (updates just stay disabled
# without it), but the enrollment output includes it - paste it to allow remote
# binary pushes to this collector.
UPDATE_SECRET=${UPDATE_SECRET:-}
INTERVAL=${INTERVAL:-30}
PING_INTERVAL=${PING_INTERVAL:-10}
VERIFY_TLS=${VERIFY_TLS:-true}

repo_dir=$(readlink -f "$(dirname "$0")/..")
service_user=probe-collector
config_dir=/etc/network-probe
state_dir=/var/lib/network-probe-collector
# The binary lives in the service user's own state dir, not a system path,
# because the agent self-updates by swapping this file in place. That means the
# dir must be writable by the agent - a deliberate trade for remote updates.
bin_dir=$state_dir/bin
binary=$bin_dir/collector

# The collector is a single Go binary (stdlib only, no runtime to install). Pick
# the prebuilt one that matches this machine's architecture; if it is missing but
# a Go toolchain is present, build it on the spot.
case "$(uname -m)" in
  x86_64)  goarch=amd64 ;;
  aarch64) goarch=arm64 ;;
  *) echo "unsupported CPU arch $(uname -m)" >&2; exit 2 ;;
esac
prebuilt=$repo_dir/collector/dist/collector-linux-$goarch
if [[ ! -f $prebuilt ]]; then
  if command -v go >/dev/null; then
    echo "No prebuilt binary for linux/$goarch; building with local Go toolchain."
    ( cd "$repo_dir/collector" && GOOS=linux GOARCH=$goarch CGO_ENABLED=0 \
        go build -trimpath -ldflags "-s -w" -o "$prebuilt" . )
  else
    echo "Missing $prebuilt and no 'go' toolchain to build it." >&2
    echo "Run scripts/build-collector.sh on a machine with Go, then re-run." >&2
    exit 2
  fi
fi

# iproute2 (ip) + iputils-ping are base on Ubuntu; ensure them anyway. The binary
# is self-contained, so there is no venv and nothing to pip install.
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq iproute2 iputils-ping >/dev/null

# Reproducible permissions/user setup lives in one script so it is auditable.
"$repo_dir/scripts/collector-permissions.sh" --apply "$service_user"

# Owned by the service user so the agent can replace it during self-update.
install -d -o "$service_user" -g "$service_user" -m 0750 "$bin_dir"
install -o "$service_user" -g "$service_user" -m 0755 "$prebuilt" "$binary"
echo "Installed collector binary at $binary."

umask 077
config_file=$config_dir/collector.json
cat > "$config_file" <<EOF
{
  "aggregator_url": "${AGGREGATOR_URL%/}",
  ${COLLECTOR_ID:+\"collector_id\": \"$COLLECTOR_ID\",}
  "ingest_key": "$INGEST_KEY",
  ${UPDATE_SECRET:+\"update_secret\": \"$UPDATE_SECRET\",}
  "interval": $INTERVAL,
  "ping_interval": $PING_INTERVAL,
  "verify_tls": $VERIFY_TLS
}
EOF
umask 022
chown root:"$service_user" "$config_file"
chmod 640 "$config_file"
echo "Wrote $config_file (key is readable only by root:$service_user)."

unit=/etc/systemd/system/network-probe-collector.service
cat > "$unit" <<EOF
[Unit]
Description=Network Probe Collector Agent
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=$service_user
Group=$service_user
Environment=PROBE_COLLECTOR_CONFIG=$config_file
ExecStart=$binary
# Restart on ANY exit: self-update falls back to exiting so systemd relaunches
# into the freshly swapped binary (the normal path re-execs and never exits).
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$state_dir
ReadOnlyPaths=$config_dir
[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$unit"
systemctl daemon-reload
systemctl enable network-probe-collector.service
systemctl restart network-probe-collector.service
sleep 2
systemctl --no-pager --full status network-probe-collector.service || true
echo
echo "Collector installed. It is now pushing to ${AGGREGATOR_URL%/}."
echo "Follow it with:  journalctl -u network-probe-collector -f"
