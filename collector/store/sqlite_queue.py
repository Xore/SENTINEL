"""Crash-safe SQLite cold queue for `Envelope` instances.

stdlib `sqlite3` only, WAL journal mode, and a busy-timeout pragma so
concurrent readers/writers (multiple `SqliteQueue` instances against the
same file, or multiple threads sharing one instance) don't immediately fail
with "database is locked".

Four properties this module owes the rest of the collector:

* **The configured caps are hard.** After any successful mutation,
  `count() <= max_records` and `total_bytes() <= max_bytes`. A record that
  cannot fit even in an empty queue is rejected with `QueueCapacityError`
  rather than accepted over the cap.
* **Every read/decide/write sequence is one serialized transaction.** The
  connection runs in autocommit mode and each mutating operation takes the
  write lock with `BEGIN IMMEDIATE` *before* its first read, so two instances
  cannot both read the same state and both commit a decision based on it.
* **A row is only trusted if it agrees with its own blob.** `event_id`,
  `created_at`, `expires_at`, and `byte_size` are re-derived from the
  canonical envelope and compared; a mismatch is quarantined, never returned.
* **Quarantine is bounded.** Corrupt rows accumulate under their own
  record/byte caps with deterministic oldest-first cleanup, so this local
  buffer cannot grow without limit.

`event_id` is the primary key, so re-enqueuing the same envelope is a no-op
(duplicate idempotency) rather than an error. Rows are ordered by
`(created_at, event_id)` for deterministic oldest-first retry/eviction.

Standalone in this claim: no LMDB hot tier, configuration, or transport
integration — those are later, separately reviewed claims.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import Iterator
from datetime import UTC, datetime

from collector.store.envelope import Envelope, EnvelopeError

DEFAULT_MAX_RECORDS = 100_000
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_BUSY_TIMEOUT_MS = 5_000
DEFAULT_MAX_QUARANTINE_RECORDS = 1_000
DEFAULT_MAX_QUARANTINE_BYTES = 10 * 1024 * 1024

# A quarantine reason is derived from an exception message, which can quote
# arbitrary blob content; it is stored for operators, so it is length-bounded.
MAX_QUARANTINE_REASON_LEN = 500


class QueueCapacityError(ValueError):
    """A record cannot be stored without exceeding a configured cap."""


def _validate_positive_int(value: object, field_name: str) -> int:
    """Require a true positive `int` — `bool` is an `int` subclass, and a
    float cap would make the hard-cap comparisons below inexact.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{field_name} must be an exact integer, not {type(value).__name__}: got {value!r}"
        )
    if value <= 0:
        raise ValueError(f"{field_name} must be positive: got {value!r}")
    return value


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
        max_quarantine_records: int = DEFAULT_MAX_QUARANTINE_RECORDS,
        max_quarantine_bytes: int = DEFAULT_MAX_QUARANTINE_BYTES,
    ) -> None:
        self._max_records = _validate_positive_int(max_records, "max_records")
        self._max_bytes = _validate_positive_int(max_bytes, "max_bytes")
        self._max_quarantine_records = _validate_positive_int(
            max_quarantine_records, "max_quarantine_records"
        )
        self._max_quarantine_bytes = _validate_positive_int(
            max_quarantine_bytes, "max_quarantine_bytes"
        )
        _validate_positive_int(busy_timeout_ms, "busy_timeout_ms")

        self._lock = threading.Lock()
        # `isolation_level=None` disables sqlite3's implicit transaction
        # handling so this module can open each transaction itself with
        # `BEGIN IMMEDIATE` — an implicit transaction would only begin at the
        # first *write*, leaving the preceding reads unprotected.
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        # PRAGMA doesn't accept bound parameters; busy_timeout_ms is validated
        # as an exact positive int above, not caller-controlled SQL.
        self._conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._init_schema()

    # ------------------------------------------------------------------ setup

    @contextlib.contextmanager
    def _write_transaction(self) -> Iterator[None]:
        """Hold the database write lock for one whole operation.

        `BEGIN IMMEDIATE` acquires the write lock up front, so an operation's
        reads and the writes it decides from them cannot interleave with
        another connection's. On any exception — including `BaseException`, so
        a `KeyboardInterrupt` between statements can't leave a half-applied
        operation committed — the transaction is rolled back.
        """
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _init_schema(self) -> None:
        with self._write_transaction():
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
                    raw_blob BLOB NOT NULL,
                    byte_size INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quarantine_order "
                "ON quarantine (quarantined_at, event_id)"
            )
            self._migrate_quarantine_byte_size()

    def _migrate_quarantine_byte_size(self) -> None:
        """Add `quarantine.byte_size` to a database written before quarantine
        was capped, so its existing rows still count toward the byte cap.
        """
        columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(quarantine)").fetchall()
        }
        if "byte_size" in columns:
            return
        self._conn.execute(
            "ALTER TABLE quarantine ADD COLUMN byte_size INTEGER NOT NULL DEFAULT 0"
        )
        self._conn.execute("UPDATE quarantine SET byte_size = length(raw_blob)")

    # ------------------------------------------------------- internal helpers

    def _queue_totals(self) -> tuple[int, int]:
        return self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(byte_size), 0) FROM queue"
        ).fetchone()

    def _delete_oldest(self, *, exclude_event_id: str | None = None) -> bool:
        """Delete the single oldest queued record. Returns whether one went."""
        if exclude_event_id is None:
            cur = self._conn.execute(
                "DELETE FROM queue WHERE event_id = ("
                "SELECT event_id FROM queue ORDER BY created_at ASC, event_id ASC LIMIT 1)"
            )
        else:
            cur = self._conn.execute(
                "DELETE FROM queue WHERE event_id = ("
                "SELECT event_id FROM queue WHERE event_id != ? "
                "ORDER BY created_at ASC, event_id ASC LIMIT 1)",
                (exclude_event_id,),
            )
        return cur.rowcount > 0

    def _make_room(
        self, extra_bytes: int, extra_records: int, *, exclude_event_id: str | None = None
    ) -> None:
        """Evict oldest-first until `extra_bytes`/`extra_records` more fit.

        Both callers first prove the record fits in an otherwise-empty queue,
        so the loop always terminates within the caps; the `QueueCapacityError`
        below is the guard for a future caller that skips that check rather
        than a path any current one can reach.
        """
        while True:
            count, total_bytes = self._queue_totals()
            if (
                count + extra_records <= self._max_records
                and total_bytes + extra_bytes <= self._max_bytes
            ):
                return
            if not self._delete_oldest(exclude_event_id=exclude_event_id):
                raise QueueCapacityError(
                    f"cannot free {extra_bytes} bytes / {extra_records} record(s) "
                    f"within max_bytes={self._max_bytes}, max_records={self._max_records}"
                )

    def _quarantine(self, event_id: str, raw_blob: bytes, reason: str) -> None:
        """Move one unusable row out of the active queue. Caller must already
        hold a write transaction.
        """
        self._conn.execute("DELETE FROM queue WHERE event_id = ?", (event_id,))
        self._conn.execute(
            "INSERT OR REPLACE INTO quarantine "
            "(event_id, quarantined_at, reason, raw_blob, byte_size) VALUES (?, ?, ?, ?, ?)",
            (
                event_id,
                _sortable(datetime.now(UTC)),
                reason[:MAX_QUARANTINE_REASON_LEN],
                raw_blob,
                len(raw_blob),
            ),
        )
        self._trim_quarantine()

    def _trim_quarantine(self) -> None:
        """Enforce the quarantine caps, oldest-first.

        A single blob larger than `max_quarantine_bytes` is dropped rather
        than kept over the cap: it is already-unusable data, and the point of
        the cap is that corruption cannot consume unbounded local disk.
        """
        while True:
            count, total_bytes = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(byte_size), 0) FROM quarantine"
            ).fetchone()
            if count == 0:
                return
            if (
                count <= self._max_quarantine_records
                and total_bytes <= self._max_quarantine_bytes
            ):
                return
            self._conn.execute(
                "DELETE FROM quarantine WHERE event_id = ("
                "SELECT event_id FROM quarantine "
                "ORDER BY quarantined_at ASC, event_id ASC LIMIT 1)"
            )

    def _row_disagreement(self, row: tuple, envelope: Envelope) -> str | None:
        """Why this row disagrees with its own canonical blob, or `None`.

        A row whose primary key differs from the blob's `event_id` would
        otherwise be handed to a caller that then cannot acknowledge it by the
        ID it received; the timestamps drive ordering and expiry, and
        `byte_size` drives cap accounting, so all four must agree.
        """
        event_id, created_at, expires_at, blob, byte_size = row
        for field, actual, expected in (
            ("event_id", event_id, envelope.event_id),
            ("created_at", created_at, _sortable(envelope.created_at)),
            ("expires_at", expires_at, _sortable(envelope.expires_at)),
            ("byte_size", byte_size, len(blob)),
        ):
            if actual != expected:
                return f"row {field} {actual!r} disagrees with envelope {expected!r}"
        return None

    def _decode_row(self, row: tuple) -> Envelope | None:
        """Decode and validate one row, quarantining it if either fails.
        Caller must already hold a write transaction.
        """
        event_id, _created_at, _expires_at, blob, _byte_size = row
        try:
            envelope = Envelope.from_bytes(blob)
        except EnvelopeError as exc:
            self._quarantine(event_id, blob, str(exc))
            return None
        disagreement = self._row_disagreement(row, envelope)
        if disagreement is not None:
            self._quarantine(event_id, blob, disagreement)
            return None
        return envelope

    # -------------------------------------------------------- public surface

    def enqueue(self, envelope: Envelope) -> None:
        """Insert `envelope`, evicting the oldest records first if either cap
        would be exceeded. A no-op if `envelope.event_id` is already queued
        (duplicate idempotency).

        Raises `QueueCapacityError` if the record could not fit even in an
        empty queue — the caps are hard, so an oversize record is rejected
        rather than accepted over `max_bytes`.
        """
        blob = envelope.to_bytes()
        size = len(blob)
        if size > self._max_bytes:
            raise QueueCapacityError(
                f"envelope is {size} bytes, which exceeds max_bytes={self._max_bytes}"
            )
        with self._lock, self._write_transaction():
            exists = self._conn.execute(
                "SELECT 1 FROM queue WHERE event_id = ?", (envelope.event_id,)
            ).fetchone()
            if exists is not None:
                return
            self._make_room(size, 1)
            self._conn.execute(
                "INSERT INTO queue "
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
        without removing them. A row that fails to deserialize or disagrees
        with its own blob is moved to quarantine and skipped rather than
        raised.

        Runs in a write transaction because quarantining is a mutation: a
        cold queue trades peek concurrency for the guarantee that a corrupt
        row is classified exactly once.
        """
        if limit <= 0:
            raise ValueError(f"limit must be positive: got {limit!r}")
        with self._lock, self._write_transaction():
            rows = self._conn.execute(
                "SELECT event_id, created_at, expires_at, envelope_blob, byte_size FROM queue "
                "ORDER BY created_at ASC, event_id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            decoded = (self._decode_row(row) for row in rows)
            return [envelope for envelope in decoded if envelope is not None]

    def mark_attempt(self, event_id: str) -> Envelope | None:
        """Increment the delivery attempt count for `event_id` and persist it.
        Returns the updated envelope, or `None` if `event_id` isn't queued
        (already acknowledged/expired/quarantined) or its row was quarantined
        by this call.

        The read, the validation, and the update all happen inside one
        `BEGIN IMMEDIATE` transaction, so concurrent instances cannot both
        read the same count and both write count+1.

        An increment can grow the serialized blob (`attempt_count` 9→10 adds a
        byte). Room is made the same oldest-first way `enqueue` makes it;
        `QueueCapacityError` is raised, leaving the row untouched, only if the
        updated record alone would exceed `max_bytes`.
        """
        with self._lock, self._write_transaction():
            row = self._conn.execute(
                "SELECT event_id, created_at, expires_at, envelope_blob, byte_size "
                "FROM queue WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            envelope = self._decode_row(row)
            if envelope is None:
                return None

            updated = envelope.with_attempt_incremented()
            blob = updated.to_bytes()
            size = len(blob)
            if size > self._max_bytes:
                raise QueueCapacityError(
                    f"envelope would be {size} bytes after the attempt increment, "
                    f"which exceeds max_bytes={self._max_bytes}"
                )
            self._make_room(size - row[4], 0, exclude_event_id=event_id)
            self._conn.execute(
                "UPDATE queue SET envelope_blob = ?, byte_size = ? WHERE event_id = ?",
                (blob, size, event_id),
            )
            return updated

    def acknowledge(self, event_id: str) -> None:
        """Remove `event_id` — safe to call once delivery has succeeded.
        A no-op if `event_id` isn't queued (already acknowledged).
        """
        with self._lock, self._write_transaction():
            self._conn.execute("DELETE FROM queue WHERE event_id = ?", (event_id,))

    def remove_expired(self, now: datetime) -> int:
        """Delete every record whose `expires_at` is at or before `now`.
        Returns the number of records removed.
        """
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError(f"now must be an aware UTC datetime: got {now!r}")
        threshold = _sortable(now)
        with self._lock, self._write_transaction():
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

    def quarantined_bytes(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COALESCE(SUM(byte_size), 0) FROM quarantine"
            ).fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> SqliteQueue:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
