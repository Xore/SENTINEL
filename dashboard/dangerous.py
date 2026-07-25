"""Roadmap P5 - the excluded-by-default capability register and its safety gate
(task #55).

The product roadmap lists behaviours the probe deliberately does NOT do:
subnet expansion / exploit scanning, credential guessing / SNMP sweeps, Wi-Fi
deauth / injection / impersonation, S7 / OPC UA writes and program operations,
and inline blocking / production changes / internet exposure. This module turns
that prose list into an explicit, gated register so the exclusions are visible
and auditable in the dashboard instead of merely being absent from the code.

Important: this is governance, not tooling. Every action here is
`implemented=False`. `run_action()` NEVER performs the destructive technique -
it refuses even when the operator has enabled the master switch and ticked the
per-item acknowledgement. Those toggles only unhide the item and record intent
(the caller writes an audit entry); the technique itself stays unbuilt by
design. If a genuinely non-destructive, authorised diagnostic is ever wanted,
it should be added as its own ordinary, ungated feature - not smuggled in here.
"""
from __future__ import annotations

# Each entry mirrors one bullet from the roadmap's "Excluded by default" list.
# `category` groups the finer-grained ids that make up one bullet.
ACTIONS: list[dict] = [
    {
        "id": "subnet_expansion",
        "category": "scanning",
        "title": "Automatic subnet expansion",
        "risk": "Turns a scoped probe into an unbounded network sweep.",
        "implemented": False,
    },
    {
        "id": "vuln_exploit_scan",
        "category": "scanning",
        "title": "Vulnerability / exploit scanning",
        "risk": "Active exploitation can crash hosts, especially fragile OT devices.",
        "implemented": False,
    },
    {
        "id": "credential_guessing",
        "category": "credentials",
        "title": "Credential guessing / default-password checks",
        "risk": "Account lockouts, IDS noise, and unauthorised access attempts.",
        "implemented": False,
    },
    {
        "id": "snmp_sweep",
        "category": "credentials",
        "title": "SNMP community sweeps",
        "risk": "Community-string guessing against infrastructure devices.",
        "implemented": False,
    },
    {
        "id": "wifi_deauth",
        "category": "wireless",
        "title": "Wi-Fi deauthentication",
        "risk": "Denial of service - knocks clients off the air.",
        "implemented": False,
    },
    {
        "id": "wifi_injection",
        "category": "wireless",
        "title": "Wi-Fi frame injection",
        "risk": "Injects crafted 802.11 frames into a live RF environment.",
        "implemented": False,
    },
    {
        "id": "wifi_impersonation",
        "category": "wireless",
        "title": "Wi-Fi AP impersonation (rogue/evil-twin)",
        "risk": "Impersonates infrastructure to intercept clients.",
        "implemented": False,
    },
    {
        "id": "ot_write",
        "category": "ot",
        "title": "S7 / OPC UA writes",
        "risk": "Writing to a live controller can move machinery or halt a process.",
        "implemented": False,
    },
    {
        "id": "ot_mode_change",
        "category": "ot",
        "title": "PLC mode changes / program operations",
        "risk": "Stop/run/program-download can take production offline unsafely.",
        "implemented": False,
    },
    {
        "id": "ot_node_browse",
        "category": "ot",
        "title": "Arbitrary OPC UA node browsing",
        "risk": "Unbounded browsing/reads outside an approved health NodeId.",
        "implemented": False,
    },
    {
        "id": "inline_blocking",
        "category": "control",
        "title": "Inline blocking / automatic production changes",
        "risk": "The probe must stay passive; inline action can break the network.",
        "implemented": False,
    },
    {
        "id": "internet_exposure",
        "category": "control",
        "title": "Internet dashboard exposure",
        "risk": "Publishing the dashboard to the internet exposes sensitive data.",
        "implemented": False,
    },
]

_BY_ID = {a["id"]: a for a in ACTIONS}


def action_ids() -> set[str]:
    return set(_BY_ID)


def _cfg(settings: dict) -> dict:
    da = (settings or {}).get("dangerous_actions") or {}
    return da if isinstance(da, dict) else {}


def is_enabled(settings: dict) -> bool:
    """Master switch: are dangerous actions unlocked at all?"""
    return bool(_cfg(settings).get("enabled"))


def is_acknowledged(settings: dict, action_id: str) -> bool:
    ack = _cfg(settings).get("acknowledged") or {}
    return bool(isinstance(ack, dict) and ack.get(action_id))


def list_actions(settings: dict) -> list[dict]:
    """The register annotated with current gate state, for the dashboard tab."""
    enabled = is_enabled(settings)
    out = []
    for a in ACTIONS:
        item = dict(a)
        item["unlocked"] = enabled and is_acknowledged(settings, a["id"])
        item["acknowledged"] = is_acknowledged(settings, a["id"])
        out.append(item)
    return out


def gate(settings: dict, action_id: str) -> tuple[bool, str]:
    """Decide whether an action may proceed. Returns (allowed, reason).

    `allowed` is True ONLY when the master switch is on, the specific action is
    acknowledged, AND the action is implemented. Because every action is
    `implemented=False`, this currently always denies - which is the point:
    the destructive techniques are not built. The gate still enforces the
    switch/ack ordering so a future non-destructive addition inherits it.
    """
    action = _BY_ID.get(action_id)
    if action is None:
        return False, f"unknown action '{action_id}'"
    if not is_enabled(settings):
        return False, "dangerous actions are disabled (enable the master switch first)"
    if not is_acknowledged(settings, action_id):
        return False, "action not acknowledged (tick its warning box first)"
    if not action.get("implemented"):
        return False, ("this build does not implement this technique by design; "
                       "it remains excluded")
    return True, "ok"


def run_action(settings: dict, action_id: str, payload: dict | None = None) -> dict:
    """Attempt to run a dangerous action. Never executes a destructive
    technique - returns a structured refusal describing the gate decision. The
    caller is expected to audit-log the attempt regardless of outcome."""
    allowed, reason = gate(settings, action_id)
    action = _BY_ID.get(action_id)
    return {
        "action": action_id,
        "title": action["title"] if action else action_id,
        "allowed": allowed,
        "executed": False,           # nothing destructive is ever executed here
        "reason": reason,
    }
