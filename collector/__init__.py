"""analyseLaptop / SENTINEL v2 collector.

A Python 3.12 asyncio agent that probes the local network and ships metrics via
OTLP/gRPC (mTLS) to the hub. This package is a greenfield v2 rewrite; the frozen
v1 Go collector lives on the ``release/v1.0`` branch and the ``v1.0`` tag.

See ``docs/guides/OPUS-AGENT-GUIDE-V2.md`` for the implementation guide and
``docs/collector/COLLECTOR-V2-REFACTOR.md`` for the primary design spec.
"""
from __future__ import annotations

__version__ = "2.0.0-dev"
