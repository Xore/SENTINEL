"""Crash-safe telemetry envelope — the immutable unit the cold queue stores.

Version `1` is frozen: `event_id`, `site_id`, `collector_id`, `observed_at`,
`created_at`, `expires_at`, `attempt_count` (an exact non-negative integer —
a count, so neither `1.5` nor `True` is one), `content_type`, opaque `payload`
bytes, and a SHA-256 `checksum` computed from `payload` at construction.
Serialization (`to_bytes`/`from_bytes`) is deterministic sorted-key JSON with
base64-encoded payload bytes, and `from_bytes` rejects any version other than
the one this module implements.

Standalone in this claim: no queue, transport, or registration wiring. The
SQLite cold queue that stores these envelopes is `collector.store.sqlite_queue`;
LMDB hot-tier and transport integration are later, separately reviewed claims.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

ENVELOPE_VERSION = 1

# Mirrors collector.config's ADR 0009 DNS-label rule (lowercase RFC 1123
# label, <=63 chars). Duplicated here rather than imported: config.py is
# frozen/out of scope for this claim.
_DNS_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class EnvelopeError(ValueError):
    """An envelope is malformed, corrupted, or of an unsupported version."""


def _validate_dns_label(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _DNS_LABEL_RE.match(value):
        raise EnvelopeError(f"{field_name} must be a lowercase RFC 1123 DNS label: got {value!r}")
    return value


def _validate_event_id(value: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise EnvelopeError(f"event_id must be a valid UUID: got {value!r}") from exc
    return str(parsed)


def _validate_exact_int(value: object, field_name: str) -> int:
    """Require a true `int`.

    `bool` is an `int` subclass and JSON floats compare equal to integers
    (`1.0 == 1`), so both would otherwise pass an `isinstance`/equality check
    and make a count or a version non-canonical.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise EnvelopeError(
            f"{field_name} must be an exact integer, not {type(value).__name__}: got {value!r}"
        )
    return value


def _require_aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EnvelopeError(f"{field_name} must be an aware UTC datetime: got {value!r}")
    if value.utcoffset() != UTC.utcoffset(None):
        raise EnvelopeError(
            f"{field_name} must be UTC: got offset {value.utcoffset()} for {value!r}"
        )
    return value


@dataclass(frozen=True)
class Envelope:  # pylint: disable=too-many-instance-attributes
    """One immutable queued telemetry event. Construct directly or via
    `from_bytes`; every field is validated in `__post_init__`, so a
    successfully constructed instance is always well-formed.
    """

    event_id: str
    site_id: str
    collector_id: str
    observed_at: datetime
    created_at: datetime
    expires_at: datetime
    content_type: str
    payload: bytes
    attempt_count: int = 0
    version: int = ENVELOPE_VERSION
    checksum: str = ""

    def __post_init__(self) -> None:
        if _validate_exact_int(self.version, "version") != ENVELOPE_VERSION:
            raise EnvelopeError(f"unsupported envelope version: {self.version!r}")
        object.__setattr__(self, "event_id", _validate_event_id(self.event_id))
        object.__setattr__(self, "site_id", _validate_dns_label(self.site_id, "site_id"))
        object.__setattr__(
            self, "collector_id", _validate_dns_label(self.collector_id, "collector_id")
        )
        _require_aware_utc(self.observed_at, "observed_at")
        _require_aware_utc(self.created_at, "created_at")
        _require_aware_utc(self.expires_at, "expires_at")
        if self.expires_at <= self.observed_at or self.expires_at <= self.created_at:
            raise EnvelopeError(
                "expires_at must be after both observed_at and created_at: "
                f"expires_at={self.expires_at!r}, observed_at={self.observed_at!r}, "
                f"created_at={self.created_at!r}"
            )
        if _validate_exact_int(self.attempt_count, "attempt_count") < 0:
            raise EnvelopeError(f"attempt_count must be non-negative: got {self.attempt_count!r}")
        if not isinstance(self.content_type, str) or not self.content_type:
            raise EnvelopeError(
                f"content_type must be a non-empty string: got {self.content_type!r}"
            )
        if not isinstance(self.payload, bytes):
            raise EnvelopeError(f"payload must be bytes: got {type(self.payload)!r}")
        object.__setattr__(self, "checksum", hashlib.sha256(self.payload).hexdigest())

    def verify_checksum(self) -> bool:
        """True if `checksum` matches a fresh digest of `payload`.

        Always true for an instance built via the constructor (the digest is
        computed there); meaningful after manual field surgery or when
        auditing a round-tripped instance.
        """
        return self.checksum == hashlib.sha256(self.payload).hexdigest()

    def with_attempt_incremented(self) -> Envelope:
        """A copy with `attempt_count + 1`. `Envelope` is frozen, so a
        failed delivery attempt is recorded via copy-on-write rather than
        in-place mutation.
        """
        return replace(self, attempt_count=self.attempt_count + 1)

    def to_bytes(self) -> bytes:
        """Deterministic serialization: sorted-key JSON, base64 payload."""
        obj = {
            "version": self.version,
            "event_id": self.event_id,
            "site_id": self.site_id,
            "collector_id": self.collector_id,
            "observed_at": self.observed_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "attempt_count": self.attempt_count,
            "content_type": self.content_type,
            "payload_b64": base64.b64encode(self.payload).decode("ascii"),
            "checksum": self.checksum,
        }
        return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> Envelope:
        """Inverse of `to_bytes`. Raises `EnvelopeError` for malformed
        bytes, an unsupported version, or a checksum that doesn't match the
        decoded payload (corruption between serialize and deserialize).
        """
        try:
            obj = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EnvelopeError(f"malformed envelope bytes: {exc}") from exc
        if not isinstance(obj, dict):
            raise EnvelopeError(f"envelope must decode to a JSON object: got {type(obj)!r}")

        version = obj.get("version")
        # Checked exactly here as well as in `__post_init__`: JSON's `1.0`
        # compares equal to `1`, so an inexact version must not slip past this
        # gate and be normalized on the way in.
        if isinstance(version, bool) or not isinstance(version, int):
            raise EnvelopeError(f"envelope version must be an exact integer: got {version!r}")
        if version != ENVELOPE_VERSION:
            raise EnvelopeError(f"unsupported envelope version: {version!r}")

        try:
            payload = base64.b64decode(obj["payload_b64"], validate=True)
            envelope = cls(
                event_id=obj["event_id"],
                site_id=obj["site_id"],
                collector_id=obj["collector_id"],
                observed_at=datetime.fromisoformat(obj["observed_at"]),
                created_at=datetime.fromisoformat(obj["created_at"]),
                expires_at=datetime.fromisoformat(obj["expires_at"]),
                attempt_count=obj["attempt_count"],
                content_type=obj["content_type"],
                payload=payload,
                version=version,
            )
        except EnvelopeError:
            # Already precise (and an `EnvelopeError` is a `ValueError`, so it
            # would otherwise be re-wrapped by the clause below).
            raise
        except KeyError as exc:
            raise EnvelopeError(f"missing envelope field: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise EnvelopeError(f"malformed envelope field: {exc}") from exc

        if obj.get("checksum") != envelope.checksum:
            raise EnvelopeError("envelope checksum mismatch — payload may be corrupted")
        return envelope
