"""Read-only kernel TCP counters for retransmission/reset trend analysis (task #50).

This is a *passive* collector: it reads the cumulative TCP statistics the Linux
kernel already maintains in ``/proc/net/snmp`` and ``/proc/net/netstat``. It
sends no packets, opens no sockets and touches no device - it only reports the
counters the host has been keeping anyway. The outage monitor samples these
periodically into ``tcp_samples``; the dashboard turns the deltas into
retransmission-ratio and reset-rate trends.

The parsing is split from the file reading so it can be unit-tested with fixture
strings on any OS (there is no ``/proc`` on Windows).

CLI:
  tcp_stat.py            # prints one JSON snapshot of the counters, or
                         # {"available": false, ...} when /proc is not present

Counters reported (all cumulative since boot):
  in_segs, out_segs      - total TCP segments in/out (RetransSegs is a subset of out)
  retrans_segs           - retransmitted segments (the headline retransmit signal)
  out_rsts               - RST segments sent
  attempt_fails          - failed active connection attempts
  estab_resets           - established connections reset (RST'd after ESTABLISHED)
  tcp_syn_retrans        - SYN retransmits (from TcpExt; connection-setup loss)
  tcp_lost_retransmit    - retransmits the kernel later judged unnecessary
"""
from __future__ import annotations

import json
from pathlib import Path

SNMP_FILE = Path("/proc/net/snmp")
NETSTAT_FILE = Path("/proc/net/netstat")

# Fields we surface, mapped from their kernel counter names. Reading by name (not
# column position) keeps us robust to kernel-version differences in column order.
_SNMP_TCP = {
    "in_segs": "InSegs",
    "out_segs": "OutSegs",
    "retrans_segs": "RetransSegs",
    "out_rsts": "OutRsts",
    "attempt_fails": "AttemptFails",
    "estab_resets": "EstabResets",
}
_NETSTAT_TCPEXT = {
    "tcp_syn_retrans": "TCPSynRetrans",
    "tcp_lost_retransmit": "TCPLostRetransmit",
}


def _parse_section(text: str, prefix: str) -> dict[str, int]:
    """Parse a `/proc/net/{snmp,netstat}` two-line section.

    These files carry paired lines with the same label: one header row of field
    names and one data row of integers, e.g.

        Tcp: RtoAlgorithm RtoMin ... RetransSegs InErrs OutRsts InCsumErrors
        Tcp: 1 200 ... 1500 0 456 0

    Returns {field_name: int} for the requested prefix (e.g. "Tcp:" / "TcpExt:").
    A missing section, ragged lines or non-integer values yield an empty/partial
    dict rather than raising.
    """
    header: list[str] | None = None
    for line in text.splitlines():
        if not line.startswith(prefix):
            continue
        parts = line.split()[1:]  # drop the "Tcp:" label
        if header is None:
            header = parts
            continue
        out: dict[str, int] = {}
        for name, value in zip(header, parts):
            try:
                out[name] = int(value)
            except ValueError:
                continue  # skip signed/odd fields like RtoAlgorithm sentinels
        return out
    return {}


def collect_counters(snmp_text: str, netstat_text: str) -> dict[str, int]:
    """Flatten the counters we track from raw snmp+netstat text into one dict.

    Missing counters default to 0 so a snapshot always has a stable shape."""
    tcp = _parse_section(snmp_text, "Tcp:")
    ext = _parse_section(netstat_text, "TcpExt:")
    snapshot: dict[str, int] = {}
    for out_key, kernel_name in _SNMP_TCP.items():
        snapshot[out_key] = int(tcp.get(kernel_name, 0))
    for out_key, kernel_name in _NETSTAT_TCPEXT.items():
        snapshot[out_key] = int(ext.get(kernel_name, 0))
    return snapshot


# Column order for the tcp_samples table insert (ts prepended by the caller).
COUNTER_FIELDS = tuple(_SNMP_TCP) + tuple(_NETSTAT_TCPEXT)


def read_proc(snmp_path: Path = SNMP_FILE, netstat_path: Path = NETSTAT_FILE) -> dict | None:
    """Read the live kernel counters, or None when /proc is unavailable.

    Graceful by design: on a non-Linux host, or if the files cannot be read,
    returns None so the caller simply skips TCP sampling this cycle."""
    try:
        snmp_text = snmp_path.read_text(encoding="ascii", errors="replace")
        netstat_text = netstat_path.read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    return collect_counters(snmp_text, netstat_text)


def sample_row(now: float) -> tuple | None:
    """One (ts, *counters) row for the tcp_samples insert, or None if unavailable."""
    snap = read_proc()
    if snap is None:
        return None
    return (now,) + tuple(snap[f] for f in COUNTER_FIELDS)


def main() -> int:
    snap = read_proc()
    if snap is None:
        print(json.dumps({"available": False,
                          "error": "kernel TCP counters not available (no /proc/net/snmp)"}))
        return 0
    snap["available"] = True
    print(json.dumps(snap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
