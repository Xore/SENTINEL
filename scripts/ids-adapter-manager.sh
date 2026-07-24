#!/usr/bin/env bash
# Suricata capture-adapter manager (root).
#
# Keeps the passive IDS bound to a usable NIC without manual babysitting:
#
#   auto   - follow the best currently-up interface (wired preferred, then
#            wireless). If the active NIC goes down and another is up, switch.
#   manual - stick to ONE chosen NIC. If that NIC is down right now (e.g. cable
#            not plugged in yet but prepared), do NOT switch away - just keep
#            re-checking every `recheck_seconds` and bind Suricata the moment it
#            comes up. Suricata is never moved off the operator's choice.
#
# Settings persist in a JSON config so a reboot keeps the same behaviour. The
# daemon subcommand re-reads that config every cycle, so a change made by the
# desktop selector takes effect on the next recheck with no service restart.
#
# Subcommands:
#   once           evaluate config, switch Suricata if needed, exit
#   daemon         loop `once` forever, sleeping recheck_seconds between passes
#   set <sel> [n]  write config (sel = auto | <iface>), optional recheck n secs,
#                  then apply once
#   status         print the current resolved state as JSON
#   apply <iface>  low-level: bind Suricata to <iface> now (validate + restart)
#
# This is the ONLY component that reconfigures Suricata; the dashboard/monitor
# stay read-only. Run as root (the desktop selector calls it via pkexec).
set -uo pipefail

CONFIG=${PROBE_IDS_ADAPTER_CONFIG:-/etc/network-probe/ids-adapter.json}
STATE_DIR=${PROBE_IDS_ADAPTER_STATE_DIR:-/run/network-probe-ids}
STATE="$STATE_DIR/state.json"
SURICATA_DEFAULT=/etc/default/suricata
SURICATA_YAML=/etc/suricata/suricata.yaml
DEFAULT_RECHECK=60
MIN_RECHECK=10

die() { echo "ids-adapter-manager: $*" >&2; exit 1; }
# `status` only reads a world-readable state file, so it needs no privilege;
# the mutating subcommands (once/daemon/set/apply) check for root themselves.
need_root() { [[ ${EUID:-$(id -u)} -eq 0 ]] || die "must run as root (try: sudo $0 $*)"; }

# --- config ----------------------------------------------------------------
# Emit: mode|interface|recheck   (defaults applied for a missing file). A pipe,
# not a tab: with a whitespace IFS `read` collapses an empty middle field (the
# empty interface in auto mode), which would shift recheck into interface.
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
mode = "manual" if mode == "manual" else "auto"
iface = str(cfg.get("interface") or "").strip()
try:
    recheck = int(cfg.get("recheck_seconds", default_recheck))
except (TypeError, ValueError):
    recheck = default_recheck
recheck = max(min_recheck, min(recheck, 86400))
print(f"{mode}|{iface}|{recheck}")
PY
}

write_cfg() {  # mode interface recheck
  local dir; dir=$(dirname "$CONFIG")
  mkdir -p "$dir"
  python3 - "$CONFIG" "$1" "$2" "$3" <<'PY'
import json, os, sys, tempfile
path, mode, iface, recheck = sys.argv[1:5]
data = {"mode": mode, "interface": iface, "recheck_seconds": int(recheck)}
d = os.path.dirname(path)
fd, tmp = tempfile.mkstemp(dir=d, prefix=".ids-adapter-")
with os.fdopen(fd, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
os.chmod(tmp, 0o644)          # no secrets; the desktop selector reads it
os.replace(tmp, path)
PY
}

# --- interfaces -------------------------------------------------------------
# All real NICs (skip loopback and virtual bridges/veth/docker).
list_ifaces() {
  local n
  for n in /sys/class/net/*; do
    n=$(basename "$n")
    case $n in lo|veth*|docker*|br-*|virbr*|vnet*) continue;; esac
    [[ -e /sys/class/net/$n/device || $n == wl* || $n == en* || $n == eth* ]] || continue
    echo "$n"
  done
}

# A NIC is usable for capture when the kernel reports the link operationally up
# (operstate=up), i.e. it has carrier. A "prepared but unplugged" NIC is
# administratively up but operstate=down/lowerlayerdown -> not usable yet.
iface_usable() {
  local n=$1 op
  [[ -e /sys/class/net/$n ]] || return 1
  op=$(cat "/sys/class/net/$n/operstate" 2>/dev/null || echo unknown)
  [[ $op == up ]] && return 0
  # Some drivers report "unknown" while carrying (common on wlan); trust carrier.
  [[ $op == unknown && $(cat "/sys/class/net/$n/carrier" 2>/dev/null || echo 0) == 1 ]]
}

is_wired() { [[ $1 == en* || $1 == eth* ]]; }

# Auto pick: first usable wired NIC, else first usable wireless NIC. Empty if
# nothing is up right now (caller then leaves Suricata where it is).
pick_auto() {
  local n
  for n in $(list_ifaces); do is_wired "$n" && iface_usable "$n" && { echo "$n"; return; }; done
  for n in $(list_ifaces); do is_wired "$n" || { iface_usable "$n" && { echo "$n"; return; }; }; done
  echo ""
}

current_iface() {
  local i=""
  [[ -r $SURICATA_DEFAULT ]] && i=$(sed -n 's/^IFACE=//p' "$SURICATA_DEFAULT" | head -1)
  [[ -z $i && -r $SURICATA_YAML ]] && i=$(sed -n 's/^[[:space:]]*- interface:[[:space:]]*//p' "$SURICATA_YAML" | head -1)
  echo "$i"
}

# --- apply ------------------------------------------------------------------
apply_iface() {  # <iface>  -> reconfigure + restart Suricata (idempotent)
  local iface=$1
  [[ -n $iface && -e /sys/class/net/$iface ]] || { echo "apply: no such interface '$iface'" >&2; return 1; }

  if [[ $(current_iface) == "$iface" ]] && systemctl is-active --quiet suricata; then
    return 0   # already bound and running - nothing to do
  fi

  if [[ -f $SURICATA_DEFAULT ]]; then
    if grep -q '^IFACE=' "$SURICATA_DEFAULT"; then
      sed -i "s/^IFACE=.*/IFACE=$iface/" "$SURICATA_DEFAULT"
    else
      echo "IFACE=$iface" >> "$SURICATA_DEFAULT"
    fi
  fi
  # Keep the af-packet section's first interface in sync (this is what the
  # running engine actually captures on).
  sed -i "0,/^\([[:space:]]*\)- interface:.*/s//\1- interface: $iface/" "$SURICATA_YAML"

  if ! suricata -T -c "$SURICATA_YAML" -i "$iface" >/dev/null 2>&1; then
    echo "apply: suricata config test failed for '$iface'" >&2
    return 1
  fi
  systemctl restart suricata
  echo "apply: Suricata now capturing on $iface"
}

# --- state ------------------------------------------------------------------
write_state() {  # mode configured recheck resolved active note
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  local ifjson n
  ifjson=""
  for n in $(list_ifaces); do
    local up=false; iface_usable "$n" && up=true
    ifjson+="{\"name\":\"$n\",\"up\":$up,\"wired\":$(is_wired "$n" && echo true || echo false)},"
  done
  ifjson="[${ifjson%,}]"
  cat > "$STATE" 2>/dev/null <<JSON || true
{
  "mode": "$1",
  "configured_interface": "$2",
  "recheck_seconds": $3,
  "resolved_interface": "$4",
  "active_interface": "$5",
  "suricata_active": $(systemctl is-active --quiet suricata && echo true || echo false),
  "note": "$6",
  "interfaces": $ifjson,
  "updated": $(date +%s)
}
JSON
  chmod 0644 "$STATE" 2>/dev/null || true
}

# --- evaluate ---------------------------------------------------------------
once() {
  local mode iface recheck; IFS='|' read -r mode iface recheck < <(read_cfg)
  local active target note
  active=$(current_iface)

  if [[ $mode == manual ]]; then
    if [[ -z $iface ]]; then
      target=""; note="manual mode but no interface set; leaving Suricata on ${active:-none}"
    elif iface_usable "$iface"; then
      target=$iface; note="manual: $iface is up"
    else
      target=""; note="manual: $iface is down (prepared); waiting, Suricata left on ${active:-none}"
    fi
  else
    target=$(pick_auto)
    if [[ -z $target ]]; then
      note="auto: no interface is up; leaving Suricata on ${active:-none}"
    else
      note="auto: best up interface is $target"
    fi
  fi

  if [[ -n $target && $target != "$active" ]]; then
    if apply_iface "$target"; then active=$target; note="switched to $target"; fi
  elif [[ -n $target ]]; then
    # Correct binding, but make sure the service is actually running.
    systemctl is-active --quiet suricata || apply_iface "$target" || true
  fi

  write_state "$mode" "$iface" "$recheck" "$target" "$active" "$note"
  echo "$note"
}

daemon() {
  echo "ids-adapter-manager: daemon started (config: $CONFIG)"
  while true; do
    once || true
    local recheck; recheck=$(read_cfg | cut -d'|' -f3)
    sleep "${recheck:-$DEFAULT_RECHECK}"
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
    need_root "apply ${2:-}"
    [[ -n ${2:-} ]] || die "usage: $0 apply <iface>"
    apply_iface "$2"
    ;;
  set)
    need_root "set ${2:-} ${3:-}"
    sel=${2:-} ; recheck=${3:-}
    [[ -n $sel ]] || die "usage: $0 set <auto|iface> [recheck_seconds]"
    IFS=$'\t' read -r cmode ciface crecheck < <(read_cfg)
    [[ -n $recheck ]] || recheck=$crecheck
    if [[ $sel == auto ]]; then
      write_cfg auto "" "$recheck"
    else
      [[ -e /sys/class/net/$sel ]] || die "no such interface '$sel'"
      write_cfg manual "$sel" "$recheck"
    fi
    once
    ;;
  *) die "unknown subcommand '$cmd' (once|daemon|set|status|apply)" ;;
esac
