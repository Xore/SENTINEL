"""Crash-safe local storage for telemetry pending delivery.

`envelope.Envelope` is the immutable, versioned unit stored; `sqlite_queue.SqliteQueue`
is the durable disk-backed cold queue that holds them. Standalone in this
claim — no LMDB hot tier, configuration, or transport integration yet.
"""
from __future__ import annotations

from collector.store.envelope import ENVELOPE_VERSION, Envelope, EnvelopeError
from collector.store.sqlite_queue import QueueCapacityError, SqliteQueue

__all__ = [
    "ENVELOPE_VERSION",
    "Envelope",
    "EnvelopeError",
    "QueueCapacityError",
    "SqliteQueue",
]
