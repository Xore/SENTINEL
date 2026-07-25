"""Shared pytest fixtures for the collector test suite.

`isolate_env` runs for every test so a stray real ``COLLECTOR_*`` /
``BACKEND__*`` / ``WIFI__*`` env var on the dev machine can never leak into a
test's view of configuration.
"""
from __future__ import annotations

import pytest

from collector.config import load_settings

# Env prefixes that CollectorSettings reads. Any of these present in the real
# environment would perturb config tests, so they are cleared per-test.
_MANAGED_PREFIXES = ("COLLECTOR_", "SITE_", "SCAN_LEVEL_", "BACKEND__", "WIFI__",
                     "MTR__", "BCAST_MCAST__", "EBPF__", "LOG_LEVEL", "DATA_DIR")


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
