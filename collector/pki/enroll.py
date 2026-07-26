"""PKI enrollment — generate a keypair + CSR, POST to the backend enroll
endpoint, and write the signed leaf cert and CA cert to the local PKI
directory.

This implements the custom CSR-POST protocol chosen over RFC 7030 EST for a
small, closed collector fleet — see
``docs/gap-analysis/gap-analysis-collector-vs-standalone.md`` §3 for the
rationale. ``pki/renew.py`` (a later phase) reuses the same wire format.
"""
from __future__ import annotations

import asyncio
import email.utils
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from collector.config import CollectorSettings

log = structlog.get_logger()

KEY_FILENAME = "collector.key"
CERT_FILENAME = "collector.crt"
CA_FILENAME = "ca.crt"


class EnrollmentError(Exception):
    """Raised when PKI enrollment fails after exhausting retries, or
    immediately for a terminal rejection or an identity/key mismatch."""


# Only these statuses (plus network errors/timeouts, handled separately) are
# transient enough to retry — everything else, including any status not
# explicitly listed here (e.g. 405, 410, 415), is treated as a terminal
# rejection of the request itself and fails immediately. Per Q-1's decision
# and Codex review 2 in docs/guides/AGENT-COORDINATION.md: an allowlist of
# retryable statuses, not a denylist of terminal ones — an unlisted status
# must fail fast, not silently retry.
_RETRYABLE_STATUSES = frozenset({408, 425, 429}) | frozenset(range(500, 600))

# Cap on both a server-directed (Retry-After) and a configured exponential
# backoff delay — Codex-approved bound so a malicious/broken Retry-After
# value or a large retry_backoff_s/retry_max combination can't stall
# enrollment indefinitely.
_MAX_BACKOFF_S = 300.0

# Must match backend/ingest/internal/identity.go's trustDomain — the
# server is the source of truth for this value.
_SPIFFE_TRUST_DOMAIN = "sentinel.local"


class _HttpEnrollError(EnrollmentError):
    """A non-200 enroll response. Carries `status`/`retry_after` so the
    retry loop can classify it without re-parsing the message text."""

    def __init__(self, message: str, *, status: int, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header per RFC 9110 §10.2.3: either form.

    - delay-seconds (e.g. ``"120"``)
    - HTTP-date (e.g. ``"Tue, 29 Oct 2030 16:04:06 GMT"``)

    Returns ``None`` (caller falls back to configured backoff) for a
    missing/unparseable header or a non-finite/negative delay — a
    non-finite value like ``"inf"`` or a date in the past must not be
    honored as-is. Otherwise the result is clamped to ``_MAX_BACKOFF_S``.
    """
    if value is None:
        return None

    try:
        seconds = float(value)
    except ValueError:
        try:
            target = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        seconds = (target - _utcnow()).total_seconds()

    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, _MAX_BACKOFF_S)


def is_enrolled(pki_dir: str | os.PathLike[str]) -> bool:
    """True if a leaf cert/key/CA already exist locally."""
    d = Path(pki_dir)
    return all((d / name).is_file() for name in (KEY_FILENAME, CERT_FILENAME, CA_FILENAME))


def _generate_private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _build_csr_pem(
    private_key: ec.EllipticCurvePrivateKey, collector_id: str, site_id: str
) -> str:
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, collector_id),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, site_id),
        ]
    )
    csr = x509.CertificateSigningRequestBuilder().subject_name(subject).sign(
        private_key, hashes.SHA256()
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _write_pem(path: Path, pem_text: str, *, mode: int) -> None:
    path.write_text(pem_text, encoding="ascii")
    os.chmod(path, mode)


async def _post_csr(
    session: aiohttp.ClientSession, settings: CollectorSettings, csr_pem: str
) -> tuple[str, str]:
    """POST the CSR to the enroll endpoint. Returns (cert_pem, ca_cert_pem)."""
    headers = {}
    if settings.backend.bootstrap_token:
        headers["Authorization"] = f"Bearer {settings.backend.bootstrap_token}"
    payload = {
        "collector_id": settings.collector_id,
        "site_id": settings.site_id,
        "csr_pem": csr_pem,
    }
    async with session.post(settings.backend.enroll_url, json=payload, headers=headers) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise _HttpEnrollError(
                f"enroll endpoint returned {resp.status}: {body[:500]}",
                status=resp.status,
                retry_after=_parse_retry_after(resp.headers.get("Retry-After")),
            )
        data = await resp.json()
    try:
        return data["certificate_pem"], data["ca_certificate_pem"]
    except (KeyError, TypeError) as exc:
        raise EnrollmentError(f"malformed enroll response: {data!r}") from exc


def _public_key_der(public_key: Any) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _verify_certificate_identity(
    cert_pem: str,
    ca_pem: str,
    private_key: ec.EllipticCurvePrivateKey,
    site_id: str,
    collector_id: str,
) -> None:
    """Confirm the enrolled leaf certificate is bound to *our* key and
    identity before it's trusted enough to persist to disk, and that the
    accompanying CA certificate is at least well-formed. The leaf — not an
    unauthenticated response field — is the identity authority (Q-1);
    mirrors the server-side check in
    backend/ingest/internal/identity.{FromCertificate,SPIFFEURI}. Full
    leaf-signature/chain verification against the CA is C1-01's production
    enrollment integration, not this check — this only rejects a leaf or CA
    that doesn't even parse as X.509.
    """
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
    except ValueError as exc:
        raise EnrollmentError(f"malformed leaf certificate: {exc}") from exc
    try:
        x509.load_pem_x509_certificate(ca_pem.encode("ascii"))
    except ValueError as exc:
        raise EnrollmentError(f"malformed CA certificate: {exc}") from exc

    if _public_key_der(cert.public_key()) != _public_key_der(private_key.public_key()):
        raise EnrollmentError("enrolled certificate's public key does not match our private key")

    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        uris = san.value.get_values_for_type(x509.UniformResourceIdentifier)
    except x509.ExtensionNotFound:
        uris = []

    expected = f"spiffe://{_SPIFFE_TRUST_DOMAIN}/sites/{site_id}/collectors/{collector_id}"
    if uris != [expected]:
        raise EnrollmentError(
            f"enrolled certificate URI SAN {uris!r} does not match expected identity {expected!r}"
        )


async def ensure_enrolled(
    settings: CollectorSettings, *, session: aiohttp.ClientSession | None = None
) -> None:
    """Enroll this collector's PKI identity if it hasn't been already.

    Idempotent: a no-op if ``collector.key``/``collector.crt``/``ca.crt``
    already exist under ``backend.pki_dir``. Only ``_RETRYABLE_STATUSES``
    (408/425/429/5xx) plus network errors/timeouts retry, up to
    ``backend.retry_max`` times; every other status — including one not
    explicitly listed — fails immediately. A retry honors a Retry-After
    response header (delay-seconds or HTTP-date) when present, otherwise
    backs off exponentially from ``backend.retry_backoff_s``; either delay
    is capped at ``_MAX_BACKOFF_S``. The returned certificate's public key
    and identity URI SAN are verified against ours, and the CA PEM is
    confirmed to at least parse, before anything is written to disk.
    """
    pki_dir = Path(settings.backend.pki_dir)
    bound_log = log.bind(collector_id=settings.collector_id, site_id=settings.site_id)

    if is_enrolled(pki_dir):
        bound_log.info("pki.enroll.skipped_already_enrolled", pki_dir=str(pki_dir))
        return

    await asyncio.to_thread(pki_dir.mkdir, parents=True, exist_ok=True)
    private_key = _generate_private_key()
    csr_pem = _build_csr_pem(private_key, settings.collector_id, settings.site_id)

    async def _retry_or_raise(
        exc: Exception, attempt: int, *, retry_after: float | None = None
    ) -> None:
        if attempt > settings.backend.retry_max:
            bound_log.error("pki.enroll.failed", error=str(exc), attempts=attempt)
            raise EnrollmentError(
                f"PKI enrollment failed after {attempt} attempts: {exc}"
            ) from exc
        backoff = (
            retry_after
            if retry_after is not None
            else settings.backend.retry_backoff_s * (2 ** (attempt - 1))
        )
        backoff = min(backoff, _MAX_BACKOFF_S)
        bound_log.warning(
            "pki.enroll.retry", error=str(exc), attempt=attempt, retry_in_s=backoff
        )
        await asyncio.sleep(backoff)

    owns_session = session is None
    active_session = session if session is not None else aiohttp.ClientSession()
    try:
        attempt = 0
        while True:
            try:
                cert_pem, ca_pem = await _post_csr(active_session, settings, csr_pem)
                break
            except _HttpEnrollError as exc:
                if exc.status not in _RETRYABLE_STATUSES:
                    bound_log.error("pki.enroll.rejected", status=exc.status, error=str(exc))
                    raise EnrollmentError(str(exc)) from exc
                attempt += 1
                await _retry_or_raise(exc, attempt, retry_after=exc.retry_after)
            except (aiohttp.ClientError, EnrollmentError) as exc:
                attempt += 1
                await _retry_or_raise(exc, attempt)
    finally:
        if owns_session:
            await active_session.close()

    _verify_certificate_identity(
        cert_pem, ca_pem, private_key, settings.site_id, settings.collector_id
    )

    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")

    await asyncio.to_thread(_write_pem, pki_dir / KEY_FILENAME, key_pem, mode=0o600)
    await asyncio.to_thread(_write_pem, pki_dir / CERT_FILENAME, cert_pem, mode=0o644)
    await asyncio.to_thread(_write_pem, pki_dir / CA_FILENAME, ca_pem, mode=0o644)

    bound_log.info("pki.enroll.complete", pki_dir=str(pki_dir))
