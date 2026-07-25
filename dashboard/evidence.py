"""Freeze-evidence bundles (roadmap P1, task #47).

A dashboard action snapshots the current telemetry (recent monitor buffers +
active anomaly/alert context + the config in effect + the #48 session report)
into a timestamped, hashed bundle for an acceptance or incident hand-off.
JSON telemetry only — never a full PCAP.

This module is the **pure** part: it builds the manifest + bundle digest,
decides the disk-reserve question, and selects old bundles for rotation. It
performs no filesystem or database IO — app.py gathers the rows, writes the
files, stats the disk, and deletes rotated bundles. Keeping the policy here
makes every decision unit-testable without touching a real disk.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

MANIFEST_NAME = "MANIFEST.json"

# Conservative defaults; the operator overrides via settings.evidence.*
DEFAULT_RESERVE_MB = 512
DEFAULT_MAX_BUNDLES = 50
DEFAULT_MAX_TOTAL_MB = 2048
DEFAULT_WINDOW_MINUTES = 60

# Nonce is reduced to bare alphanumerics so bundle_id() output always satisfies
# is_valid_bundle_id() — even for a non-hex nonce.
_ID_SAFE = re.compile(r"[^A-Za-z0-9]")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bundle_id(created: float, nonce: str) -> str:
    """A filesystem-safe, sortable bundle id: evidence-<UTC>-<nonce>."""
    stamp = datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_nonce = _ID_SAFE.sub("", nonce)[:12] or "0"
    return f"evidence-{stamp}-{safe_nonce}"


def is_valid_bundle_id(name: str) -> bool:
    """Guard against path traversal: only accept our own id shape."""
    return bool(re.fullmatch(r"evidence-\d{8}T\d{6}Z-[A-Za-z0-9]{1,12}", name or ""))


def build_manifest(bid: str, created: float, files: dict[str, bytes],
                   meta: dict | None = None) -> dict:
    """Manifest listing each file's SHA-256 + size, plus a single bundle_digest
    over the sorted per-file hashes so the whole bundle is tamper-evident.

    files: filename -> raw bytes (the manifest itself is NOT one of them).
    """
    entries: dict[str, dict] = {}
    for name in sorted(files):
        blob = files[name]
        entries[name] = {"sha256": sha256_hex(blob), "bytes": len(blob)}
    # Digest over "name:hash" lines — order-independent, content-sensitive.
    joined = "\n".join(f"{n}:{entries[n]['sha256']}" for n in sorted(entries))
    bundle_digest = sha256_hex(joined.encode())
    return {
        "bundle_id": bid,
        "created": round(created, 3),
        "created_iso": datetime.fromtimestamp(created, tz=timezone.utc).isoformat(timespec="seconds"),
        "files": entries,
        "bundle_digest": bundle_digest,
        "meta": meta or {},
    }


def verify_manifest(manifest: dict, files: dict[str, bytes]) -> bool:
    """True iff every file hash matches and the bundle_digest recomputes.
    `files` must be the same filename->bytes map (excluding the manifest)."""
    entries = manifest.get("files", {})
    if set(entries) != set(files):
        return False
    for name, blob in files.items():
        if entries[name].get("sha256") != sha256_hex(blob):
            return False
    joined = "\n".join(f"{n}:{entries[n]['sha256']}" for n in sorted(entries))
    return sha256_hex(joined.encode()) == manifest.get("bundle_digest")


def disk_reserve_ok(free_bytes: int, incoming_bytes: int, reserve_bytes: int) -> bool:
    """Whether writing `incoming_bytes` keeps free space at/above the reserve.
    Refuses the snapshot when it would push the partition below the hard floor."""
    return (free_bytes - incoming_bytes) >= reserve_bytes


def select_for_rotation(bundles: list[dict], *, max_bundles: int,
                        max_total_bytes: int) -> list[str]:
    """Given existing bundles (each {id, created, bytes}), return the ids to
    delete — oldest first — so that at most `max_bundles` remain and their total
    size is within `max_total_bytes`. Pure: the caller does the deletion."""
    ordered = sorted(bundles, key=lambda b: b.get("created", 0))  # oldest first
    keep = list(ordered)
    doomed: list[str] = []

    # Count cap: drop oldest until within max_bundles.
    while max_bundles > 0 and len(keep) > max_bundles:
        doomed.append(keep.pop(0)["id"])

    # Size cap: drop oldest until total is within max_total_bytes.
    if max_total_bytes > 0:
        total = sum(b.get("bytes", 0) for b in keep)
        while keep and total > max_total_bytes:
            victim = keep.pop(0)
            doomed.append(victim["id"])
            total -= victim.get("bytes", 0)
    return doomed


def policy(evidence_cfg: dict | None) -> dict:
    """Normalise the settings.evidence section into concrete numbers, applying
    defaults and clamping to sane bounds."""
    cfg = evidence_cfg or {}

    def num(key, default, lo, hi):
        val = cfg.get(key, default)
        try:
            val = float(val)
        except (TypeError, ValueError):
            val = default
        return max(lo, min(val, hi))

    return {
        "reserve_bytes": int(num("reserve_mb", DEFAULT_RESERVE_MB, 0, 1_000_000) * 1024 * 1024),
        "max_bundles": int(num("max_bundles", DEFAULT_MAX_BUNDLES, 1, 100_000)),
        "max_total_bytes": int(num("max_total_mb", DEFAULT_MAX_TOTAL_MB, 1, 10_000_000) * 1024 * 1024),
        "window_minutes": int(num("window_minutes", DEFAULT_WINDOW_MINUTES, 5, 1440)),
    }
