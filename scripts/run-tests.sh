#!/usr/bin/env bash
# Run the whole test suite: Go collector tests + Python backend tests.
# Run this after every change. Exits non-zero if anything fails.
#
#   ./scripts/run-tests.sh
#
# Picks up a local venv automatically (.venv/ on Windows or Linux layout);
# override the interpreter with PYTHON=/path/to/python.
set -uo pipefail
cd "$(dirname "$0")/.."
rc=0

echo "== Go collector tests =="
if command -v go >/dev/null; then
  ( cd collector && go vet ./... && go test ./... ) || rc=1
else
  echo "SKIP: no 'go' toolchain on PATH" >&2
fi

echo
echo "== Python backend tests =="
# Find an interpreter: explicit $PYTHON, then a repo venv, then system python.
py=${PYTHON:-}
if [[ -z $py ]]; then
  for cand in .venv/Scripts/python.exe .venv/bin/python venv/bin/python python3 python; do
    if [[ -x $cand ]] || command -v "$cand" >/dev/null 2>&1; then py=$cand; break; fi
  done
fi
if [[ -n $py ]]; then
  "$py" -W ignore::ResourceWarning -m unittest discover -s tests || rc=1
else
  echo "SKIP: no python interpreter found" >&2
fi

echo
echo "== Shell (setup.sh) tests =="
if [[ -f tests/test_setup_sh.sh ]]; then
  bash tests/test_setup_sh.sh || rc=1
else
  echo "SKIP: tests/test_setup_sh.sh not found" >&2
fi

echo
if [[ $rc -eq 0 ]]; then echo "ALL TESTS PASSED"; else echo "TESTS FAILED"; fi
exit $rc
