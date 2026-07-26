"""Tests for collector.store.envelope — the immutable versioned envelope."""
from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from collector.store.envelope import ENVELOPE_VERSION, Envelope, EnvelopeError


def _make(  # pylint: disable=too-many-arguments
    *,
    event_id: str | None = None,
    site_id: str = "site-a",
    collector_id: str = "collector-1",
    observed_at: datetime | None = None,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
    content_type: str = "application/x-otlp",
    payload: bytes = b"hello world",
    attempt_count: int = 0,
    version: int = ENVELOPE_VERSION,
) -> Envelope:
    now = observed_at or datetime.now(UTC)
    return Envelope(
        event_id=event_id or str(uuid.uuid4()),
        site_id=site_id,
        collector_id=collector_id,
        observed_at=now,
        created_at=created_at or now,
        expires_at=expires_at or now + timedelta(hours=1),
        content_type=content_type,
        payload=payload,
        attempt_count=attempt_count,
        version=version,
    )


class TestConstruction:
    def test_valid_envelope_computes_checksum(self):
        env = _make(payload=b"abc")
        assert len(env.checksum) == 64
        assert env.verify_checksum() is True

    def test_event_id_with_stray_whitespace_is_rejected(self):
        raw = "  " + str(uuid.uuid4()).upper()
        with pytest.raises(EnvelopeError, match="event_id"):
            _make(event_id=raw)

    def test_event_id_canonicalizes_case(self):
        raw = str(uuid.uuid4())
        env = _make(event_id=raw.upper())
        assert env.event_id == raw.lower()


class TestValidation:
    @pytest.mark.parametrize("bad", ["Site-A", "site_a", "-site", "site-", "a" * 64, ""])
    def test_rejects_invalid_site_id(self, bad):
        with pytest.raises(EnvelopeError, match="site_id"):
            _make(site_id=bad)

    @pytest.mark.parametrize("bad", ["Collector-1", "collector_1", ""])
    def test_rejects_invalid_collector_id(self, bad):
        with pytest.raises(EnvelopeError, match="collector_id"):
            _make(collector_id=bad)

    def test_rejects_non_uuid_event_id(self):
        with pytest.raises(EnvelopeError, match="event_id"):
            _make(event_id="not-a-uuid")

    def test_rejects_naive_datetime(self):
        naive = datetime.now()  # noqa: DTZ005 — intentionally naive for the test
        with pytest.raises(EnvelopeError, match="observed_at"):
            _make(observed_at=naive)

    def test_rejects_non_utc_offset(self):
        non_utc = datetime.now(timezone(timedelta(hours=5)))
        with pytest.raises(EnvelopeError, match="observed_at"):
            _make(observed_at=non_utc)

    def test_rejects_expires_at_before_observed_at(self):
        now = datetime.now(UTC)
        with pytest.raises(EnvelopeError, match="expires_at"):
            _make(observed_at=now, created_at=now, expires_at=now - timedelta(seconds=1))

    def test_rejects_expires_at_before_created_at(self):
        now = datetime.now(UTC)
        with pytest.raises(EnvelopeError, match="expires_at"):
            _make(observed_at=now - timedelta(hours=2), created_at=now, expires_at=now)

    def test_rejects_expires_at_equal_to_created_at(self):
        now = datetime.now(UTC)
        with pytest.raises(EnvelopeError, match="expires_at"):
            _make(observed_at=now, created_at=now, expires_at=now)

    def test_rejects_negative_attempt_count(self):
        with pytest.raises(EnvelopeError, match="attempt_count"):
            _make(attempt_count=-1)

    def test_rejects_empty_content_type(self):
        with pytest.raises(EnvelopeError, match="content_type"):
            _make(content_type="")

    def test_rejects_non_bytes_payload(self):
        with pytest.raises(EnvelopeError, match="payload"):
            _make(payload="not bytes")  # type: ignore[arg-type]

    def test_rejects_unsupported_version_at_construction(self):
        with pytest.raises(EnvelopeError, match="version"):
            _make(version=2)


class TestSerializationRoundTrip:
    def test_to_bytes_is_deterministic(self):
        env = _make()
        assert env.to_bytes() == env.to_bytes()

    def test_from_bytes_round_trips_exactly(self):
        env = _make()
        restored = Envelope.from_bytes(env.to_bytes())
        assert restored == env

    def test_identical_fields_serialize_identically(self):
        event_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        expires = now + timedelta(hours=1)
        env1 = _make(event_id=event_id, observed_at=now, created_at=now, expires_at=expires)
        env2 = _make(event_id=event_id, observed_at=now, created_at=now, expires_at=expires)
        assert env1.to_bytes() == env2.to_bytes()

    def test_to_bytes_base64_encodes_payload(self):
        env = _make(payload=b"\x00\x01\xff binary")
        obj = json.loads(env.to_bytes())
        assert base64.b64decode(obj["payload_b64"]) == b"\x00\x01\xff binary"


class TestChecksumCorruption:
    def test_corrupted_payload_bytes_are_rejected(self):
        env = _make(payload=b"the real payload")
        obj = json.loads(env.to_bytes())
        tampered_payload = base64.b64encode(b"a different payload").decode("ascii")
        obj["payload_b64"] = tampered_payload
        tampered = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with pytest.raises(EnvelopeError, match="checksum"):
            Envelope.from_bytes(tampered)

    def test_corrupted_checksum_field_is_rejected(self):
        env = _make()
        obj = json.loads(env.to_bytes())
        obj["checksum"] = "0" * 64
        tampered = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with pytest.raises(EnvelopeError, match="checksum"):
            Envelope.from_bytes(tampered)

    def test_verify_checksum_false_after_manual_payload_tamper(self):
        env = _make(payload=b"original")
        object.__setattr__(env, "payload", b"tampered")
        assert env.verify_checksum() is False


class TestUnknownVersion:
    def test_from_bytes_rejects_future_version(self):
        env = _make()
        obj = json.loads(env.to_bytes())
        obj["version"] = 2
        tampered = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with pytest.raises(EnvelopeError, match="version"):
            Envelope.from_bytes(tampered)

    def test_from_bytes_rejects_missing_version(self):
        env = _make()
        obj = json.loads(env.to_bytes())
        del obj["version"]
        tampered = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with pytest.raises(EnvelopeError, match="version"):
            Envelope.from_bytes(tampered)


class TestMalformedBytes:
    def test_from_bytes_rejects_non_json(self):
        with pytest.raises(EnvelopeError, match="malformed"):
            Envelope.from_bytes(b"not json at all")

    def test_from_bytes_rejects_non_utf8(self):
        with pytest.raises(EnvelopeError, match="malformed"):
            Envelope.from_bytes(b"\xff\xfe\x00\x01")

    def test_from_bytes_rejects_json_array(self):
        with pytest.raises(EnvelopeError, match="JSON object"):
            Envelope.from_bytes(b"[1, 2, 3]")

    def test_from_bytes_rejects_missing_field(self):
        env = _make()
        obj = json.loads(env.to_bytes())
        del obj["site_id"]
        tampered = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with pytest.raises(EnvelopeError, match="missing envelope field"):
            Envelope.from_bytes(tampered)

    def test_from_bytes_rejects_malformed_base64(self):
        env = _make()
        obj = json.loads(env.to_bytes())
        obj["payload_b64"] = "not-valid-base64!!!"
        tampered = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with pytest.raises(EnvelopeError, match="malformed envelope field"):
            Envelope.from_bytes(tampered)


class TestAttemptIncrement:
    def test_with_attempt_incremented_returns_new_instance(self):
        env = _make(attempt_count=0)
        updated = env.with_attempt_incremented()
        assert updated.attempt_count == 1
        assert env.attempt_count == 0
        assert updated is not env

    def test_with_attempt_incremented_preserves_checksum(self):
        env = _make(payload=b"stable payload")
        updated = env.with_attempt_incremented()
        assert updated.checksum == env.checksum

    def test_envelope_is_frozen(self):
        env = _make()
        with pytest.raises(AttributeError):
            env.attempt_count = 5  # type: ignore[misc]
