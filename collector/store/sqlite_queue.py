"""Crash-safe SQLite cold queue for `Envelope` instances.

stdlib `sqlite3` only, WAL journal mode, and a busy-timeout pragma so
concurrent readers/writers (multiple `SqliteQueue` instances against the
same file, or multiple threads sharing one instance) don't immediately fail
with "database is locked". Every multi-statement operation runs inside one
explicit transaction.

`event_id` is the primary key, so re-enqueuing the same envelope is a no-op
(duplicate idempotency) rather than an error. Rows are ordered by
`(created_at, event_id)` for deterministic oldest-first retry/eviction. A row
whose blob fails to deserialize (checksum mismatch, malformed JSON) is moved
to a separate `quarantine` table rather than raised or silently dropped, so
one corrupted record can't wedge the queue.

Standalone in this claim: no LMDB hot tier, configuration, or transport
integration — those are later, separately reviewed claims.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime

from collector.store.envelope import Envelope, EnvelopeError

DEFAULT_MAX_RECORDS = 100_000
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_BUSY_TIMEOUT_MS = 5_000


def _sortable(value: datetime) -> str:
    """A fixed-width, lexicographically sortable UTC timestamp string."""
    return value.astimezone(UTC).isoformat(timespec="microseconds")


class SqliteQueue:
    """A durable, disk-backed FIFO queue of `Envelope` instances."""

    def __init__(
        self,
        db_path: str,
        *,
        max_records: int = DEFAULT_MAX_RECORDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        if max_records <= 0:
            raise ValueError(f"max_records must be positive: got {max_records!r}")
        if max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive: got {max_bytes!r}")
        if busy_timeout_ms <= 0:
            raise ValueError(f"busy_timeout_ms must be positive: got {busy_timeout_ms!r}")

        self._max_records = max_records
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # PRAGMA doesn't accept bound parameters; busy_timeout_ms is
        # validated as a positive int above, not caller-controlled SQL.
        self._conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue (
                    event_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    envelope_blob BLOB NOT NULL,
                    byte_size INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_queue_order ON queue (created_at, event_id)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quarantine (
                    event_id TEXT PRIMARY KEY,
                    quarantined_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    raw_blob BLOB NOT NULL
                )
                """
            )

    def _evict_for_capacity(self, incoming_bytes: int) -> None:
        """Evict oldest-first until the incoming record fits both caps.

        If the incoming record alone exceeds `max_bytes`, eviction stops once
        the queue is empty and the record is inserted anyway — a single
        oversize record isn't rejected, just no longer boundable by evicting
        others.
        """
        while True:
            count, total_bytes = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(byte_size), 0) FROM queue"
            ).fetchone()
            if count == 0:
                return
            if count + 1 <= self._max_records and total_bytes + incoming_bytes <= self._max_bytes:
                return
            self._conn.execute(
                "DELETE FROM queue WHERE event_id = ("
                "SELECT event_id FROM queue ORDER BY created_at ASC, event_id ASC LIMIT 1)"
            )

    def _quarantine(self, event_id: str, raw_blob: bytes, reason: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM queue WHERE event_id = ?", (event_id,))
            self._conn.execute(
                "INSERT OR REPLACE INTO quarantine "
                "(event_id, quarantined_at, reason, raw_blob) VALUES (?, ?, ?, ?)",
                (event_id, _sortable(datetime.now(UTC)), reason, raw_blob),
            )

    def enqueue(self, envelope: Envelope) -> None:
        """Insert `envelope`, evicting the oldest records first if either
        cap would be exceeded. A no-op if `envelope.event_id` is already
        queued (duplicate idempotency).
        """
        blob = envelope.to_bytes()
        size = len(blob)
        with self._lock, self._conn:
            exists = self._conn.execute(
                "SELECT 1 FROM queue WHERE event_id = ?", (envelope.event_id,)
            ).fetchone()
            if exists is not None:
                return
            self._evict_for_capacity(size)
            self._conn.execute(
                "INSERT OR IGNORE INTO queue "
                "(event_id, created_at, expires_at, envelope_blob, byte_size) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    envelope.event_id,
                    _sortable(envelope.created_at),
                    _sortable(envelope.expires_at),
                    blob,
                    size,
                ),
            )

    def peek(self, limit: int) -> list[Envelope]:
        """The oldest `limit` envelopes, in `(created_at, event_id)` order,
        without removing them. A row that fails to deserialize is moved to
        quarantine and skipped rather than raised.
        """
        if limit <= 0:
            raise ValueError(f"limit must be positive: got {limit!r}")
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_id, envelope_blob FROM queue "
                "ORDER BY created_at ASC, event_id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            envelopes: list[Envelope] = []
            for event_id, blob in rows:
                try:
                    envelopes.append(Envelope.from_bytes(blob))
                except EnvelopeError as exc:
                    self._quarantine(event_id, blob, str(exc))
            return envelopes

    def mark_attempt(self, event_id: str) -> Envelope | None:
        """Increment the delivery attempt count for `event_id` and persist
        it. Returns the updated envelope, or `None` if `event_id` isn't
        queued (already acknowledged/expired/quarantined).
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT envelope_blob FROM queue WHERE event_id = ?", (event_id,)
            ).fetchone()
            if row is None:
                return None
            try:
                envelope = Envelope.from_bytes(row[0])
            except EnvelopeError as exc:
                self._quarantine(event_id, row[0], str(exc))
                return None
            updated = envelope.with_attempt_incremented()
            blob = updated.to_bytes()
            with self._conn:
                self._conn.execute(
                    "UPDATE queue SET envelope_blob = ?, byte_size = ? WHERE event_id = ?",
                    (blob, len(blob), event_id),
                )
            return updated

    def acknowledge(self, event_id: str) -> None:
        """Remove `event_id` — safe to call once delivery has succeeded.
        A no-op if `event_id` isn't queued (already acknowledged).
        """
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM queue WHERE event_id = ?", (event_id,))

    def remove_expired(self, now: datetime) -> int:
        """Delete every record whose `expires_at` is at or before `now`.
        Returns the number of records removed.
        """
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError(f"now must be an aware UTC datetime: got {now!r}")
        threshold = _sortable(now)
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM queue WHERE expires_at <= ?", (threshold,))
            return cur.rowcount

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0]

    def total_bytes(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COALESCE(SUM(byte_size), 0) FROM queue"
            ).fetchone()[0]

    def quarantined_count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> SqliteQueue:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
