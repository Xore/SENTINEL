#!/usr/bin/env bash
# Writes a fresh dashboard access token, invalidating the previous one.
#
# Wired as a systemd ExecStartPre=+ hook (runs as root) so every dashboard
# (re)start rotates the token: any browser still holding the old token is
# deauthenticated and must sign in again with the new one. Retrieve it with:
#   sudo cat /etc/network-probe/dashboard-token
#
# Only rotates when the token file already exists (i.e. LAN exposure with auth
# is configured); a loopback-only install with no token file is left untouched.
set -euo pipefail

token_file=${1:-/etc/network-probe/dashboard-token}
service_group=${2:-probe-dashboard}

[[ -f $token_file ]] || exit 0   # no token configured -> nothing to rotate

umask 077
new=$(openssl rand -hex 16)
printf '%s\n' "$new" > "$token_file"
chgrp "$service_group" "$token_file" 2>/dev/null || true
chmod 0640 "$token_file"
echo "Rotated dashboard access token (previous sessions deauthenticated)."
