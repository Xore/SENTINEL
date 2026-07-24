#!/usr/bin/env bash
# Desktop selector for the Suricata IDS capture adapter.
#
# Double-click launcher (installed by install-desktop-launcher.sh). Shows a
# graphical list of the laptop's NICs plus an "Auto" option and a recheck
# interval, then applies the choice through the root manager via pkexec (one
# graphical password prompt). Run as your normal desktop user, NOT root.
set -uo pipefail

MANAGER=${PROBE_IDS_MANAGER:-/opt/analyseLaptop/scripts/ids-adapter-manager.sh}
STATE=/run/network-probe-ids/state.json

command -v zenity >/dev/null 2>&1 || { echo "zenity is required (sudo apt install zenity)"; exit 1; }

err() { zenity --error --title="IDS Capture Adapter" --width=380 --text="$1"; exit 1; }

[[ -x $MANAGER || -f $MANAGER ]] || err "Manager not found at:\n$MANAGER\n\nRun scripts/install-ids-adapter.sh --apply on the probe first."

# Current state (world-readable file the daemon refreshes). Fall back to blanks.
cur_mode=auto; cur_iface=""; cur_recheck=60; active=""
if [[ -r $STATE ]]; then
  read -r cur_mode cur_iface cur_recheck active < <(python3 - "$STATE" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
print(d.get("mode","auto"), d.get("configured_interface","") or "-",
      d.get("recheck_seconds",60), d.get("active_interface","") or "-")
PY
)
  [[ $cur_iface == "-" ]] && cur_iface=""
  [[ $active == "-" ]] && active=""
fi

# Build the radio-list rows: Auto first, then each NIC with its live up/down.
rows=()
sel_auto=FALSE; [[ $cur_mode == auto ]] && sel_auto=TRUE
rows+=("$sel_auto" "auto" "Auto - follow the best connected NIC" "-")
if [[ -r $STATE ]]; then
  while IFS=$'\t' read -r name up wired; do
    [[ -n $name ]] || continue
    state=$([[ $up == true ]] && echo "up" || echo "down (prepared)")
    kind=$([[ $wired == true ]] && echo wired || echo wireless)
    on=FALSE; [[ $cur_mode == manual && $cur_iface == "$name" ]] && on=TRUE
    rows+=("$on" "$name" "$kind, $state" "$name")
  done < <(python3 - "$STATE" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={"interfaces":[]}
for i in d.get("interfaces",[]):
    print(f'{i.get("name","")}\t{str(i.get("up",False)).lower()}\t{str(i.get("wired",False)).lower()}')
PY
)
else
  # No state yet: list NICs straight from the kernel.
  for n in /sys/class/net/*; do n=$(basename "$n"); [[ $n == lo ]] && continue
    case $n in en*|eth*|wl*) ;; *) continue;; esac
    op=$(cat "/sys/class/net/$n/operstate" 2>/dev/null || echo unknown)
    rows+=("FALSE" "$n" "$op" "$n"); done
fi

choice=$(zenity --list --radiolist --title="Select IDS Capture Adapter" \
  --width=560 --height=380 \
  --text="Suricata is currently capturing on: <b>${active:-unknown}</b>\nChoose which NIC the IDS should watch." \
  --column="Pick" --column="Adapter" --column="Description" --column="id" \
  --hide-column=4 --print-column=4 \
  "${rows[@]}") || exit 0
[[ -n $choice ]] || exit 0

recheck=$(zenity --scale --title="Recheck interval" \
  --text="How often (seconds) to re-check the adapter.\nMatters when a pinned NIC is down/prepared - the IDS binds it as soon as it comes up." \
  --min-value=10 --max-value=600 --value="${cur_recheck:-60}" --step=10) || recheck=$cur_recheck

# Apply through the root manager (graphical auth prompt).
if out=$(pkexec "$MANAGER" set "$choice" "$recheck" 2>&1); then
  label=$([[ $choice == auto ]] && echo "Auto (best connected NIC)" || echo "$choice")
  zenity --info --title="IDS Capture Adapter" --width=420 \
    --text="Saved.\n\nMode: <b>$label</b>\nRecheck: every ${recheck}s\n\n$out"
else
  err "Could not apply the change:\n\n$out"
fi
