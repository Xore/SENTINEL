#!/usr/bin/env bash
# Tests for scripts/setup.sh - the unified installer orchestrator. Pure dry-run /
# argument-parsing checks: they must never touch the system or need root.
set -uo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
setup="$here/../scripts/setup.sh"
fails=0

check() { # desc, expected-exit, actual-exit
  if [[ $2 -eq $3 ]]; then echo "ok   - $1"; else echo "FAIL - $1 (want exit $2, got $3)"; fails=$((fails+1)); fi
}
contains() { # desc, needle, haystack
  if [[ $3 == *"$2"* ]]; then echo "ok   - $1"; else echo "FAIL - $1 (missing: $2)"; fails=$((fails+1)); fi
}
missing() { # desc, needle, haystack
  if [[ $3 != *"$2"* ]]; then echo "ok   - $1"; else echo "FAIL - $1 (should not contain: $2)"; fails=$((fails+1)); fi
}

echo "== setup.sh =="
bash -n "$setup"; check "parses (bash -n)" 0 $?

out=$(bash "$setup" --help); check "--help exit 0" 0 $?
contains "--help mentions collector role" "--collector" "$out"

out=$(bash "$setup" --list); check "--list exit 0" 0 $?
contains "--list shows dashboard" "dashboard" "$out"
contains "--list shows collector" "collector" "$out"

# standalone dry-run: ordered plan, dashboard before monitor, no IDS
out=$(bash "$setup" --standalone --dry-run); check "standalone dry-run exit 0" 0 $?
contains "standalone includes dashboard" "install-dashboard-service.sh" "$out"
missing  "standalone excludes IDS" "install-ids.sh" "$out"

# ordering: even if IDS is asked before dashboard, dashboard is planned first
plan=$(bash "$setup" --component ids --component dashboard --dry-run | grep -E '^\s+- ' | awk '{print $2}' | tr '\n' ' ')
contains "dashboard ordered before ids" "dashboard ids " "$plan"

# unknown component rejected
bash "$setup" --component nope --dry-run >/dev/null 2>&1; check "unknown component exits 2" 2 $?

# apply without a role/component and no TTY must fail cleanly (not hang)
bash "$setup" --apply </dev/null >/dev/null 2>&1; check "no selection + no TTY exits 2" 2 $?

# collector dry-run must NOT require AGGREGATOR_URL/INGEST_KEY (only apply does)
( unset AGGREGATOR_URL INGEST_KEY; bash "$setup" --collector --dry-run >/dev/null 2>&1 ); check "collector dry-run needs no env" 0 $?

echo
if [[ $fails -eq 0 ]]; then echo "setup.sh tests PASSED"; else echo "setup.sh tests FAILED ($fails)"; fi
exit $(( fails > 0 ? 1 : 0 ))
