"""Tests for collector.pki.enroll — CSR generation, HTTP enroll, file writes."""
from __future__ import annotations

import stat
from pathlib import Path

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


class _FakeResponse:
    def __init__(self, status: int, json_body: object = None, text_body: str = ""):
        self.status = status
        self._json = json_body
        self._text = text_body

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def json(self) -> object:
        return self._json

    async def text(self) -> str:
        return self._text


class _FakeSession:
    """Queues canned responses; raises if called more times than queued."""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url: str, json: dict, headers: dict) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)


def _ok_response() -> _FakeResponse:
    return _FakeResponse(
        200,
        json_body={
            "certificate_pem": "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n",
            "ca_certificate_pem": (
                "-----BEGIN CERTIFICATE-----\nfakeca\n-----END CERTIFICATE-----\n"
            ),
        },
    )


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
        session = _FakeSession([_ok_response()])
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
