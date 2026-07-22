#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -r $1 ]]; then
  echo "Usage: sudo $0 path/to/targets.csv" >&2
  exit 2
fi
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run as root so Nmap TCP connect behavior is consistent." >&2
  exit 2
fi
command -v nmap >/dev/null || { echo "nmap is required" >&2; exit 2; }

read -r -p "Confirm every listed target is authorized for this check [type YES]: " confirmation
[[ $confirmation == YES ]] || { echo "Cancelled."; exit 1; }

printf 'timestamp,name,address,protocol,port,state\n'
while IFS=, read -r name address protocol port extra; do
  [[ -z ${name// } || $name == \#* ]] && continue
  if [[ -n ${extra:-} || ! $name =~ ^[A-Za-z0-9._-]+$ || ! $address =~ ^[A-Za-z0-9:._-]+$ || ! $port =~ ^[0-9]{1,5}$ ]]; then
    echo "Invalid row for target: $name" >&2; exit 2
  fi
  [[ $protocol == s7-tcp || $protocol == opcua-tcp || $protocol == tcp ]] || { echo "Unsupported protocol: $protocol" >&2; exit 2; }
  (( port >= 1 && port <= 65535 )) || { echo "Invalid port: $port" >&2; exit 2; }
  state=$(nmap -n -Pn -sT -T2 --max-retries 1 --host-timeout 10s -p "$port" -- "$address" -oG - 2>/dev/null | awk '/Ports:/ {split($0,a,"Ports: "); split(a[2],b,"/"); print b[2]}')
  printf '%s,%s,%s,%s,%s,%s\n' "$(date --iso-8601=seconds)" "$name" "$address" "$protocol" "$port" "${state:-unknown}"
  sleep 1
done < "$1"
