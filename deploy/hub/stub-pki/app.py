"""Dev-only stub PKI service for the local hub integration test.

NOT for production use — no bootstrap-token auth, no revocation, no HA. It
exists to unblock the Phase 1 "collector connects, enrolls, heartbeat lands
in VictoriaMetrics" integration test without a real hub PKI service.

Generates a throwaway CA and an otel-collector server certificate on first
startup (persisted to a shared volume), then signs collector enrollment
CSRs against that CA — matching the wire contract collector/pki/enroll.py
already implements: POST {collector_id, site_id, csr_pem} ->
{certificate_pem, ca_certificate_pem}.
"""
from __future__ import annotations

import datetime
import logging
import os
from pathlib import Path

from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stub-pki")

PKI_DIR = Path(os.environ.get("PKI_DIR", "/pki"))
CA_KEY_PATH = PKI_DIR / "ca.key"
CA_CERT_PATH = PKI_DIR / "ca.crt"
OTEL_KEY_PATH = PKI_DIR / "otel-collector.key"
OTEL_CERT_PATH = PKI_DIR / "otel-collector.crt"

# Server identity the otel-collector's OTLP receiver presents; must cover
# every hostname a client (host-side test collector, or a containerized one
# on the compose network) connects through.
OTEL_SERVER_SANS = ["localhost", "127.0.0.1", "otel-collector", "ingest"]

CA_VALIDITY = datetime.timedelta(days=3650)  # dev CA — 10 years, never rotated
LEAF_VALIDITY = datetime.timedelta(days=825)  # matches common CA/Browser Forum limits


def _generate_ca() -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "analyseLaptop dev CA (NOT FOR PRODUCTION)")]
    )
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + CA_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _generate_otel_server_cert(
    ca_key: ec.EllipticCurvePrivateKey, ca_cert: x509.Certificate
) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "otel-collector")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + LEAF_VALIDITY)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(s) for s in OTEL_SERVER_SANS]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _write_private(path: Path, pem: bytes) -> None:
    path.write_bytes(pem)
    # World-readable, not 0600: this volume is shared across containers
    # (stub-pki, otel-collector) running as different, unrelated UIDs. Fine
    # for a throwaway dev CA that exists only to unblock a local integration
    # test — never do this for a real CA/server key.
    os.chmod(path, 0o644)


def _load_or_create_ca() -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    if CA_KEY_PATH.is_file() and CA_CERT_PATH.is_file():
        log.info("pki.ca.reusing_existing")
        key = serialization.load_pem_private_key(CA_KEY_PATH.read_bytes(), password=None)
        cert = x509.load_pem_x509_certificate(CA_CERT_PATH.read_bytes())
        return key, cert

    log.info("pki.ca.generating_new")
    PKI_DIR.mkdir(parents=True, exist_ok=True)
    key, cert = _generate_ca()
    _write_private(
        CA_KEY_PATH,
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    CA_CERT_PATH.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key, cert


def _ensure_otel_server_cert(
    ca_key: ec.EllipticCurvePrivateKey, ca_cert: x509.Certificate
) -> None:
    if OTEL_KEY_PATH.is_file() and OTEL_CERT_PATH.is_file():
        log.info("pki.otel_cert.reusing_existing")
        return
    log.info("pki.otel_cert.generating_new")
    key, cert = _generate_otel_server_cert(ca_key, ca_cert)
    _write_private(
        OTEL_KEY_PATH,
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    OTEL_CERT_PATH.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


async def handle_enroll(request: web.Request) -> web.Response:
    ca_key: ec.EllipticCurvePrivateKey = request.app["ca_key"]
    ca_cert: x509.Certificate = request.app["ca_cert"]

    body = await request.json()
    collector_id = body.get("collector_id")
    site_id = body.get("site_id", "default")
    csr_pem = body.get("csr_pem")
    if not collector_id or not csr_pem:
        return web.json_response({"error": "collector_id and csr_pem are required"}, status=400)

    try:
        csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
    except ValueError as exc:
        return web.json_response({"error": f"invalid CSR: {exc}"}, status=400)

    if not csr.is_signature_valid:
        return web.json_response({"error": "CSR signature invalid"}, status=400)

    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + LEAF_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    log.info("pki.enroll.issued collector_id=%s site_id=%s", collector_id, site_id)
    return web.json_response(
        {
            "certificate_pem": cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
            "ca_certificate_pem": ca_cert.public_bytes(serialization.Encoding.PEM).decode(
                "ascii"
            ),
        }
    )


async def handle_healthz(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def create_app() -> web.Application:
    app = web.Application()
    ca_key, ca_cert = _load_or_create_ca()
    _ensure_otel_server_cert(ca_key, ca_cert)
    app["ca_key"] = ca_key
    app["ca_cert"] = ca_cert
    app.router.add_post("/api/pki/enroll", handle_enroll)
    app.router.add_get("/healthz", handle_healthz)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8443)
