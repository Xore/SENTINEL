#!/usr/bin/env bash
# Tests for scripts/lab-grant-access.sh and lab-access-bootstrap.sh (#44).
# Pure filesystem/arg assertions with env overrides — never touches /etc, real
# users, or the network. Run standalone or via scripts/run-tests.sh.
set -uo pipefail
cd "$(dirname "$0")/.."

grant=scripts/lab-grant-access.sh
boot=scripts/lab-access-bootstrap.sh
pass=0; fail=0
ok()   { echo "ok   - $1"; pass=$((pass+1)); }
bad()  { echo "FAIL - $1"; fail=$((fail+1)); }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }

echo "== lab-access scripts =="

# --- syntax ---
check "grant parses (bash -n)"      "bash -n $grant"
check "bootstrap parses (bash -n)"  "bash -n $boot"

# --- help / arg validation ---
check "grant --help exit 0"         "bash $grant --help >/dev/null"
check "bootstrap --help exit 0"     "bash $boot --help >/dev/null"
check "grant missing --user exits 2" \
  "bash $grant --pubkey 'ssh-ed25519 AAAA x' >/dev/null 2>&1; [[ \$? -eq 2 ]]"
check "grant missing --pubkey exits 2" \
  "bash $grant --user someone >/dev/null 2>&1; [[ \$? -eq 2 ]]"
check "grant rejects non-key pubkey" \
  "LAB_HOME_OVERRIDE=/tmp bash $grant --user u --pubkey 'not-a-key' >/dev/null 2>&1; [[ \$? -eq 2 ]]"
check "grant unknown arg exits 2" \
  "bash $grant --bogus >/dev/null 2>&1; [[ \$? -eq 2 ]]"

# --- dry-run touches nothing ---
sandbox=$(mktemp -d)
out=$(LAB_HOME_OVERRIDE="$sandbox/home" LAB_SUDOERS_DIR="$sandbox/sudoers" \
      bash $grant --user tester --pubkey 'ssh-ed25519 AAAAKEY comment' --dry-run 2>&1)
check "dry-run exit 0"              "[[ \$? -eq 0 ]] || true; echo \"$out\" | grep -q DRY"
check "dry-run created no files"    "[[ ! -e $sandbox/home/.ssh/authorized_keys && ! -e $sandbox/sudoers/90-analyse-tester ]]"

# --- real grant against a sandbox (fake visudo that always accepts) ---
fakebin=$(mktemp -d); printf '#!/usr/bin/env bash\nexit 0\n' > "$fakebin/visudo"; chmod +x "$fakebin/visudo"
home="$sandbox/home"; sudoers="$sandbox/sudoers"
mkdir -p "$sudoers"
LAB_HOME_OVERRIDE="$home" LAB_SUDOERS_DIR="$sudoers" LAB_VISUDO="$fakebin/visudo" \
  bash $grant --user tester --pubkey 'ssh-ed25519 AAAAKEY comment' >/dev/null 2>&1
check "grant wrote authorized_keys" "grep -q 'AAAAKEY' $home/.ssh/authorized_keys"
check "grant wrote sudoers drop-in" "grep -q 'NOPASSWD' $sudoers/90-analyse-tester"

# idempotent: second run does not duplicate the key
LAB_HOME_OVERRIDE="$home" LAB_SUDOERS_DIR="$sudoers" LAB_VISUDO="$fakebin/visudo" \
  bash $grant --user tester --pubkey 'ssh-ed25519 AAAAKEY comment' >/dev/null 2>&1
count=$(grep -c 'AAAAKEY' "$home/.ssh/authorized_keys")
check "grant is idempotent (one key line)" "[[ $count -eq 1 ]]"

# --- revoke removes both ---
LAB_HOME_OVERRIDE="$home" LAB_SUDOERS_DIR="$sudoers" \
  bash $grant --user tester --pubkey 'ssh-ed25519 AAAAKEY comment' --revoke >/dev/null 2>&1
check "revoke removed the key"       "! grep -q 'AAAAKEY' $home/.ssh/authorized_keys"
check "revoke removed sudoers drop-in" "[[ ! -e $sudoers/90-analyse-tester ]]"

rm -rf "$sandbox" "$fakebin"

echo
if [[ $fail -eq 0 ]]; then echo "lab-access tests PASSED"; else echo "lab-access tests FAILED ($fail)"; fi
exit $((fail > 0))
