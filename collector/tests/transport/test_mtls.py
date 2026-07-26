"""Tests for collector.transport.mtls — grpc credential loading from PKI files."""
from __future__ import annotations

import grpc
import pytest
from collector.transport.mtls import MtlsCredentialError, load_channel_credentials


def test_missing_pki_dir_raises(tmp_path):
    with pytest.raises(MtlsCredentialError) as exc:
        load_channel_credentials(tmp_path / "pki")
    msg = str(exc.value)
    assert "collector.key" in msg
    assert "collector.crt" in msg
    assert "ca.crt" in msg


def test_partial_files_raises_naming_only_missing_ones(tmp_path):
    d = tmp_path / "pki"
    d.mkdir()
    (d / "collector.key").write_bytes(b"fake-key")

    with pytest.raises(MtlsCredentialError) as exc:
        load_channel_credentials(d)
    msg = str(exc.value)
    assert "collector.key" not in msg
    assert "collector.crt" in msg
    assert "ca.crt" in msg


def test_builds_channel_credentials(enrolled_pki_dir):
    creds = load_channel_credentials(enrolled_pki_dir)
    assert isinstance(creds, grpc.ChannelCredentials)
