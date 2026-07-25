#!/usr/bin/env bash
# Grant (or revoke) key-based SSH + passwordless sudo for a login user on a lab
# box. Runs ON the lab machine under sudo. Idempotent: safe to re-run.
#
#   sudo ./lab-grant-access.sh --user adminuser --pubkey "ssh-ed25519 AAAA... comment"
#   ssh-add -L | sudo ./lab-grant-access.sh --user adminuser --pubkey -   # from stdin
#   sudo ./lab-grant-access.sh --user adminuser --revoke                  # undo both
#   ./lab-grant-access.sh --user adminuser --pubkey "..." --dry-run       # preview
#
# What "grant" does, both idempotently:
#   1. installs the public key into ~USER/.ssh/authorized_keys (0700 dir, 0600
#      file, owned by USER) — de-duped, never clobbers other keys;
#   2. writes a validated /etc/sudoers.d/ drop-in giving USER NOPASSWD sudo.
#
# The private key never touches the lab box — only the public key is installed.
# This is for TRUSTED lab machines you own; NOPASSWD sudo is a deliberate
# convenience, not something to do on production hosts.
set -euo pipefail

# Overridable for tests so the suite never touches the real system.
sudoers_dir=${LAB_SUDOERS_DIR:-/etc/sudoers.d}
home_override=${LAB_HOME_OVERRIDE:-}          # if set, used verbatim as USER's home
visudo_bin=${LAB_VISUDO:-visudo}

user=""
pubkey=""
revoke=0
dry_run=0

die() { echo "$*" >&2; exit 2; }

usage() {
  sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --user) user=${2:-}; shift 2 ;;
    --pubkey) pubkey=${2:-}; shift 2 ;;
    --revoke) revoke=1; shift ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage 0 ;;
    *) die "Unknown argument: $1 (try --help)" ;;
  esac
done

[[ -n $user ]] || die "Missing --user."
if [[ $revoke -eq 0 ]]; then
  [[ -n $pubkey ]] || die "Missing --pubkey (or use --revoke)."
  if [[ $pubkey == - ]]; then pubkey=$(cat); fi
  pubkey=$(printf '%s' "$pubkey" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
  [[ $pubkey == ssh-* || $pubkey == ecdsa-* || $pubkey == sk-* ]] || die "That does not look like an SSH public key."
fi

# Resolve the user's home. LAB_HOME_OVERRIDE short-circuits getent for tests.
if [[ -n $home_override ]]; then
  home=$home_override
else
  home=$(getent passwd "$user" | cut -d: -f6)
  [[ -n $home ]] || die "No such user: $user"
fi
ssh_dir=$home/.ssh
auth_keys=$ssh_dir/authorized_keys
sudoers_file=$sudoers_dir/90-analyse-$user

run() {  # echo in dry-run, execute otherwise
  if [[ $dry_run -eq 1 ]]; then echo "DRY: $*"; else "$@"; fi
}

# Own a path as $user, but only when that account actually exists (it always
# does on a real lab box; in the test sandbox it doesn't, so we skip chown and
# still create the files).
own() { if id "$user" >/dev/null 2>&1; then run chown "$user:$user" "$@"; fi; }

# chmod that warns instead of aborting — some test filesystems (MSYS) can't set
# POSIX modes; a real Ubuntu lab box always can.
setmode() { chmod "$1" "$2" 2>/dev/null || echo "  (warn: could not chmod $1 $2)"; }

grant() {
  echo "Granting key + NOPASSWD sudo to '$user' (home: $home)"
  run mkdir -p "$ssh_dir"
  [[ $dry_run -eq 0 ]] && setmode 0700 "$ssh_dir"
  own "$ssh_dir"
  if [[ $dry_run -eq 0 ]]; then
    touch "$auth_keys"
    if grep -qxF "$pubkey" "$auth_keys" 2>/dev/null; then
      echo "  key already present in $auth_keys"
    else
      printf '%s\n' "$pubkey" >> "$auth_keys"
      echo "  key appended to $auth_keys"
    fi
    own "$auth_keys"
    setmode 0600 "$auth_keys"
  else
    echo "DRY: append key to $auth_keys (if absent); chown $user; chmod 0600"
  fi

  # sudoers drop-in — validate a temp copy with visudo before installing, so a
  # bad file can never lock sudo out.
  local line="$user ALL=(ALL) NOPASSWD:ALL"
  if [[ $dry_run -eq 1 ]]; then
    echo "DRY: write '$line' to $sudoers_file (0440 root:root, visudo-checked)"
  else
    local tmp; tmp=$(mktemp)
    printf '%s\n' "$line" > "$tmp"
    if "$visudo_bin" -cf "$tmp" >/dev/null; then
      cp "$tmp" "$sudoers_file"
      setmode 0440 "$sudoers_file"
      if id root >/dev/null 2>&1; then chown root:root "$sudoers_file" 2>/dev/null || true; fi
      echo "  installed $sudoers_file"
    else
      rm -f "$tmp"; die "visudo rejected the generated sudoers line; aborting."
    fi
    rm -f "$tmp"
  fi
}

revoke_access() {
  echo "Revoking key + NOPASSWD sudo for '$user'"
  if [[ -f $auth_keys ]]; then
    if [[ -n $pubkey ]]; then
      run sed -i "\#$(printf '%s' "$pubkey" | sed 's/[#&/]/\\&/g')#d" "$auth_keys"
      echo "  removed matching key from $auth_keys"
    else
      echo "  (no --pubkey given: left authorized_keys untouched, removed only sudoers)"
    fi
  fi
  if [[ -f $sudoers_file ]]; then
    run rm -f "$sudoers_file"
    echo "  removed $sudoers_file"
  else
    echo "  $sudoers_file not present"
  fi
}

if [[ $revoke -eq 1 ]]; then revoke_access; else grant; fi
echo "Done."
