"""mTLS channel credentials — load the collector's enrolled leaf cert/key and
the CA certificate (written by ``collector.pki.enroll``) into
``grpc.ssl_channel_credentials()`` for the OTLP/gRPC exporter.
"""
from __future__ import annotations

import os
from pathlib import Path

import grpc

from collector.pki.enroll import CA_FILENAME, CERT_FILENAME, KEY_FILENAME


class MtlsCredentialError(Exception):
    """Raised when the PKI files needed for an mTLS channel are missing."""


def load_channel_credentials(pki_dir: str | os.PathLike[str]) -> grpc.ChannelCredentials:
    """Build gRPC channel credentials from the collector's enrolled PKI files.

    Raises `MtlsCredentialError` naming any of collector.key/collector.crt/
    ca.crt that is missing from `pki_dir` — enrollment via
    `collector.pki.enroll.ensure_enrolled` must run first.
    """
    d = Path(pki_dir)
    key_path, cert_path, ca_path = d / KEY_FILENAME, d / CERT_FILENAME, d / CA_FILENAME

    missing = [p.name for p in (key_path, cert_path, ca_path) if not p.is_file()]
    if missing:
        raise MtlsCredentialError(
            f"missing PKI file(s) in {d}: {', '.join(missing)} — "
            "run collector.pki.enroll.ensure_enrolled() first"
        )

    return grpc.ssl_channel_credentials(
        root_certificates=ca_path.read_bytes(),
        private_key=key_path.read_bytes(),
        certificate_chain=cert_path.read_bytes(),
    )
