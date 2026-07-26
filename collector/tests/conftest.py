"""Shared pytest fixtures for the collector test suite.

`isolate_env` runs for every test so a stray real ``COLLECTOR_*`` /
``BACKEND__*`` / ``WIFI__*`` env var on the dev machine can never leak into a
test's view of configuration.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from collector.config import load_settings
from collector.pki.enroll import CA_FILENAME, CERT_FILENAME, KEY_FILENAME

# Env prefixes that CollectorSettings reads. Any of these present in the real
# environment would perturb config tests, so they are cleared per-test.
_MANAGED_PREFIXES = ("COLLECTOR_", "SITE_", "SCAN_LEVEL_", "BACKEND__", "WIFI__",
                     "MTR__", "BCAST_MCAST__", "EBPF__", "ICMP__", "TCP__", "HTTP__",
                     "DNS__", "LOG_LEVEL", "DATA_DIR")


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch, tmp_path):
    for key in list(__import__("os").environ):
        if key.startswith(_MANAGED_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    # Never let a real ./.env on disk bleed in during tests.
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def settings():
    """A minimal valid CollectorSettings with all defaults."""
    return load_settings(collector_id="test-collector")


def _self_signed_pem(common_name: str) -> tuple[bytes, bytes]:
    """Return (key_pem, cert_pem) for a minimal self-signed EC certificate."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return key_pem, cert_pem


@pytest.fixture
def enrolled_pki_dir(tmp_path) -> Path:
    """A pki_dir populated with a real self-signed leaf cert/key + CA cert."""
    d = tmp_path / "pki"
    d.mkdir()
    leaf_key_pem, leaf_cert_pem = _self_signed_pem("node-1")
    _, ca_cert_pem = _self_signed_pem("test-ca")
    (d / KEY_FILENAME).write_bytes(leaf_key_pem)
    (d / CERT_FILENAME).write_bytes(leaf_cert_pem)
    (d / CA_FILENAME).write_bytes(ca_cert_pem)
    return d
