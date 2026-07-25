#!/usr/bin/env bash
# Bootstrap passwordless SSH + sudo access to a lab box, from your workstation.
# One command, idempotent, re-runnable:
#
#   ./lab-access-bootstrap.sh --host 192.168.50.33
#   ./lab-access-bootstrap.sh --host 192.168.50.33 --user adminuser --key ~/.ssh/analyse_lab
#
# It, in order:
#   1. ensures an ed25519 keypair exists at --key (generates one, no passphrase,
#      if absent — this is the identity you log in with);
#   2. checks whether key login already works (BatchMode, no prompt);
#   3. if not, runs ssh-copy-id so the PUBLIC key is installed — this is the ONE
#      step that asks for the box's password, and YOU type it, interactively;
#   4. runs scripts/lab-grant-access.sh on the box (over ssh, under sudo) to make
#      the key install idempotent and add a NOPASSWD sudo drop-in;
#   5. verifies key login + passwordless sudo now work.
#
# For TRUSTED lab machines you own. Do not point it at production hosts.
set -euo pipefail
cd "$(dirname "$0")/.."

host=""
user="adminuser"
key="$HOME/.ssh/analyse_lab"
grant_script="scripts/lab-grant-access.sh"

die() { echo "$*" >&2; exit 2; }
usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case $1 in
    --host) host=${2:-}; shift 2 ;;
    --user) user=${2:-}; shift 2 ;;
    --key) key=${2:-}; shift 2 ;;
    --grant-script) grant_script=${2:-}; shift 2 ;;
    -h|--help) usage 0 ;;
    *) die "Unknown argument: $1 (try --help)" ;;
  esac
done
[[ -n $host ]] || die "Missing --host."
[[ -f $grant_script ]] || die "Grant script not found: $grant_script"

# 1. Ensure the keypair exists.
if [[ ! -f $key ]]; then
  echo "== Generating keypair at $key"
  ssh-keygen -t ed25519 -N "" -C "analyse-lab@$(hostname)" -f "$key"
fi
[[ -f $key.pub ]] || die "Public key $key.pub missing (regenerate the keypair)."
pubkey=$(tr -d '\r\n' < "$key.pub")

ssh_key() { ssh -i "$key" -o IdentitiesOnly=yes -o ConnectTimeout=8 "$@"; }

# 2. Does key login already work?
if ssh_key -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$user@$host" true 2>/dev/null; then
  echo "== Key login already works for $user@$host"
else
  # 3. Install the public key. THIS prompts for the box password — you type it.
  echo "== Installing public key via ssh-copy-id (you'll be asked for $user@$host's password)"
  ssh-copy-id -i "$key.pub" -o StrictHostKeyChecking=accept-new "$user@$host" \
    || die "ssh-copy-id failed. Install $key.pub into $user@$host:~/.ssh/authorized_keys manually, then re-run."
fi

# 4. Make it idempotent + add NOPASSWD sudo by running the grant script remotely.
#    Piped over stdin so nothing needs to pre-exist on the box.
echo "== Applying grant script on $host (key install + NOPASSWD sudo)"
ssh_key "$user@$host" "sudo bash -s -- --user '$user' --pubkey '$pubkey'" < "$grant_script"

# 5. Verify.
echo "== Verifying"
if ssh_key -o BatchMode=yes "$user@$host" 'sudo -n true' 2>/dev/null; then
  echo "OK: key login + passwordless sudo confirmed for $user@$host"
  echo "   log in with:  ssh -i $key $user@$host"
else
  die "Verification failed: passwordless sudo not working for $user@$host."
fi
