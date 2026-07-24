#!/usr/bin/env bash
# Desktop selector for the Suricata IDS capture adapter(s).
#
# Double-click launcher (installed by install-desktop-launcher.sh). Suricata can
# capture on several NICs at once, so this offers three modes:
#   Auto      - follow the single best connected NIC (wired preferred)
#   All       - capture on every NIC that is up
#   Specific  - tick one or more NICs (a checklist); down/prepared NICs are bound
#               as soon as they come up
# then applies the choice through the root manager via pkexec (one graphical
# password prompt). Run as your normal desktop user, NOT root.
set -uo pipefail

MANAGER=${PROBE_IDS_MANAGER:-/opt/analyseLaptop/scripts/ids-adapter-manager.sh}
STATE=/run/network-probe-ids/state.json

command -v zenity >/dev/null 2>&1 || { echo "zenity is required (sudo apt install zenity)"; exit 1; }

err() { zenity --error --title="IDS Capture Adapter" --width=380 --text="$1"; exit 1; }

[[ -x $MANAGER || -f $MANAGER ]] || err "Manager not found at:\n$MANAGER\n\nRun scripts/install-ids-adapter.sh --apply on the probe first."

# Current state (world-readable file the daemon refreshes). Fall back to blanks.
cur_mode=auto; cur_recheck=60; active=""; configured_csv=""
if [[ -r $STATE ]]; then
  read -r cur_mode cur_recheck active configured_csv < <(python3 - "$STATE" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
def csv(key):
    v=d.get(key) or []
    return ",".join(str(x) for x in v) if isinstance(v,list) else ""
act=csv("active_interfaces")
print(d.get("mode","auto"), d.get("recheck_seconds",60),
      act or "-", csv("configured_interfaces") or "-")
PY
)
  [[ $active == "-" ]] && active=""
  [[ $configured_csv == "-" ]] && configured_csv=""
fi
active_disp=${active//,/, }

# Step 1: pick the mode.
sel_auto=FALSE sel_all=FALSE sel_spec=FALSE
case $cur_mode in
  all) sel_all=TRUE ;; manual) sel_spec=TRUE ;; *) sel_auto=TRUE ;;
esac
mode=$(zenity --list --radiolist --title="Select IDS Capture Adapter" \
  --width=560 --height=300 \
  --text="Suricata is currently capturing on: <b>${active_disp:-unknown}</b>\nHow should the IDS choose its capture interface(s)?" \
  --column="Pick" --column="mode" --column="Mode" \
  --hide-column=2 --print-column=2 \
  "$sel_auto" auto "Auto - follow the single best connected NIC" \
  "$sel_all"  all  "All - capture on every NIC that is up" \
  "$sel_spec" spec "Specific - choose one or more NICs myself") || exit 0
[[ -n $mode ]] || exit 0

# Build the current configured set for pre-ticking the checklist.
declare -A is_configured=()
IFS=',' read -ra _cfg <<< "$configured_csv"
for c in "${_cfg[@]}"; do [[ -n $c ]] && is_configured["$c"]=1; done

sel="$mode"
if [[ $mode == spec ]]; then
  # Step 2 (Specific only): a checklist of NICs with live up/down.
  rows=()
  if [[ -r $STATE ]]; then
    while IFS='|' read -r name up wired; do
      [[ -n $name ]] || continue
      state=$([[ $up == true ]] && echo "up" || echo "down (prepared)")
      kind=$([[ $wired == true ]] && echo wired || echo wireless)
      on=FALSE; [[ ${is_configured[$name]:-} == 1 ]] && on=TRUE
      rows+=("$on" "$name" "$kind, $state")
    done < <(python3 - "$STATE" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={"interfaces":[]}
for i in d.get("interfaces",[]):
    print(f'{i.get("name","")}|{str(i.get("up",False)).lower()}|{str(i.get("wired",False)).lower()}')
PY
)
  else
    for n in /sys/class/net/*; do n=$(basename "$n"); [[ $n == lo ]] && continue
      case $n in en*|eth*|wl*) ;; *) continue;; esac
      op=$(cat "/sys/class/net/$n/operstate" 2>/dev/null || echo unknown)
      rows+=("FALSE" "$n" "$op"); done
  fi
  picks=$(zenity --list --checklist --title="Choose capture NIC(s)" \
    --width=560 --height=380 \
    --text="Tick every NIC Suricata should watch. Down/prepared NICs are bound as soon as they come up." \
    --column="Watch" --column="Adapter" --column="Description" \
    --separator="," --print-column=2 \
    "${rows[@]}") || exit 0
  [[ -n $picks ]] || err "No NIC selected. Nothing changed."
  sel="$picks"
fi

recheck=$(zenity --scale --title="Recheck interval" \
  --text="How often (seconds) to re-check the adapter(s).\nMatters when a picked NIC is down/prepared - the IDS binds it as soon as it comes up." \
  --min-value=10 --max-value=600 --value="${cur_recheck:-60}" --step=10) || recheck=$cur_recheck

# Apply through the root manager (graphical auth prompt).
if out=$(pkexec "$MANAGER" set "$sel" "$recheck" 2>&1); then
  case $mode in
    auto) label="Auto (best connected NIC)" ;;
    all)  label="All up NICs" ;;
    *)    label="${sel//,/, }" ;;
  esac
  zenity --info --title="IDS Capture Adapter" --width=420 \
    --text="Saved.\n\nMode: <b>$label</b>\nRecheck: every ${recheck}s\n\n$out"
else
  err "Could not apply the change:\n\n$out"
fi
