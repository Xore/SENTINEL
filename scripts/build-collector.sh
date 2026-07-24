#!/usr/bin/env bash
# Cross-compile the Go collector agent into single static binaries.
#
# The collector is the ONLY component written in Go, precisely so it can ship as
# a dependency-free binary to whatever a customer runs - Linux boxes and Windows
# hosts alike. Run this on any machine with a Go toolchain; it writes into
# collector/dist/ and touches nothing else.
#
#   ./build-collector.sh              # build linux/amd64 + windows/amd64
#   ./build-collector.sh linux/arm64  # build only the targets you pass
set -euo pipefail

repo_dir=$(readlink -f "$(dirname "$0")/..")
src_dir=$repo_dir/collector
out_dir=$src_dir/dist
mkdir -p "$out_dir"

targets=("$@")
[[ ${#targets[@]} -eq 0 ]] && targets=(linux/amd64 windows/amd64)

version=$(grep -oE 'version = "[^"]+"' "$src_dir/main.go" | head -1 | cut -d'"' -f2)
echo "Building network-probe-collector v${version:-?}"

entries=()
for t in "${targets[@]}"; do
  os=${t%/*}; arch=${t#*/}
  ext=""; [[ $os == windows ]] && ext=.exe
  fname="collector-$os-$arch$ext"
  out="$out_dir/$fname"
  echo "  -> $out"
  ( cd "$src_dir" && GOOS="$os" GOARCH="$arch" CGO_ENABLED=0 \
      go build -trimpath -ldflags "-s -w" -o "$out" . )
  entries+=("\"$os/$arch\": \"$fname\"")
done

# Manifest the aggregator reads to know which version/binaries it can hand out
# to collectors for self-update (see dashboard _collector_release()).
{
  echo "{"
  echo "  \"version\": \"${version:-0.0.0}\","
  echo "  \"files\": {"
  for i in "${!entries[@]}"; do
    sep=","; [[ $i -eq $((${#entries[@]} - 1)) ]] && sep=""
    echo "    ${entries[$i]}$sep"
  done
  echo "  }"
  echo "}"
} > "$out_dir/manifest.json"
echo "Done. Binaries + manifest.json in $out_dir"
