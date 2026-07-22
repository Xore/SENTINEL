"""Wi-Fi AP / channel survey for the network probe.

Answers the original "which AP is the Wi-Fi coming from and what does the RF
neighbourhood look like" question: a structured AP list with BSSID, SSID,
channel, band, signal and a security label, plus a per-channel occupancy
summary.

Two back-ends, tried in order:
  1. `nmcli dev wifi list` - reads NetworkManager's scan cache. Works
     unprivileged (the dashboard uses this) as long as the radio is enabled.
  2. `iw dev <iface> scan` - direct scan; richer but needs root. Used as a
     fallback when run from a shell with sudo.

A scan only sends standard probe requests. It needs the radio enabled - if it
is rfkill-blocked, both back-ends fail and we say so.

CLI (used by the dashboard):
  wifi_survey.py --iface wlp2s0 [--rescan]
Prints a JSON summary on stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys


def band_for(freq_mhz: int) -> str:
    if 2400 <= freq_mhz <= 2500:
        return "2.4 GHz"
    if 5000 <= freq_mhz < 5925:
        return "5 GHz"
    if 5925 <= freq_mhz <= 7125:
        return "6 GHz"
    return "?"


def channel_for(freq_mhz: int) -> int:
    if 2412 <= freq_mhz <= 2472:
        return (freq_mhz - 2407) // 5
    if freq_mhz == 2484:
        return 14
    if 5000 <= freq_mhz <= 5900:
        return (freq_mhz - 5000) // 5
    if 5925 <= freq_mhz <= 7125:
        return (freq_mhz - 5950) // 5
    return 0


def _split_terse(line: str) -> list[str]:
    """nmcli -t escapes ':' inside fields (e.g. BSSID) as '\\:'."""
    return [part.replace("\\:", ":") for part in re.split(r"(?<!\\):", line)]


def survey_nmcli(iface: str, rescan: bool) -> list[dict] | None:
    if rescan:
        subprocess.run(["nmcli", "dev", "wifi", "rescan", "ifname", iface],
                       capture_output=True, text=True, timeout=20)
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "IN-USE,BSSID,SSID,CHAN,FREQ,SIGNAL,SECURITY",
             "dev", "wifi", "list", "ifname", iface],
            capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    aps = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        fields = _split_terse(line)
        if len(fields) < 7:
            continue
        in_use, bssid, ssid, chan, freq, signal, security = fields[:7]
        freq_mhz = int(re.sub(r"\D", "", freq) or 0)
        aps.append({
            "bssid": bssid.lower(),
            "ssid": ssid or "(hidden)",
            "channel": int(chan) if chan.isdigit() else channel_for(freq_mhz),
            "freq_mhz": freq_mhz, "band": band_for(freq_mhz),
            "signal_pct": int(signal) if signal.isdigit() else None,
            "security": security or "Open",
            "in_use": in_use.strip() == "*",
        })
    aps.sort(key=lambda ap: (ap["signal_pct"] is None, -(ap["signal_pct"] or -1)))
    return aps


def survey_iw(iface: str) -> tuple[list[dict] | None, str]:
    try:
        result = subprocess.run(["iw", "dev", iface, "scan"],
                                capture_output=True, text=True, timeout=25)
    except FileNotFoundError:
        return None, "iw is not installed"
    except subprocess.TimeoutExpired:
        return None, "iw scan timed out"
    if result.returncode != 0:
        message = result.stderr.strip() or "iw scan failed"
        if "not permitted" in message.lower():
            message = "iw scan needs root; run the dashboard survey (nmcli) or use sudo"
        elif "rfkill" in message.lower() or "blocked" in message.lower():
            message = "radio is rfkill-blocked - enable the wireless switch/BIOS radio first"
        return None, message
    aps = []
    for chunk in re.split(r"(?=^BSS )", result.stdout, flags=re.MULTILINE):
        bssid = re.match(r"BSS ([0-9a-fA-F:]{17})", chunk.strip())
        if not bssid:
            continue
        ssid = re.search(r"^\s*SSID: (.*)$", chunk, re.MULTILINE)
        freq = re.search(r"freq: (\d+)", chunk)
        signal = re.search(r"signal: (-?[\d.]+) dBm", chunk)
        freq_mhz = int(freq.group(1)) if freq else 0
        aps.append({
            "bssid": bssid.group(1).lower(),
            "ssid": (ssid.group(1).strip() if ssid else "") or "(hidden)",
            "channel": channel_for(freq_mhz), "freq_mhz": freq_mhz, "band": band_for(freq_mhz),
            "signal_dbm": float(signal.group(1)) if signal else None,
            "security": "WPA2/WPA3" if "SAE" in chunk else ("WPA2" if "RSN" in chunk else
                        ("WPA" if "WPA:" in chunk else ("WEP" if "Privacy" in chunk else "Open"))),
            "in_use": False,
        })
    aps.sort(key=lambda ap: (ap.get("signal_dbm") is None, -(ap.get("signal_dbm") or -999)))
    return aps, ""


def radio_enabled() -> bool:
    try:
        out = subprocess.run(["nmcli", "radio", "wifi"], capture_output=True, text=True, timeout=5).stdout
        return out.strip().lower() == "enabled"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True  # can't tell; don't claim it's off


def channel_summary(aps: list[dict]) -> list[dict]:
    counts: dict[tuple, int] = {}
    for ap in aps:
        key = (ap["band"], ap["channel"])
        counts[key] = counts.get(key, 0) + 1
    return [{"band": band, "channel": chan, "ap_count": n}
            for (band, chan), n in sorted(counts.items(), key=lambda item: -item[1])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wi-Fi AP/channel survey.")
    parser.add_argument("--iface", required=True)
    parser.add_argument("--rescan", action="store_true")
    args = parser.parse_args(argv)

    backend = "nmcli"
    aps = survey_nmcli(args.iface, args.rescan)
    if aps is None:
        backend = "iw"
        aps, error = survey_iw(args.iface)
        if aps is None:
            print(json.dumps({"error": error}))
            return 2

    note = ""
    if not aps and not radio_enabled():
        note = "Wi-Fi radio is off/blocked - enable the wireless switch or BIOS radio, then rescan."

    print(json.dumps({
        "interface": args.iface, "backend": backend, "ap_count": len(aps),
        "channels": channel_summary(aps), "aps": aps, "note": note,
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
