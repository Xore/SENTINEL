"""Tests for collector.pki.enroll — CSR generation, HTTP enroll, file writes."""
from __future__ import annotations

import email.utils
import stat
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiohttp
import collector.pki.enroll as enroll_module
import pytest
from collector.config import load_settings
from collector.pki.enroll import (
    CA_FILENAME,
    CERT_FILENAME,
    KEY_FILENAME,
    EnrollmentError,
    ensure_enrolled,
    is_enrolled,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

_MALFORMED_PEM = "-----BEGIN CERTIFICATE-----\nnotvalid\n-----END CERTIFICATE-----\n"


class _FakeResponse:
    def __init__(
        self,
        status: int,
        json_body: object = None,
        text_body: str = "",
        headers: dict[str, str] | None = None,
    ):
        self.status = status
        self._json = json_body
        self._text = text_body
        self.headers = headers or {}

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def json(self) -> object:
        return self._json

    async def text(self) -> str:
        return self._text


class _FakeSession:
    """Queues canned responses; raises if called more times than queued.

    A queued item may be a `_FakeResponse` (returned as-is), a
    `BaseException` instance (raised, simulating a network/timeout error),
    or a callable taking the request's JSON payload and returning a
    `_FakeResponse` — used to mint a leaf certificate bound to the actual
    CSR's public key, since `ensure_enrolled` now parses and verifies the
    returned certificate before writing it to disk.
    """

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url: str, json: dict, headers: dict) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(json)
        return item


def _mint_leaf_cert(
    csr_pem: str, *, site_id: str, collector_id: str, public_key: Any = None
) -> str:
    """Stand in for the backend's CA signing step: binds a certificate to
    the CSR's own public key (unless `public_key` overrides it, to
    simulate a key-mismatch response) and a SPIFFE URI SAN for
    site_id/collector_id (which may deliberately not match the real
    request, to simulate an identity-mismatch response). Signature/chain
    validity against a CA isn't checked by the collector yet — that's
    C1-01's production enrollment integration — so a throwaway self-signed
    key is enough; only the public key and URI SAN matter here (see
    `_verify_certificate_identity` in collector/pki/enroll.py).
    """
    csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
    bound_key = public_key if public_key is not None else csr.public_key()
    signing_key = ec.generate_private_key(ec.SECP256R1())
    uri = f"spiffe://sentinel.local/sites/{site_id}/collectors/{collector_id}"
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(csr.subject)
        .public_key(bound_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.UniformResourceIdentifier(uri)]), critical=False
        )
        .sign(signing_key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _mint_ca_cert() -> str:
    """A minimal self-signed certificate standing in for the backend's CA
    cert in the enroll response. `ensure_enrolled` only parses (not
    chain-verifies) the CA PEM (Codex review 2 — see
    docs/guides/AGENT-COORDINATION.md), so a throwaway self-signed cert is
    a well-formed enough stand-in.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


_FAKE_CA_PEM = _mint_ca_cert()


def _ok_response(
    site_id: str = "site-a", collector_id: str = "node-1"
) -> Callable[[dict], _FakeResponse]:
    def _factory(payload: dict) -> _FakeResponse:
        cert_pem = _mint_leaf_cert(payload["csr_pem"], site_id=site_id, collector_id=collector_id)
        return _FakeResponse(
            200, json_body={"certificate_pem": cert_pem, "ca_certificate_pem": _FAKE_CA_PEM}
        )

    return _factory


@pytest.fixture
def enroll_settings(tmp_path):
    return load_settings(
        collector_id="node-1",
        site_id="site-a",
        backend={"pki_dir": str(tmp_path / "pki"), "retry_max": 2, "retry_backoff_s": 0.001},
    )


@pytest.fixture
def pre_enrolled_pki_dir(enroll_settings):
    """Pre-populate the PKI dir so ensure_enrolled sees it as already enrolled."""
    pki_dir = Path(enroll_settings.backend.pki_dir)
    pki_dir.mkdir(parents=True)
    for name in (KEY_FILENAME, CERT_FILENAME, CA_FILENAME):
        (pki_dir / name).write_text("preexisting")
    return pki_dir


class TestIsEnrolled:
    def test_false_when_missing(self, tmp_path):
        assert is_enrolled(tmp_path / "pki") is False

    def test_true_when_all_three_present(self, tmp_path):
        d = tmp_path / "pki"
        d.mkdir()
        for name in (KEY_FILENAME, CERT_FILENAME, CA_FILENAME):
            (d / name).write_text("x")
        assert is_enrolled(d) is True

    def test_false_when_partial(self, tmp_path):
        d = tmp_path / "pki"
        d.mkdir()
        (d / KEY_FILENAME).write_text("x")
        assert is_enrolled(d) is False


class TestEnsureEnrolled:
    async def test_writes_files_on_success(self, enroll_settings):
        session = _FakeSession([_ok_response()])
        await ensure_enrolled(enroll_settings, session=session)

        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert (pki_dir / KEY_FILENAME).is_file()
        assert (pki_dir / CERT_FILENAME).read_text().startswith("-----BEGIN CERTIFICATE-----")
        assert (pki_dir / CA_FILENAME).read_text().startswith("-----BEGIN CERTIFICATE-----")

        key_mode = stat.S_IMODE((pki_dir / KEY_FILENAME).stat().st_mode)
        if sys.platform == "win32":
            # os.chmod on Windows only toggles FILE_ATTRIBUTE_READONLY — it
            # cannot restrict access to the owner the way POSIX 0600 does,
            # and CPython's stat() emulation always reports rw for
            # user/group/other alike once a file isn't read-only. Since
            # pki/enroll.py's mode=0o600 has a write bit set, the file ends
            # up NOT read-only, so the real, honest Windows expectation is
            # 0o666 — asserting 0o600 here would just be asserting a POSIX
            # fact the platform cannot produce. True owner-only protection
            # on Windows needs an explicit ACL, not chmod (tracked as a
            # platform gap, not fixed by this test).
            assert key_mode == 0o666
        else:
            assert key_mode == 0o600

    async def test_sends_collector_and_site_id(self, enroll_settings):
        session = _FakeSession([_ok_response()])
        await ensure_enrolled(enroll_settings, session=session)

        assert session.calls[0]["json"]["collector_id"] == "node-1"
        assert session.calls[0]["json"]["site_id"] == "site-a"
        assert "csr_pem" in session.calls[0]["json"]
        assert "Authorization" not in session.calls[0]["headers"]

    async def test_sends_bootstrap_token_header(self, tmp_path):
        settings = load_settings(
            collector_id="node-1",
            backend={"pki_dir": str(tmp_path / "pki"), "bootstrap_token": "s3cr3t"},
        )
        # site_id defaults to "default" when not passed to load_settings.
        session = _FakeSession([_ok_response(site_id="default")])
        await ensure_enrolled(settings, session=session)

        assert session.calls[0]["headers"]["Authorization"] == "Bearer s3cr3t"

    async def test_skips_if_already_enrolled(self, enroll_settings, pre_enrolled_pki_dir):
        session = _FakeSession([])  # would raise IndexError if called
        await ensure_enrolled(enroll_settings, session=session)

        assert (pre_enrolled_pki_dir / KEY_FILENAME).read_text() == "preexisting"
        assert session.calls == []

    async def test_retries_then_succeeds(self, enroll_settings):
        session = _FakeSession([_FakeResponse(500, text_body="oops"), _ok_response()])
        await ensure_enrolled(enroll_settings, session=session)

        assert len(session.calls) == 2
        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert (pki_dir / CERT_FILENAME).is_file()

    async def test_raises_after_max_retries(self, enroll_settings):
        # retry_max=2 -> 3 total attempts, all failing
        session = _FakeSession([_FakeResponse(500, text_body="e1")] * 3)
        with pytest.raises(EnrollmentError):
            await ensure_enrolled(enroll_settings, session=session)

        assert len(session.calls) == 3
        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert not (pki_dir / CERT_FILENAME).exists()

    async def test_malformed_response_raises(self, enroll_settings):
        session = _FakeSession([_FakeResponse(200, json_body={"unexpected": "shape"})] * 3)
        with pytest.raises(EnrollmentError):
            await ensure_enrolled(enroll_settings, session=session)


class TestEnsureEnrolledFailureModes:
    """S1-02 requirement 3 + Q-1's resolution: reused/invalid token,
    malformed cert/CA data, timeout/network-error, terminal-vs-retryable
    status classification, Retry-After handling, and certificate
    identity/key mismatch. Q-1 (docs/guides/AGENT-COORDINATION.md) settled
    the two previously-open contract questions: terminal statuses fail
    fast (no identity-echo field is added — the certificate itself is the
    identity authority, verified client-side instead).
    """

    async def test_invalid_or_reused_token_status_fails_immediately(self, enroll_settings):
        # 401 is a terminal status (Q-1): retrying an invalid/reused token
        # against the same request can't succeed, so exactly one attempt is
        # made — unlike the pre-Q-1 behavior, which retried it 3 times.
        session = _FakeSession([_FakeResponse(401, text_body="invalid or reused token")] * 3)
        with pytest.raises(EnrollmentError, match="401"):
            await ensure_enrolled(enroll_settings, session=session)
        assert len(session.calls) == 1
        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert not (pki_dir / CERT_FILENAME).exists()

    @pytest.mark.parametrize("status", [400, 403, 404, 409, 422])
    async def test_terminal_status_fails_immediately_without_retry(self, enroll_settings, status):
        # Mirrors enroll.py's _RETRYABLE_STATUSES (Q-1's decision): these
        # reject the request itself, not a transient condition, so exactly
        # one attempt is made even though retry_max allows 3.
        session = _FakeSession([_FakeResponse(status, text_body="rejected")] * 3)
        with pytest.raises(EnrollmentError, match=str(status)):
            await ensure_enrolled(enroll_settings, session=session)
        assert len(session.calls) == 1
        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert not (pki_dir / CERT_FILENAME).exists()

    @pytest.mark.parametrize("status", [405, 410, 415])
    async def test_unlisted_status_fails_immediately_without_retry(self, enroll_settings, status):
        # Codex review 2: retry classification is an allowlist
        # (_RETRYABLE_STATUSES = {408, 425, 429} | 5xx), not a denylist of
        # terminal statuses — a status that isn't explicitly listed either
        # way (405/410/415 here) must still fail fast, not silently retry.
        session = _FakeSession([_FakeResponse(status, text_body="rejected")] * 3)
        with pytest.raises(EnrollmentError, match=str(status)):
            await ensure_enrolled(enroll_settings, session=session)
        assert len(session.calls) == 1
        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert not (pki_dir / CERT_FILENAME).exists()

    async def test_retryable_status_honors_retry_after_header(self, enroll_settings, monkeypatch):
        sleeps: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(enroll_module.asyncio, "sleep", _fake_sleep)

        session = _FakeSession(
            [
                _FakeResponse(429, text_body="slow down", headers={"Retry-After": "2.5"}),
                _ok_response(),
            ]
        )
        await ensure_enrolled(enroll_settings, session=session)

        assert sleeps == [2.5]
        assert len(session.calls) == 2

    async def test_retryable_status_without_retry_after_uses_configured_backoff(
        self, enroll_settings, monkeypatch
    ):
        sleeps: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(enroll_module.asyncio, "sleep", _fake_sleep)

        # 503 has no Retry-After header, so it must fall back to the
        # configured exponential backoff (retry_backoff_s=0.001 * 2**0),
        # not silently skip the wait like a missing/None value might.
        session = _FakeSession([_FakeResponse(503, text_body="unavailable"), _ok_response()])
        await ensure_enrolled(enroll_settings, session=session)

        assert sleeps == [pytest.approx(0.001)]

    async def test_retry_after_http_date_form_is_honored(self, enroll_settings, monkeypatch):
        # RFC 9110 §10.2.3's second Retry-After form: an HTTP-date rather
        # than delay-seconds. _utcnow() is monkeypatched so "5 seconds from
        # now" is deterministic instead of depending on real wall-clock
        # timing between header construction and the parser's own call.
        fixed_now = datetime(2030, 1, 1, tzinfo=UTC)
        monkeypatch.setattr(enroll_module, "_utcnow", lambda: fixed_now)

        sleeps: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(enroll_module.asyncio, "sleep", _fake_sleep)

        http_date = email.utils.format_datetime(fixed_now + timedelta(seconds=5), usegmt=True)
        session = _FakeSession(
            [
                _FakeResponse(503, text_body="unavailable", headers={"Retry-After": http_date}),
                _ok_response(),
            ]
        )
        await ensure_enrolled(enroll_settings, session=session)

        assert sleeps == [pytest.approx(5.0, abs=0.01)]

    async def test_retry_after_non_finite_value_falls_back_to_configured_backoff(
        self, enroll_settings, monkeypatch
    ):
        sleeps: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(enroll_module.asyncio, "sleep", _fake_sleep)

        # "inf" parses as a float but must be rejected, not honored as an
        # unbounded wait — falls back to configured exponential backoff.
        session = _FakeSession(
            [_FakeResponse(503, text_body="x", headers={"Retry-After": "inf"}), _ok_response()]
        )
        await ensure_enrolled(enroll_settings, session=session)

        assert sleeps == [pytest.approx(0.001)]

    async def test_retry_after_invalid_value_falls_back_to_configured_backoff(
        self, enroll_settings, monkeypatch
    ):
        sleeps: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(enroll_module.asyncio, "sleep", _fake_sleep)

        session = _FakeSession(
            [
                _FakeResponse(503, text_body="x", headers={"Retry-After": "not-a-real-value"}),
                _ok_response(),
            ]
        )
        await ensure_enrolled(enroll_settings, session=session)

        assert sleeps == [pytest.approx(0.001)]

    async def test_retry_after_huge_value_is_capped(self, enroll_settings, monkeypatch):
        sleeps: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(enroll_module.asyncio, "sleep", _fake_sleep)

        session = _FakeSession(
            [
                _FakeResponse(503, text_body="x", headers={"Retry-After": "999999"}),
                _ok_response(),
            ]
        )
        await ensure_enrolled(enroll_settings, session=session)

        # Codex-approved cap (enroll.py's _MAX_BACKOFF_S = 300.0).
        assert sleeps == [300.0]

    async def test_configured_backoff_is_capped(self, tmp_path, monkeypatch):
        settings = load_settings(
            collector_id="node-1",
            site_id="site-a",
            backend={
                "pki_dir": str(tmp_path / "pki"),
                "retry_max": 1,
                "retry_backoff_s": 1000.0,
            },
        )
        sleeps: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(enroll_module.asyncio, "sleep", _fake_sleep)

        session = _FakeSession([_FakeResponse(503, text_body="x"), _ok_response()])
        await ensure_enrolled(settings, session=session)

        # Without a Retry-After header, the configured exponential backoff
        # (1000.0 * 2**0) must still be clamped to _MAX_BACKOFF_S.
        assert sleeps == [300.0]

    async def test_public_key_mismatch_raises_and_does_not_write_files(self, enroll_settings):
        unrelated_key = ec.generate_private_key(ec.SECP256R1())

        def _wrong_key_response(payload: dict) -> _FakeResponse:
            cert_pem = _mint_leaf_cert(
                payload["csr_pem"],
                site_id="site-a",
                collector_id="node-1",
                public_key=unrelated_key.public_key(),
            )
            return _FakeResponse(
                200, json_body={"certificate_pem": cert_pem, "ca_certificate_pem": _FAKE_CA_PEM}
            )

        session = _FakeSession([_wrong_key_response])
        with pytest.raises(EnrollmentError, match="public key"):
            await ensure_enrolled(enroll_settings, session=session)

        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert not (pki_dir / CERT_FILENAME).exists()
        assert not (pki_dir / KEY_FILENAME).exists()

    async def test_identity_mismatch_raises_and_does_not_write_files(self, enroll_settings):
        def _wrong_identity_response(payload: dict) -> _FakeResponse:
            cert_pem = _mint_leaf_cert(
                payload["csr_pem"], site_id="site-a", collector_id="some-other-node"
            )
            return _FakeResponse(
                200, json_body={"certificate_pem": cert_pem, "ca_certificate_pem": _FAKE_CA_PEM}
            )

        session = _FakeSession([_wrong_identity_response])
        with pytest.raises(EnrollmentError, match="URI SAN"):
            await ensure_enrolled(enroll_settings, session=session)

        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert not (pki_dir / CERT_FILENAME).exists()
        assert not (pki_dir / KEY_FILENAME).exists()

    async def test_malformed_leaf_certificate_raises_and_does_not_write_files(
        self, enroll_settings
    ):
        # Codex review 2: the leaf must be parsed (not just trusted as an
        # opaque string) before anything is persisted.
        def _malformed_leaf_response(payload: dict) -> _FakeResponse:  # pylint: disable=unused-argument
            return _FakeResponse(
                200,
                json_body={"certificate_pem": _MALFORMED_PEM, "ca_certificate_pem": _FAKE_CA_PEM},
            )

        session = _FakeSession([_malformed_leaf_response])
        with pytest.raises(EnrollmentError, match="malformed leaf certificate"):
            await ensure_enrolled(enroll_settings, session=session)

        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert not (pki_dir / CERT_FILENAME).exists()
        assert not (pki_dir / KEY_FILENAME).exists()

    async def test_malformed_ca_certificate_raises_and_does_not_write_files(self, enroll_settings):
        # Codex review 2: previously only the leaf was parsed, so a
        # malformed CA PEM was silently accepted and written to disk.
        def _malformed_ca_response(payload: dict) -> _FakeResponse:
            cert_pem = _mint_leaf_cert(payload["csr_pem"], site_id="site-a", collector_id="node-1")
            return _FakeResponse(
                200, json_body={"certificate_pem": cert_pem, "ca_certificate_pem": _MALFORMED_PEM}
            )

        session = _FakeSession([_malformed_ca_response])
        with pytest.raises(EnrollmentError, match="malformed CA certificate"):
            await ensure_enrolled(enroll_settings, session=session)

        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert not (pki_dir / CERT_FILENAME).exists()
        assert not (pki_dir / KEY_FILENAME).exists()

    async def test_malformed_response_missing_certificate_pem(self, enroll_settings):
        session = _FakeSession([_FakeResponse(200, json_body={"ca_certificate_pem": "x"})] * 3)
        with pytest.raises(EnrollmentError, match="malformed"):
            await ensure_enrolled(enroll_settings, session=session)

    async def test_malformed_response_missing_ca_certificate_pem(self, enroll_settings):
        session = _FakeSession([_FakeResponse(200, json_body={"certificate_pem": "x"})] * 3)
        with pytest.raises(EnrollmentError, match="malformed"):
            await ensure_enrolled(enroll_settings, session=session)

    async def test_malformed_response_non_dict_body(self, enroll_settings):
        # A bare list is valid JSON but not a mapping — _post_csr's
        # data["certificate_pem"] subscript hits TypeError, not KeyError.
        session = _FakeSession([_FakeResponse(200, json_body=["unexpected", "shape"])] * 3)
        with pytest.raises(EnrollmentError, match="malformed"):
            await ensure_enrolled(enroll_settings, session=session)

    async def test_network_error_retries_then_succeeds(self, enroll_settings):
        session = _FakeSession(
            [aiohttp.ClientConnectionError("connection refused"), _ok_response()]
        )
        await ensure_enrolled(enroll_settings, session=session)
        assert len(session.calls) == 2
        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert (pki_dir / CERT_FILENAME).is_file()

    async def test_network_timeout_raises_after_max_retries(self, enroll_settings):
        session = _FakeSession([aiohttp.ServerTimeoutError("timed out")] * 3)
        with pytest.raises(EnrollmentError):
            await ensure_enrolled(enroll_settings, session=session)
        assert len(session.calls) == 3
        pki_dir = Path(enroll_settings.backend.pki_dir)
        assert not (pki_dir / CERT_FILENAME).exists()
