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


def _signal_label(ap: dict) -> tuple[float | None, str]:
    """Normalise either back-end's signal to an approximate dBm and a word.
    nmcli gives a 0-100%, iw gives dBm; map % to a rough dBm for one scale."""
    dbm = ap.get("signal_dbm")
    if dbm is None and ap.get("signal_pct") is not None:
        dbm = ap["signal_pct"] / 2.0 - 100.0  # 100% -> -50, 50% -> -75
    if dbm is None:
        return None, "unknown"
    if dbm >= -60:
        return dbm, "strong"
    if dbm >= -72:
        return dbm, "fair"
    return dbm, "weak"


def assess(aps: list[dict]) -> dict:
    """Turn the raw AP list into the survey's answers: coverage, band/RF design,
    security posture and rogue/evil-twin clues. Everything here is derived from
    the passive scan already taken - it sends nothing new."""
    if not aps:
        return {}
    bands: dict[str, int] = {}
    security: dict[str, int] = {}
    per_channel: dict[tuple, int] = {}
    ssid_bssids: dict[str, set] = {}
    hidden = 0
    coverage = {"strong": 0, "fair": 0, "weak": 0, "unknown": 0}
    best = None
    for ap in aps:
        bands[ap["band"]] = bands.get(ap["band"], 0) + 1
        sec = ap.get("security") or "Open"
        security[sec] = security.get(sec, 0) + 1
        per_channel[(ap["band"], ap["channel"])] = per_channel.get((ap["band"], ap["channel"]), 0) + 1
        ssid = ap.get("ssid", "")
        if ssid and ssid != "(hidden)":
            ssid_bssids.setdefault(ssid, set()).add(ap["bssid"])
        else:
            hidden += 1
        dbm, word = _signal_label(ap)
        coverage[word] += 1
        if dbm is not None and (best is None or dbm > best[0]):
            best = (dbm, ap)

    overlap = [{"band": b, "channel": c, "ap_count": n}
               for (b, c), n in sorted(per_channel.items(), key=lambda kv: -kv[1]) if n > 1]
    twins = [{"ssid": s, "bssid_count": len(bs), "bssids": sorted(bs)}
             for s, bs in ssid_bssids.items() if len(bs) > 1]
    open_count = sum(n for s, n in security.items() if s.lower() in ("open", "", "--"))
    weak_enc = sum(n for s, n in security.items() if "wep" in s.lower())

    notes = []
    if open_count:
        notes.append(f"{open_count} open (unencrypted) network(s) on air")
    if weak_enc:
        notes.append(f"{weak_enc} network(s) using deprecated WEP")
    if twins:
        notes.append(f"{len(twins)} SSID(s) advertised by multiple BSSIDs "
                     "(normal for roaming/mesh, but also the evil-twin signature - verify the BSSIDs are yours)")
    if overlap:
        worst = overlap[0]
        notes.append(f"channel congestion: {worst['ap_count']} APs share {worst['band']} ch{worst['channel']}")
    if coverage["weak"] and not coverage["strong"]:
        notes.append("no strong-signal AP visible from here - coverage or antenna placement may be poor")

    return {
        "coverage": coverage,
        "strongest": ({"ssid": best[1]["ssid"], "bssid": best[1]["bssid"],
                       "band": best[1]["band"], "channel": best[1]["channel"],
                       "approx_dbm": round(best[0], 1)} if best else None),
        "bands": [{"band": b, "ap_count": n} for b, n in sorted(bands.items(), key=lambda kv: -kv[1])],
        "security": [{"type": s, "ap_count": n} for s, n in sorted(security.items(), key=lambda kv: -kv[1])],
        "open_count": open_count,
        "co_channel": overlap[:8],
        "same_ssid_multi_bssid": twins,
        "hidden_count": hidden,
        "notes": notes,
    }


def channel_summary(aps: list[dict]) -> list[dict]:
    counts: dict[tuple, int] = {}
    for ap in aps:
        key = (ap["band"], ap["channel"])
        counts[key] = counts.get(key, 0) + 1
    return [{"band": band, "channel": chan, "ap_count": n}
            for (band, chan), n in sorted(counts.items(), key=lambda item: -item[1])]


# --- Spectrum / interference analyser --------------------------------------
# We have no SDR, so this is not a true RF spectrum - it is a *channel*
# occupancy model built from the passive AP scan. Each AP spreads its energy
# across the channels its 20 MHz carrier physically overlaps (in 2.4 GHz the
# 5 MHz-spaced channels overlap heavily; in 5/6 GHz the common 20 MHz channels
# do not), weighted by received power. That is exactly the interference an AP
# on a given channel would experience, which is what "pick a clean channel"
# needs. Honest about its limits: no non-Wi-Fi emitters (microwaves, BT, radar).

# Canonical 20 MHz channel grids per band for a stable x-axis.
_BAND_CHANNELS = {
    "2.4 GHz": list(range(1, 14)),
    "5 GHz": [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120,
              124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165],
    "6 GHz": [1 + 4 * i for i in range(59)],  # 6E 20 MHz channels 1..233
}
# The classic non-overlapping 2.4 GHz set - what we steer people toward.
_NON_OVERLAP_24 = [1, 6, 11]


def _approx_dbm(ap: dict) -> float | None:
    """One dBm scale from either back-end (iw gives dBm, nmcli a 0-100%)."""
    dbm = ap.get("signal_dbm")
    if dbm is None and ap.get("signal_pct") is not None:
        dbm = ap["signal_pct"] / 2.0 - 100.0
    return dbm


def _overlap_weights(band: str, channel: int) -> dict[int, float]:
    """Fraction of a 20 MHz carrier centred on `channel` that lands on each
    nearby channel slot. 2.4 GHz channels sit 5 MHz apart, so a 20 MHz carrier
    bleeds onto +/-2 neighbours (triangular roll-off); 5/6 GHz 20 MHz channels
    are 20 MHz apart and treated as self-only."""
    if band == "2.4 GHz":
        return {channel - 2: 0.35, channel - 1: 0.7, channel: 1.0,
                channel + 1: 0.7, channel + 2: 0.35}
    return {channel: 1.0}


def spectrum(aps: list[dict]) -> dict:
    """Per-band, per-channel occupancy + a recommended clean channel.

    occupancy is summed received power (linear mW) an AP on that channel would
    face from every overlapping neighbour, normalised to 0..100 across all
    bands for display. ap_count is how many APs land on the slot at all."""
    if not aps:
        return {"bands": [], "notes": ["no APs visible - enable the radio and rescan"]}

    # Accumulate linear power + counts per (band, channel).
    power: dict[tuple, float] = {}
    count: dict[tuple, float] = {}
    strongest: dict[tuple, tuple] = {}  # (band,chan) -> (dbm, ssid)
    for ap in aps:
        band = ap.get("band") or "?"
        if band not in _BAND_CHANNELS:
            continue
        chan = ap.get("channel") or 0
        dbm = _approx_dbm(ap)
        # Unknown-signal APs still occupy the channel; treat them as weak (-85).
        mw = 10 ** ((dbm if dbm is not None else -85.0) / 10.0)
        for slot, w in _overlap_weights(band, chan).items():
            if slot not in _BAND_CHANNELS[band]:
                continue
            key = (band, slot)
            power[key] = power.get(key, 0.0) + mw * w
            count[key] = count.get(key, 0.0) + w
            if w >= 1.0 and dbm is not None:
                cur = strongest.get(key)
                if cur is None or dbm > cur[0]:
                    strongest[key] = (dbm, ap.get("ssid") or "(hidden)")

    peak = max(power.values()) if power else 1.0
    bands_out = []
    for band, channels in _BAND_CHANNELS.items():
        # Only surface a band we actually heard something on.
        if not any((band, c) in power for c in channels):
            continue
        rows = []
        for c in channels:
            key = (band, c)
            occ = round(100.0 * power.get(key, 0.0) / peak, 1)
            rows.append({
                "channel": c,
                "occupancy": occ,
                "ap_count": int(round(count.get(key, 0.0))),
                "dominant": strongest.get(key, (None, None))[1],
            })
        candidates = ([c for c in _NON_OVERLAP_24] if band == "2.4 GHz"
                      else [r["channel"] for r in rows])
        best = min(candidates, key=lambda c: power.get((band, c), 0.0))
        occ_by_chan = {r["channel"]: r["occupancy"] for r in rows}
        reason = ("least-occupied of the non-overlapping 1/6/11 set"
                  if band == "2.4 GHz" else "least-occupied channel heard")
        bands_out.append({
            "band": band,
            "channels": rows,
            "recommend": {"channel": best, "occupancy": occ_by_chan.get(best, 0.0),
                          "reason": reason},
        })

    # Busiest slot overall + a couple of plain-language notes.
    notes = []
    if power:
        (bb, bc), _ = max(power.items(), key=lambda kv: kv[1])
        notes.append(f"busiest slot: {bb} ch{bc}")
    if any(b["band"] == "2.4 GHz" for b in bands_out):
        rec = next(b["recommend"] for b in bands_out if b["band"] == "2.4 GHz")
        notes.append(f"2.4 GHz is crowded by design - prefer ch{rec['channel']} "
                     "and move clients to 5/6 GHz where you can")
    return {"bands": bands_out, "notes": notes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wi-Fi AP/channel survey.")
    parser.add_argument("--iface", required=True)
    parser.add_argument("--rescan", action="store_true")
    args = parser.parse_args(argv)

    backend = "nmcli"
    aps = survey_nmcli(args.iface, args.rescan)
    iw_error = ""
    if not aps:
        # nmcli gave us nothing usable. Two cases land here: the command failed
        # (aps is None), or it succeeded but its scan cache is empty (aps == [])
        # because NetworkManager has the radio disabled. In BOTH cases a direct
        # `iw` scan can still see APs - it talks to the phy and bypasses NM's
        # managed/rfkill-aggregated path - so always try it before giving up.
        iw_aps, iw_error = survey_iw(args.iface)
        if iw_aps:
            aps, backend = iw_aps, "iw"
        elif aps is None:
            # Neither backend produced anything and nmcli itself could not run.
            print(json.dumps({"error": iw_error}))
            return 2
        else:
            aps = []  # keep the empty list; the note below explains why

    note = ""
    if not aps and not radio_enabled():
        note = ("Wi-Fi radio is off/blocked - NetworkManager reports the radio "
                "disabled. If this is a Dell platform rfkill HARD block, software "
                "cannot clear it: use the physical wireless switch / Fn key or "
                "enable the WLAN radio in BIOS, then rescan. "
                + (f"(iw fallback: {iw_error})" if iw_error else "")).strip()

    print(json.dumps({
        "interface": args.iface, "backend": backend, "ap_count": len(aps),
        "channels": channel_summary(aps), "assessment": assess(aps),
        "spectrum": spectrum(aps), "aps": aps, "note": note,
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
