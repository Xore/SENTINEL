#!/usr/bin/env bash
# Suricata capture-adapter manager (root).
#
# Keeps the passive IDS bound to the right NIC(s) without manual babysitting.
# Suricata can capture on several interfaces at once (one af-packet block each),
# so this supports three modes:
#
#   auto   - follow the single best currently-up NIC (wired preferred).
#   all    - capture on EVERY currently-up NIC (multi-interface).
#   manual - capture on a chosen SET of NICs. NICs that are down right now
#            (prepared/unplugged) are simply waited on and added the moment they
#            come up; Suricata is never moved off the operator's choice.
#
# Settings persist in a JSON config that the dashboard can also write (so the
# whole thing is configurable from the website). The daemon re-reads the config
# every recheck cycle, so a change takes effect with no service restart.
#
# Subcommands:
#   once            evaluate config, reconfigure Suricata if needed, exit
#   daemon          loop `once`, sleeping recheck_seconds between passes
#   set <sel> [n]   write config + apply. sel = auto | all | csv of ifaces
#                   (e.g. "wlp2s0,enp0s31f6"); optional recheck n seconds
#   status          print the current resolved state as JSON (no root needed)
#   apply <if...>   low-level: bind Suricata to these NIC(s) now
#
# This is the ONLY component that reconfigures Suricata; the dashboard/monitor
# stay read-only. The desktop selector and the dashboard call `set` (via pkexec
# / the reconciler) - never Suricata directly.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CONFIG=${PROBE_IDS_ADAPTER_CONFIG:-/var/lib/network-probe/ids-adapter.json}
STATE_DIR=${PROBE_IDS_ADAPTER_STATE_DIR:-/run/network-probe-ids}
STATE="$STATE_DIR/state.json"
AFPACKET_TOOL=${PROBE_SURICATA_AFPACKET:-$HERE/suricata_afpacket.py}
SURICATA_DEFAULT=/etc/default/suricata
SURICATA_YAML=/etc/suricata/suricata.yaml
DEFAULT_RECHECK=60
MIN_RECHECK=10

die() { echo "ids-adapter-manager: $*" >&2; exit 1; }
need_root() { [[ ${EUID:-$(id -u)} -eq 0 ]] || die "must run as root (try: sudo $0 $*)"; }

# --- config ----------------------------------------------------------------
# Emit: mode|iface_csv|recheck   (pipe, not tab: a whitespace IFS would collapse
# an empty middle field). iface_csv is the chosen set for manual mode.
read_cfg() {
  python3 - "$CONFIG" "$DEFAULT_RECHECK" "$MIN_RECHECK" <<'PY'
import json, sys
path, default_recheck, min_recheck = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
try:
    cfg = json.load(open(path))
    if not isinstance(cfg, dict):
        cfg = {}
except (OSError, ValueError):
    cfg = {}
mode = cfg.get("mode")
mode = mode if mode in ("auto", "all", "manual") else "auto"
# New schema: interfaces[]. Legacy: interface "" (single string).
ifaces = cfg.get("interfaces")
if not isinstance(ifaces, list):
    one = str(cfg.get("interface") or "").strip()
    ifaces = [one] if one else []
ifaces = [str(x).strip() for x in ifaces if str(x).strip()]
try:
    recheck = int(cfg.get("recheck_seconds", default_recheck))
except (TypeError, ValueError):
    recheck = default_recheck
recheck = max(min_recheck, min(recheck, 86400))
print(f"{mode}|{','.join(ifaces)}|{recheck}")
PY
}

write_cfg() {  # mode  iface_csv  recheck
  local dir; dir=$(dirname "$CONFIG")
  mkdir -p "$dir"
  python3 - "$CONFIG" "$1" "$2" "$3" <<'PY'
import json, os, sys, tempfile
path, mode, csv, recheck = sys.argv[1:5]
ifaces = [x for x in csv.split(",") if x]
data = {"mode": mode, "interfaces": ifaces, "recheck_seconds": int(recheck)}
d = os.path.dirname(path)
fd, tmp = tempfile.mkstemp(dir=d, prefix=".ids-adapter-")
with os.fdopen(fd, "w") as fh:
    json.dump(data, fh, indent=2); fh.write("\n")
os.chmod(tmp, 0o644)     # no secrets; dashboard + desktop selector read it
os.replace(tmp, path)
PY
}

# --- interfaces -------------------------------------------------------------
list_ifaces() {
  local n
  for n in /sys/class/net/*; do
    n=$(basename "$n")
    case $n in lo|veth*|docker*|br-*|virbr*|vnet*) continue;; esac
    [[ -e /sys/class/net/$n/device || $n == wl* || $n == en* || $n == eth* ]] || continue
    echo "$n"
  done
}

# Usable = link operationally up (has carrier). A "prepared but unplugged" NIC
# is admin-up but operstate down -> not usable yet.
iface_usable() {
  local n=$1 op
  [[ -e /sys/class/net/$n ]] || return 1
  op=$(cat "/sys/class/net/$n/operstate" 2>/dev/null || echo unknown)
  [[ $op == up ]] && return 0
  [[ $op == unknown && $(cat "/sys/class/net/$n/carrier" 2>/dev/null || echo 0) == 1 ]]
}

is_wired() { [[ $1 == en* || $1 == eth* ]]; }

# Best single up NIC: first usable wired, else first usable wireless.
pick_auto() {
  local n
  for n in $(list_ifaces); do is_wired "$n" && iface_usable "$n" && { echo "$n"; return; }; done
  for n in $(list_ifaces); do is_wired "$n" || { iface_usable "$n" && { echo "$n"; return; }; }; done
}

# Interfaces Suricata is currently configured to capture on (af-packet blocks,
# excluding the `default` catch-all), space-separated. Scoped to the af-packet
# section ONLY - the yaml also has `- interface:` lines under pcap/netmap/dpdk,
# and counting those would make the idempotency check never match, restarting
# Suricata every cycle.
current_ifaces() {
  [[ -r $SURICATA_YAML ]] || return 0
  awk '
    /^af-packet:[[:space:]]*$/ { inaf=1; next }
    inaf && /^[^[:space:]#]/   { inaf=0 }
    inaf && match($0, /^[[:space:]]*-[[:space:]]*interface:[[:space:]]*/) {
      v = substr($0, RLENGTH + 1); sub(/[[:space:]#].*$/, "", v)
      if (v != "" && v != "default") print v
    }
  ' "$SURICATA_YAML" | tr '\n' ' '
}

# --- apply ------------------------------------------------------------------
# Reconfigure Suricata to capture on exactly the given NIC(s). Idempotent, and
# safe: backs up the yaml, validates, and rolls the yaml back if the test fails.
apply_ifaces() {  # <iface...>
  local want=("$@")
  ((${#want[@]})) || { echo "apply: no interfaces given" >&2; return 1; }
  local w
  for w in "${want[@]}"; do [[ -e /sys/class/net/$w ]] || { echo "apply: no such interface '$w'" >&2; return 1; }; done

  # Already capturing exactly this set and running? Nothing to do.
  local cur; cur=$(current_ifaces)
  local want_sorted cur_sorted
  want_sorted=$(printf '%s\n' "${want[@]}" | sort | tr '\n' ' ')
  cur_sorted=$(printf '%s\n' $cur | sort | tr '\n' ' ')
  if [[ $want_sorted == "$cur_sorted" ]] && systemctl is-active --quiet suricata; then
    return 0
  fi

  local backup="${SURICATA_YAML}.probe-bak"
  cp -f "$SURICATA_YAML" "$backup"
  if ! python3 "$AFPACKET_TOOL" "$SURICATA_YAML" "${want[@]}"; then
    cp -f "$backup" "$SURICATA_YAML"; echo "apply: yaml rewrite failed; restored" >&2; return 1
  fi
  # Keep the pcap-mode IFACE line in sync with the first interface (cosmetic).
  if [[ -f $SURICATA_DEFAULT ]]; then
    if grep -q '^IFACE=' "$SURICATA_DEFAULT"; then sed -i "s/^IFACE=.*/IFACE=${want[0]}/" "$SURICATA_DEFAULT"
    else echo "IFACE=${want[0]}" >> "$SURICATA_DEFAULT"; fi
  fi
  if ! suricata -T -c "$SURICATA_YAML" >/dev/null 2>&1; then
    cp -f "$backup" "$SURICATA_YAML"; echo "apply: suricata config test failed; restored" >&2; return 1
  fi
  systemctl restart suricata
  echo "apply: Suricata now capturing on ${want[*]}"
}

# --- state ------------------------------------------------------------------
json_array() { local out="" x; for x in "$@"; do out+="\"$x\","; done; echo "[${out%,}]"; }

write_state() {  # mode  configured_csv  recheck  resolved_csv  active_csv  note
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  local ifjson="" n
  for n in $(list_ifaces); do
    local up=false; iface_usable "$n" && up=true
    ifjson+="{\"name\":\"$n\",\"up\":$up,\"wired\":$(is_wired "$n" && echo true || echo false)},"
  done
  local resolved active configured
  IFS=',' read -ra _r <<< "$4"; resolved=$(json_array "${_r[@]}")
  IFS=',' read -ra _a <<< "$5"; active=$(json_array "${_a[@]}")
  IFS=',' read -ra _c <<< "$2"; configured=$(json_array "${_c[@]}")
  cat > "$STATE" 2>/dev/null <<JSON || true
{
  "mode": "$1",
  "configured_interfaces": $configured,
  "recheck_seconds": $3,
  "resolved_interfaces": $resolved,
  "active_interfaces": $active,
  "suricata_active": $(systemctl is-active --quiet suricata && echo true || echo false),
  "note": "$6",
  "interfaces": [${ifjson%,}],
  "updated": $(date +%s)
}
JSON
  chmod 0644 "$STATE" 2>/dev/null || true
}

# --- evaluate ---------------------------------------------------------------
once() {
  local mode csv recheck; IFS='|' read -r mode csv recheck < <(read_cfg)
  local -a chosen=(); [[ -n $csv ]] && IFS=',' read -ra chosen <<< "$csv"
  local -a target=(); local note active
  active=$(current_ifaces); active=${active% }

  if [[ $mode == all ]]; then
    local n; for n in $(list_ifaces); do iface_usable "$n" && target+=("$n"); done
    note=$( ((${#target[@]})) && echo "all: capturing on ${target[*]}" || echo "all: no interface is up; left on ${active:-none}" )
  elif [[ $mode == manual ]]; then
    local down=() n
    for n in "${chosen[@]}"; do if iface_usable "$n"; then target+=("$n"); else down+=("$n"); fi; done
    if ((${#target[@]})); then
      note="manual: capturing on ${target[*]}"; ((${#down[@]})) && note+="; waiting on ${down[*]} (down)"
    else
      note="manual: chosen NIC(s) ${chosen[*]:-none} down; waiting, left on ${active:-none}"
    fi
  else
    local best; best=$(pick_auto)
    [[ -n $best ]] && target=("$best")
    note=$( [[ -n $best ]] && echo "auto: best up interface is $best" || echo "auto: no interface is up; left on ${active:-none}" )
  fi

  if ((${#target[@]})); then
    local tset cset
    tset=$(printf '%s\n' "${target[@]}" | sort | tr '\n' ' ')
    cset=$(printf '%s\n' $active | sort | tr '\n' ' ')
    if [[ $tset != "$cset" ]] || ! systemctl is-active --quiet suricata; then
      if apply_ifaces "${target[@]}"; then active="${target[*]}"; note="switched to ${target[*]}"; fi
    fi
  fi

  local resolved_csv; resolved_csv=$(IFS=,; echo "${target[*]}")
  local active_csv; active_csv=$(echo "$active" | tr ' ' ',')
  write_state "$mode" "$csv" "$recheck" "$resolved_csv" "$active_csv" "$note"
  echo "$note"
}

# Poll cadence: the daemon wakes every TICK seconds and re-reads the config, but
# only runs a full evaluation when either (a) the config changed since the last
# tick - so a web/desktop edit applies within ~TICK seconds instead of waiting
# out the old recheck - or (b) recheck_seconds have elapsed, which is what makes
# a pinned-but-down NIC get bound the moment it comes up.
DAEMON_TICK=${PROBE_IDS_DAEMON_TICK:-5}

daemon() {
  echo "ids-adapter-manager: daemon started (config: $CONFIG, tick: ${DAEMON_TICK}s)"
  local last_sig="" last_eval=0
  while true; do
    local cfg sig recheck now
    cfg=$(read_cfg); sig=$cfg
    recheck=$(printf '%s' "$cfg" | cut -d'|' -f3); recheck=${recheck:-$DEFAULT_RECHECK}
    now=$(date +%s)
    if [[ $sig != "$last_sig" ]] || (( now - last_eval >= recheck )); then
      once || true
      last_sig=$sig; last_eval=$now
    fi
    sleep "$DAEMON_TICK"
  done
}

# --- CLI --------------------------------------------------------------------
cmd=${1:-status}
case $cmd in
  once)   need_root once; once ;;
  daemon) need_root daemon; daemon ;;
  status)
    if [[ -r $STATE ]]; then cat "$STATE"
    elif [[ ${EUID:-$(id -u)} -eq 0 ]]; then once >/dev/null 2>&1; cat "$STATE" 2>/dev/null || echo '{"status":"unknown"}'
    else echo '{"status":"unknown","note":"no state yet; the adapter daemon may not be running"}'; fi
    ;;
  apply)
    need_root "apply ${*:2}"
    shift; [[ $# -ge 1 ]] || die "usage: $0 apply <iface...>"
    apply_ifaces "$@"
    ;;
  set)
    need_root "set ${2:-} ${3:-}"
    sel=${2:-} ; recheck=${3:-}
    [[ -n $sel ]] || die "usage: $0 set <auto|all|iface[,iface...]> [recheck_seconds]"
    IFS='|' read -r _m _c crecheck < <(read_cfg)
    [[ -n $recheck ]] || recheck=$crecheck
    case $sel in
      auto) write_cfg auto "" "$recheck" ;;
      all)  write_cfg all  "" "$recheck" ;;
      *)
        csv=${sel//[[:space:]]/}
        IFS=',' read -ra picks <<< "$csv"
        for p in "${picks[@]}"; do [[ -e /sys/class/net/$p ]] || die "no such interface '$p'"; done
        write_cfg manual "$csv" "$recheck" ;;
    esac
    once
    ;;
  *) die "unknown subcommand '$cmd' (once|daemon|set|status|apply)" ;;
esac
