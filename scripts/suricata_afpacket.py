#!/usr/bin/env python3
"""Rewrite the af-packet interface list in suricata.yaml to a given set of NICs.

Passive-IDS multi-interface support: Suricata captures on every interface that
appears as an af-packet block, in one engine with one eve.json. This regenerates
the explicit NIC blocks (one per requested interface, each with a unique
cluster-id) and preserves the trailing `- interface: default` catch-all, which
supplies the shared tuning defaults. All other suricata.yaml sections are left
untouched.

Only the interface *list* changes here; the caller is responsible for backing up
the file and running `suricata -T` before restarting the service.

Usage: suricata_afpacket.py <yaml> <iface1> [iface2 ...]
Exit 0 and writes in place on success; exit 2 without writing if the af-packet
section cannot be located or no interfaces are given.
"""
from __future__ import annotations

import re
import sys

# A generated block inherits everything else from `- interface: default`; we only
# pin the load-balancing essentials so multiple NICs don't collide on cluster-id.
BLOCK_TEMPLATE = (
    "  - interface: {iface}\n"
    "    cluster-id: {cid}\n"
    "    cluster-type: cluster_flow\n"
    "    defrag: yes\n"
    "    use-mmap: yes\n"
    "    tpacket-v3: yes\n"
)


def _section_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Return (start, end): the index of the `af-packet:` line and the index of
    the next top-level key (column 0, non-blank, non-comment) after it."""
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^af-packet:\s*$", line):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.strip() == "" or line.startswith((" ", "\t", "#")):
            continue
        if re.match(r"^\S", line):   # next top-level key
            end = j
            break
    return start, end


def _default_block(section: list[str]) -> list[str]:
    """Extract the `- interface: default` list item (with its children) verbatim,
    so we can re-append it unchanged. Empty list if there isn't one."""
    starts = [k for k, ln in enumerate(section)
              if re.match(r"^\s*-\s*interface:\s*\S", ln)]
    for idx, k in enumerate(starts):
        m = re.match(r"^\s*-\s*interface:\s*(\S+)", section[k])
        if m and m.group(1) == "default":
            stop = starts[idx + 1] if idx + 1 < len(starts) else len(section)
            return section[k:stop]
    return []


def rewrite(path: str, ifaces: list[str]) -> int:
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    bounds = _section_bounds(lines)
    if not bounds:
        print("af-packet section not found", file=sys.stderr)
        return 2
    start, end = bounds
    section = lines[start + 1:end]
    default_item = _default_block(section)

    new_section: list[str] = []
    for i, iface in enumerate(ifaces):
        new_section.append(BLOCK_TEMPLATE.format(iface=iface, cid=99 - i))
    new_blob = "".join(new_section) + "".join(default_item)
    # Ensure the section ends with a newline before the next top-level key.
    if new_blob and not new_blob.endswith("\n"):
        new_blob += "\n"

    lines[start + 1:end] = [new_blob]
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    print("af-packet interfaces set to: " + ", ".join(ifaces))
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    path = sys.argv[1]
    ifaces = [a for a in sys.argv[2:] if a.strip()]
    if not ifaces:
        print("no interfaces given", file=sys.stderr)
        return 2
    # De-dupe, preserve order.
    seen, uniq = set(), []
    for a in ifaces:
        if a not in seen:
            seen.add(a); uniq.append(a)
    return rewrite(path, uniq)


if __name__ == "__main__":
    raise SystemExit(main())
