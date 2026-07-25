#!/usr/bin/env bash
# Unified, menu-driven setup for the Network Probe.
#
# This is a thin orchestrator over the individual component installers in this
# directory - it does not itself change the system. It lets you pick a role
# (standalone node, or a slim collector) or individual components, shows the
# exact ordered plan, and then runs each real installer with its own --apply.
#
# Nothing is applied without confirmation. Preview a plan safely with:
#   ./scripts/setup.sh --standalone --dry-run
# Apply it for real (most components need root):
#   sudo ./scripts/setup.sh --standalone --apply
# Interactive menu (pick components):
#   sudo ./scripts/setup.sh
#
# A collector node needs the aggregator URL + the one-time ingest key:
#   sudo AGGREGATOR_URL=http://192.168.50.32:8088 INGEST_KEY=<key> \
#        ./scripts/setup.sh --collector --apply
set -euo pipefail

here=$(cd -- "$(dirname -- "$0")" && pwd)

# Component registry. Each row: id|title|script|run_as|extra_args
# run_as: root (needs sudo) | user (must NOT be root) | root-noapply (root, no --apply flag)
# Order here is the canonical *apply* order (dependencies first).
components=(
  "lightweight|Base packages & CLI tools|install-lightweight.sh|root-noapply|"
  "dashboard|Dashboard web service (systemd)|install-dashboard-service.sh|root|--apply"
  "monitor|Continuous outage monitor (needs dashboard)|install-outage-monitor.sh|root|--apply"
  "reconciler|Privileged reconciler (safe network changes)|install-reconciler.sh|root|--apply"
  "neighbours|LLDP neighbour discovery (lldpd)|install-neighbors.sh|root|--apply"
  "ids|Suricata passive IDS|install-ids.sh|root|--apply"
  "ids-adapter|IDS capture-NIC auto-switch daemon|install-ids-adapter.sh|root|--apply"
  "ntopng|ntopng passive flow analyser|install-ntopng.sh|root|--apply"
  "desktop|Desktop launchers (run as your user)|install-desktop-launcher.sh|user|"
  "collector|Collector push-agent (slim node)|install-collector.sh|root|--apply"
)

# Profiles map a role to an ordered set of component ids.
profile_standalone="lightweight dashboard monitor reconciler neighbours"
profile_full="lightweight dashboard monitor reconciler neighbours ids ids-adapter ntopng"
profile_collector="collector"

usage() {
  cat <<'EOF'
Network Probe unified setup

Usage:
  setup.sh [role] [options]
  setup.sh                         interactive menu (choose components)

Roles (pick one):
  --standalone     core self-sufficient node: base tools, dashboard, monitor,
                   reconciler, LLDP neighbours
  --full           --standalone plus Suricata IDS, IDS adapter and ntopng
  --collector      slim collector push-agent only (needs AGGREGATOR_URL + INGEST_KEY)

Component selection (repeatable, combine freely):
  --component <id>    add one component by id (see --list)

Options:
  --list           list available components and exit
  --dry-run        show the ordered plan without changing anything (no root needed)
  --apply          actually run each component installer
  --yes, -y        do not prompt for confirmation before applying
  --help, -h       this help

Examples:
  ./scripts/setup.sh --standalone --dry-run
  sudo ./scripts/setup.sh --full --apply
  sudo ./scripts/setup.sh --component dashboard --component ids --apply
EOF
}

list_components() {
  printf '%-13s %s\n' "ID" "COMPONENT"
  local row id title
  for row in "${components[@]}"; do
    IFS='|' read -r id title _ _ _ <<<"$row"
    printf '%-13s %s\n' "$id" "$title"
  done
  echo
  echo "Profiles: --standalone ($profile_standalone)"
  echo "          --full ($profile_full)"
  echo "          --collector ($profile_collector)"
}

# Look up a registry row by id; echoes the row or returns 1.
row_for() {
  local want=$1 row id
  for row in "${components[@]}"; do
    IFS='|' read -r id _ _ _ _ <<<"$row"
    [[ $id == "$want" ]] && { echo "$row"; return 0; }
  done
  return 1
}

# Reduce a space-separated id set to canonical apply order, de-duplicated.
order_ids() {
  local sel=" $* " row id ordered=()
  for row in "${components[@]}"; do
    IFS='|' read -r id _ _ _ _ <<<"$row"
    [[ $sel == *" $id "* ]] && ordered+=("$id")
  done
  echo "${ordered[@]}"
}

DRY_RUN=0
APPLY=0
ASSUME_YES=0
selected=""

add_ids() { selected="$selected $*"; }

# --- parse args ---
[[ $# -eq 0 ]] && INTERACTIVE=1 || INTERACTIVE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --standalone) add_ids "$profile_standalone" ;;
    --full)       add_ids "$profile_full" ;;
    --collector)  add_ids "$profile_collector" ;;
    --component)  shift; [[ ${1:-} ]] || { echo "--component needs an id" >&2; exit 2; }
                  row_for "$1" >/dev/null || { echo "unknown component: $1 (see --list)" >&2; exit 2; }
                  add_ids "$1" ;;
    --list)       list_components; exit 0 ;;
    --dry-run)    DRY_RUN=1 ;;
    --apply)      APPLY=1 ;;
    --yes|-y)     ASSUME_YES=1 ;;
    --help|-h)    usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# --- interactive menu when no selection was given ---
if [[ $INTERACTIVE -eq 1 || -z ${selected// } ]]; then
  if [[ ! -t 0 ]]; then
    echo "No components selected and no TTY for the menu. Use --standalone/--full/--collector or --component." >&2
    usage >&2
    exit 2
  fi
  echo "Select components to install (space-separated numbers), or a profile:"
  echo "  s) standalone profile   f) full profile   c) collector profile"
  i=1; menu_ids=()
  for row in "${components[@]}"; do
    IFS='|' read -r id title _ _ _ <<<"$row"
    printf '  %2d) %-13s %s\n' "$i" "$id" "$title"
    menu_ids+=("$id"); i=$((i+1))
  done
  printf 'Choice: '
  read -r choice
  case "$choice" in
    s) add_ids "$profile_standalone" ;;
    f) add_ids "$profile_full" ;;
    c) add_ids "$profile_collector" ;;
    *) for n in $choice; do
         [[ $n =~ ^[0-9]+$ ]] && (( n>=1 && n<=${#menu_ids[@]} )) \
           && add_ids "${menu_ids[$((n-1))]}" \
           || { echo "invalid choice: $n" >&2; exit 2; }
       done ;;
  esac
fi

ordered=$(order_ids $selected)
[[ -n ${ordered// } ]] || { echo "Nothing selected." >&2; exit 2; }

# --- build + show the plan ---
echo "Planned components (in order):"
for id in $ordered; do
  row=$(row_for "$id"); IFS='|' read -r _ title script run_as extra <<<"$row"
  case "$run_as" in
    user) how="as your user" ;;
    root|root-noapply) how="as root" ;;
    *) how="" ;;
  esac
  printf '  - %-13s %s  [%s %s, %s]\n' "$id" "$title" "$script" "${extra:-}" "$how"
done

if [[ $DRY_RUN -eq 1 || $APPLY -eq 0 ]]; then
  echo
  echo "(dry run - nothing applied). Re-run with --apply to install."
  exit 0
fi

# --- apply: confirm, then run each real installer in order ---
if [[ $ASSUME_YES -eq 0 ]]; then
  printf 'Apply the plan above? [y/N] '
  read -r ans
  [[ $ans == [yY] || $ans == [yY][eE][sS] ]] || { echo "Aborted."; exit 1; }
fi

run_component() {
  local id=$1 row script run_as extra
  row=$(row_for "$id"); IFS='|' read -r _ _ script run_as extra <<<"$row"
  local path="$here/$script"
  [[ -f $path ]] || { echo "missing installer: $path" >&2; return 1; }
  echo "==> $id: $script ${extra:-}"
  case "$run_as" in
    user)
      if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
        # desktop launchers must land on the real user's desktop, not root's
        [[ -n ${SUDO_USER:-} ]] || { echo "  skip: run '$script' as your normal desktop user, not root." >&2; return 0; }
        sudo -u "$SUDO_USER" bash "$path" $extra
      else
        bash "$path" $extra
      fi ;;
    collector)
      : "${AGGREGATOR_URL:?collector needs AGGREGATOR_URL}" "${INGEST_KEY:?collector needs INGEST_KEY}"
      bash "$path" $extra ;;
    *)
      bash "$path" $extra ;;
  esac
}

for id in $ordered; do
  if [[ $id == collector ]]; then
    : "${AGGREGATOR_URL:?collector needs AGGREGATOR_URL (see enrollment)}" \
      "${INGEST_KEY:?collector needs INGEST_KEY (shown once at enrollment)}"
  fi
  run_component "$id"
done

echo "Setup complete: $ordered"
