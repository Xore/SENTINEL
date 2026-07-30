"""Tests for collector.store.sqlite_queue — the durable SQLite cold queue."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from collector.store.envelope import ENVELOPE_VERSION, Envelope
from collector.store.sqlite_queue import QueueCapacityError, SqliteQueue


def _make(
    *,
    event_id: str | None = None,
    created_at: datetime | None = None,
    ttl: timedelta = timedelta(hours=1),
    payload: bytes = b"payload",
) -> Envelope:
    now = created_at or datetime.now(UTC)
    return Envelope(
        event_id=event_id or str(uuid.uuid4()),
        site_id="site-a",
        collector_id="collector-1",
        observed_at=now,
        created_at=now,
        expires_at=now + ttl,
        content_type="application/x-otlp",
        payload=payload,
    )


@pytest.fixture(name="db_path")
def _db_path_fixture(tmp_path):
    return str(tmp_path / "queue.db")


def _overwrite_blob(db_path: str, event_id: str, blob: bytes) -> None:
    """Corrupt one stored blob behind the queue's back."""
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE queue SET envelope_blob = ? WHERE event_id = ?", (blob, event_id))
    conn.commit()
    conn.close()


def _overwrite_column(db_path: str, event_id: str, column: str, value: object) -> None:
    """Desynchronize one indexed row column from its canonical blob.

    `column` is a fixed literal chosen by the test, never external input.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(f"UPDATE queue SET {column} = ? WHERE event_id = ?", (value, event_id))
    conn.commit()
    conn.close()


def _quarantine_rows(db_path: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT event_id, reason, byte_size FROM quarantine "
            "ORDER BY quarantined_at ASC, event_id ASC"
        ).fetchall()
    finally:
        conn.close()


class TestConstruction:
    def test_rejects_non_positive_max_records(self, db_path):
        with pytest.raises(ValueError, match="max_records"):
            SqliteQueue(db_path, max_records=0)

    def test_rejects_non_positive_max_bytes(self, db_path):
        with pytest.raises(ValueError, match="max_bytes"):
            SqliteQueue(db_path, max_bytes=0)

    def test_rejects_non_positive_busy_timeout(self, db_path):
        with pytest.raises(ValueError, match="busy_timeout_ms"):
            SqliteQueue(db_path, busy_timeout_ms=0)


class TestRoundTripDeterminism:
    def test_enqueue_then_peek_round_trips_exactly(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        peeked = queue.peek(10)
        assert len(peeked) == 1
        assert peeked[0] == env
        queue.close()


class TestDuplicateIdempotency:
    def test_enqueuing_same_event_id_twice_is_a_no_op(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        queue.enqueue(env)
        assert queue.count() == 1
        queue.close()


class TestChecksumCorruption:
    def test_corrupted_row_is_quarantined_not_returned(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)

        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE queue SET envelope_blob = ? WHERE event_id = ?", (b"garbage", env.event_id)
        )
        conn.commit()
        conn.close()

        assert not queue.peek(10)
        assert queue.count() == 0
        assert queue.quarantined_count() == 1
        queue.close()


class TestUnknownVersion:
    def test_future_version_row_is_quarantined(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)

        obj = json.loads(env.to_bytes())
        obj["version"] = ENVELOPE_VERSION + 1
        bad_blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE queue SET envelope_blob = ? WHERE event_id = ?", (bad_blob, env.event_id)
        )
        conn.commit()
        conn.close()

        assert not queue.peek(10)
        assert queue.quarantined_count() == 1
        queue.close()


class TestCrashReopenDurability:
    def test_data_survives_abandoned_connection(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        del queue  # simulate a crash: no explicit close()

        reopened = SqliteQueue(db_path)
        peeked = reopened.peek(10)
        assert len(peeked) == 1
        assert peeked[0] == env
        reopened.close()


class TestConcurrentProducerConsumer:
    def test_many_threads_enqueue_on_one_instance_without_lost_writes(self, db_path):
        queue = SqliteQueue(db_path, max_records=1000)
        envelopes = [_make() for _ in range(50)]

        def _enqueue_all(items):
            for item in items:
                queue.enqueue(item)

        threads = [
            threading.Thread(target=_enqueue_all, args=(envelopes[i::5],)) for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert queue.count() == 50
        queue.close()

    def test_separate_instances_share_the_same_file(self, db_path):
        producer = SqliteQueue(db_path)
        consumer = SqliteQueue(db_path)

        env = _make()
        producer.enqueue(env)

        peeked = consumer.peek(10)
        assert len(peeked) == 1
        assert peeked[0] == env
        consumer.acknowledge(env.event_id)

        assert producer.count() == 0
        producer.close()
        consumer.close()


class TestBusyLockedDatabase:
    def test_write_raises_when_busy_timeout_is_shorter_than_the_hold(self, db_path):
        queue = SqliteQueue(db_path, busy_timeout_ms=50)
        blocker = sqlite3.connect(db_path, check_same_thread=False)
        blocker.execute("BEGIN IMMEDIATE")

        release = threading.Event()

        def _release_after_delay():
            release.wait(0.3)
            blocker.commit()
            blocker.close()

        releaser = threading.Thread(target=_release_after_delay)
        releaser.start()
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                queue.enqueue(_make())
        finally:
            release.set()
            releaser.join()
            queue.close()

    def test_write_succeeds_after_waiting_within_busy_timeout(self, db_path):
        queue = SqliteQueue(db_path, busy_timeout_ms=2000)
        blocker = sqlite3.connect(db_path, check_same_thread=False)
        blocker.execute("BEGIN IMMEDIATE")

        def _release_shortly():
            blocker.commit()
            blocker.close()

        timer = threading.Timer(0.2, _release_shortly)
        timer.start()
        try:
            queue.enqueue(_make())
            assert queue.count() == 1
        finally:
            timer.join()
            queue.close()


class TestCapEviction:
    def test_max_records_evicts_oldest_first(self, db_path):
        queue = SqliteQueue(db_path, max_records=3)
        envs = [_make(created_at=datetime.now(UTC) + timedelta(seconds=i)) for i in range(5)]
        for env in envs:
            queue.enqueue(env)

        remaining = queue.peek(10)
        assert queue.count() == 3
        assert [e.event_id for e in remaining] == [e.event_id for e in envs[2:]]
        queue.close()

    def test_max_bytes_evicts_oldest_first(self, db_path):
        payload = b"x" * 100
        approx_envelope_size = len(_make(payload=payload).to_bytes())
        queue = SqliteQueue(db_path, max_records=1000, max_bytes=approx_envelope_size * 3 + 10)
        envs = [
            _make(created_at=datetime.now(UTC) + timedelta(seconds=i), payload=payload)
            for i in range(5)
        ]
        for env in envs:
            queue.enqueue(env)

        assert queue.count() <= 3
        assert queue.total_bytes() <= approx_envelope_size * 3 + 10
        remaining = queue.peek(10)
        assert [e.event_id for e in remaining] == [e.event_id for e in envs[-len(remaining):]]
        queue.close()

    def test_oversize_single_record_is_rejected_not_stored_over_the_cap(self, db_path):
        # `max_bytes` is a hard cap on local disk use. A record that cannot fit
        # even in an empty queue is refused; storing it anyway would make the
        # cap advisory and let one oversize envelope blow the budget.
        queue = SqliteQueue(db_path, max_bytes=1)
        env = _make(payload=b"x" * 1000)

        with pytest.raises(QueueCapacityError, match="exceeds max_bytes"):
            queue.enqueue(env)

        assert queue.count() == 0
        assert queue.total_bytes() == 0
        queue.close()

    def test_caps_hold_after_every_single_enqueue(self, db_path):
        payload = b"x" * 100
        one = len(_make(payload=payload).to_bytes())
        queue = SqliteQueue(db_path, max_records=4, max_bytes=one * 3 + 5)

        for i in range(20):
            queue.enqueue(_make(created_at=datetime.now(UTC) + timedelta(seconds=i),
                                payload=payload))
            # Checked after *each* mutation, not just at the end: an
            # intermediate overrun is still an overrun on disk.
            assert queue.count() <= 4
            assert queue.total_bytes() <= one * 3 + 5
        queue.close()

    def test_rejected_oversize_record_does_not_evict_existing_records(self, db_path):
        one = len(_make(payload=b"x" * 100).to_bytes())
        queue = SqliteQueue(db_path, max_bytes=one * 2)
        keeper = _make(payload=b"x" * 100)
        queue.enqueue(keeper)

        with pytest.raises(QueueCapacityError):
            queue.enqueue(_make(payload=b"x" * 10_000))

        assert [e.event_id for e in queue.peek(10)] == [keeper.event_id]
        queue.close()


class TestAttemptIncrementCapacity:
    """An attempt increment grows the blob at every digit boundary
    (`attempt_count` 9 -> 10 adds a byte), so it is a capacity event too."""

    @staticmethod
    def _grow_past_a_digit_boundary(queue, event_id):
        for _ in range(10):
            queue.mark_attempt(event_id)

    def test_growth_evicts_the_oldest_other_record_to_stay_under_the_cap(self, db_path):
        base = datetime.now(UTC)
        older = _make(created_at=base)
        newer = _make(created_at=base + timedelta(seconds=1))
        exact = len(older.to_bytes()) + len(newer.to_bytes())
        queue = SqliteQueue(db_path, max_bytes=exact)
        queue.enqueue(older)
        queue.enqueue(newer)
        assert queue.count() == 2

        self._grow_past_a_digit_boundary(queue, newer.event_id)

        remaining = queue.peek(10)
        assert [e.event_id for e in remaining] == [newer.event_id]
        assert remaining[0].attempt_count == 10
        assert queue.total_bytes() <= exact
        queue.close()

    def test_growth_that_cannot_fit_raises_and_leaves_the_row_untouched(self, db_path):
        env = _make()
        # Exactly one record's worth of room, and no other record to evict.
        queue = SqliteQueue(db_path, max_bytes=len(env.to_bytes()))
        queue.enqueue(env)
        for _ in range(9):
            queue.mark_attempt(env.event_id)

        with pytest.raises(QueueCapacityError, match="after the attempt increment"):
            queue.mark_attempt(env.event_id)

        # The failed transaction rolled back: the count is still 9, not 10.
        peeked = queue.peek(10)
        assert [e.attempt_count for e in peeked] == [9]
        assert queue.total_bytes() <= len(env.to_bytes())
        queue.close()


class TestRowBlobAgreement:
    """The indexed columns are derived data. A row is only trusted when it
    still agrees with the canonical blob it was derived from."""

    def _quarantined_reason(self, db_path, queue, env):
        assert queue.peek(10) == []
        assert queue.count() == 0
        rows = _quarantine_rows(db_path)
        assert len(rows) == 1
        assert rows[0][0] == env.event_id
        return rows[0][1]

    def test_event_id_disagreement_is_quarantined(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        # A row keyed by an ID the blob doesn't carry could never be
        # acknowledged by the ID the caller was handed.
        renamed = str(uuid.uuid4())
        _overwrite_column(db_path, env.event_id, "event_id", renamed)

        assert queue.peek(10) == []
        assert queue.count() == 0
        rows = _quarantine_rows(db_path)
        assert [row[0] for row in rows] == [renamed]
        assert "row event_id" in rows[0][1]
        queue.close()

    def test_created_at_disagreement_is_quarantined(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        # created_at drives retry ordering, so a drifted copy silently
        # reorders the queue.
        _overwrite_column(db_path, env.event_id, "created_at", "1999-01-01T00:00:00.000000+00:00")

        assert "row created_at" in self._quarantined_reason(db_path, queue, env)
        queue.close()

    def test_expires_at_disagreement_is_quarantined(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        # expires_at drives `remove_expired`, so a drifted copy either drops
        # live data or keeps dead data forever.
        _overwrite_column(db_path, env.event_id, "expires_at", "2999-01-01T00:00:00.000000+00:00")

        assert "row expires_at" in self._quarantined_reason(db_path, queue, env)
        queue.close()

    def test_byte_size_disagreement_is_quarantined(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        # byte_size is what the cap arithmetic trusts; an understated one
        # would let the queue exceed max_bytes without noticing.
        _overwrite_column(db_path, env.event_id, "byte_size", 1)

        assert "row byte_size" in self._quarantined_reason(db_path, queue, env)
        queue.close()

    def test_mark_attempt_also_rejects_a_disagreeing_row(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        _overwrite_column(db_path, env.event_id, "byte_size", 1)

        assert queue.mark_attempt(env.event_id) is None
        assert queue.count() == 0
        assert queue.quarantined_count() == 1
        queue.close()

    def test_an_agreeing_row_is_returned_unchanged(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        assert queue.peek(10) == [env]
        assert queue.quarantined_count() == 0
        queue.close()


class TestTransactionIsolation:
    class _FailingConn:
        """Proxy that fails one statement prefix; `sqlite3.Connection` does
        not accept attribute assignment, so the connection is wrapped."""

        def __init__(self, conn, fail_prefix, *, max_failures=None):
            self._conn = conn
            self._fail_prefix = fail_prefix
            self._max_failures = max_failures
            self._failures = 0

        def execute(self, sql, *args):
            if sql.lstrip().startswith(self._fail_prefix) and (
                self._max_failures is None or self._failures < self._max_failures
            ):
                self._failures += 1
                raise sqlite3.OperationalError("simulated disk I/O error")
            return self._conn.execute(sql, *args)

        def close(self):
            self._conn.close()

    def test_a_failed_insert_rolls_back_the_eviction_it_caused(self, db_path):
        base = datetime.now(UTC)
        first = _make(created_at=base)
        queue = SqliteQueue(db_path, max_records=1)
        queue.enqueue(first)

        real_conn = queue._conn  # pylint: disable=protected-access
        queue._conn = self._FailingConn(  # pylint: disable=protected-access
            real_conn, "INSERT INTO queue"
        )
        try:
            with pytest.raises(sqlite3.OperationalError):
                queue.enqueue(_make(created_at=base + timedelta(seconds=1)))
        finally:
            queue._conn = real_conn  # pylint: disable=protected-access

        # `first` was evicted to make room for the insert that then failed;
        # rolling back must bring it back rather than leave the queue emptied.
        assert queue.count() == 1
        assert [e.event_id for e in queue.peek(10)] == [first.event_id]
        queue.close()

    def test_a_failed_commit_does_not_wedge_the_queue_forever(self, db_path):
        """SQLite returns `SQLITE_FULL`/`SQLITE_BUSY` from `COMMIT` and leaves
        the transaction *open*. If that failure escapes without a rollback the
        connection stays mid-transaction, so every later `BEGIN IMMEDIATE`
        raises "cannot start a transaction within a transaction" — a queue that
        stays dead after the disk has room again, on exactly the hardware
        (SD card, small NVMe) where filling up is the expected failure.
        """
        base = datetime.now(UTC)
        first = _make(created_at=base)
        queue = SqliteQueue(db_path)
        queue.enqueue(first)

        real_conn = queue._conn  # pylint: disable=protected-access
        queue._conn = self._FailingConn(  # pylint: disable=protected-access
            real_conn, "COMMIT", max_failures=1
        )
        try:
            with pytest.raises(sqlite3.OperationalError):
                queue.enqueue(_make(created_at=base + timedelta(seconds=1)))
        finally:
            queue._conn = real_conn  # pylint: disable=protected-access

        # The uncommitted write is gone, and — the point of the test — the
        # queue still works once the transient condition has passed.
        recovered = _make(created_at=base + timedelta(seconds=2))
        queue.enqueue(recovered)
        assert [e.event_id for e in queue.peek(10)] == [first.event_id, recovered.event_id]
        assert queue.count() == 2
        queue.close()

    def test_no_lost_increments_across_separate_instances(self, db_path):
        env = _make()
        seed = SqliteQueue(db_path)
        seed.enqueue(env)
        seed.close()

        # Instances are opened up front so the threads contend on the queue
        # operations themselves, not on schema initialization.
        queues = [SqliteQueue(db_path, busy_timeout_ms=15_000) for _ in range(4)]
        failures: list[BaseException] = []

        def _bump(queue):
            try:
                for _ in range(10):
                    queue.mark_attempt(env.event_id)
            except BaseException as exc:  # pylint: disable=broad-except
                failures.append(exc)

        threads = [threading.Thread(target=_bump, args=(q,)) for q in queues]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)

        assert not failures
        # Read-modify-write under BEGIN IMMEDIATE: every one of the 40
        # increments must be present. A lost update shows up as < 40.
        assert queues[0].peek(1)[0].attempt_count == 40
        for queue in queues:
            queue.close()

    def test_concurrent_instances_cannot_overrun_the_record_cap(self, db_path):
        queues = [
            SqliteQueue(db_path, max_records=5, busy_timeout_ms=15_000) for _ in range(4)
        ]
        failures: list[BaseException] = []

        def _fill(queue):
            try:
                for _ in range(15):
                    queue.enqueue(_make())
            except BaseException as exc:  # pylint: disable=broad-except
                failures.append(exc)

        threads = [threading.Thread(target=_fill, args=(q,)) for q in queues]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)

        assert not failures
        assert queues[0].count() == 5
        # Byte accounting must still match the rows actually stored.
        conn = sqlite3.connect(db_path)
        try:
            summed, actual = conn.execute(
                "SELECT COALESCE(SUM(byte_size), 0), COALESCE(SUM(LENGTH(envelope_blob)), 0) "
                "FROM queue"
            ).fetchone()
        finally:
            conn.close()
        assert summed == actual
        for queue in queues:
            queue.close()


class TestSimultaneousProducersAndConsumers:
    """`peek()` deliberately is not a lease, so two consumers may observe the
    same event; dedup is the sender's job. What must hold is that nothing is
    lost, nothing is invented, and the queue drains empty."""

    @staticmethod
    def _drain(producer_queues, consumer_queues, per_producer):
        produced: list[str] = []
        produced_lock = threading.Lock()
        drained: set[str] = set()
        drained_lock = threading.Lock()
        producers_done = threading.Event()
        failures: list[BaseException] = []

        def _produce(queue):
            try:
                for _ in range(per_producer):
                    env = _make()
                    queue.enqueue(env)
                    with produced_lock:
                        produced.append(env.event_id)
            except BaseException as exc:  # pylint: disable=broad-except
                failures.append(exc)

        def _consume(queue):
            try:
                while True:
                    batch = queue.peek(5)
                    if not batch:
                        if producers_done.is_set():
                            return
                        time.sleep(0.005)
                        continue
                    for env in batch:
                        queue.acknowledge(env.event_id)
                        with drained_lock:
                            drained.add(env.event_id)
            except BaseException as exc:  # pylint: disable=broad-except
                failures.append(exc)

        producers = [threading.Thread(target=_produce, args=(q,)) for q in producer_queues]
        consumers = [threading.Thread(target=_consume, args=(q,)) for q in consumer_queues]
        for t in consumers + producers:
            t.start()
        for t in producers:
            t.join(60)
        producers_done.set()
        for t in consumers:
            t.join(60)

        assert not failures
        assert len(produced) == len(producer_queues) * per_producer
        assert drained == set(produced)
        return produced

    def test_one_instance_shared_by_producer_and_consumer_threads(self, db_path):
        queue = SqliteQueue(db_path, max_records=1000)
        self._drain([queue] * 3, [queue] * 2, per_producer=20)
        assert queue.count() == 0
        assert queue.quarantined_count() == 0
        queue.close()

    def test_separate_instances_on_the_same_file(self, db_path):
        producers = [SqliteQueue(db_path, max_records=1000, busy_timeout_ms=15_000)
                     for _ in range(3)]
        consumers = [SqliteQueue(db_path, max_records=1000, busy_timeout_ms=15_000)
                     for _ in range(2)]
        try:
            self._drain(producers, consumers, per_producer=20)
            assert producers[0].count() == 0
            assert producers[0].quarantined_count() == 0
        finally:
            for queue in producers + consumers:
                queue.close()


class TestBoundedQuarantine:
    """Quarantine is a local buffer of already-unusable data, so it gets its
    own hard caps rather than growing until the disk fills."""

    @staticmethod
    def _corrupt_one(db_path, queue, *, blob=b"garbage"):
        env = _make()
        queue.enqueue(env)
        _overwrite_blob(db_path, env.event_id, blob)
        queue.peek(10)
        # Distinct quarantined_at values keep oldest-first eviction
        # deterministic rather than falling back to the event_id tiebreak.
        time.sleep(0.005)
        return env

    def test_rejects_non_positive_quarantine_caps(self, db_path):
        with pytest.raises(ValueError, match="max_quarantine_records"):
            SqliteQueue(db_path, max_quarantine_records=0)
        with pytest.raises(ValueError, match="max_quarantine_bytes"):
            SqliteQueue(db_path, max_quarantine_bytes=0)

    def test_record_cap_evicts_oldest_quarantined_first(self, db_path):
        queue = SqliteQueue(db_path, max_quarantine_records=2)
        first = self._corrupt_one(db_path, queue)
        second = self._corrupt_one(db_path, queue)
        third = self._corrupt_one(db_path, queue)

        assert queue.quarantined_count() == 2
        # `first` was quarantined earliest, so it is the one dropped.
        assert [row[0] for row in _quarantine_rows(db_path)] == [
            second.event_id,
            third.event_id,
        ]
        assert first is not None
        queue.close()

    def test_byte_cap_bounds_quarantine_disk_use(self, db_path):
        blob = b"g" * 100
        queue = SqliteQueue(db_path, max_quarantine_records=1000, max_quarantine_bytes=250)
        for _ in range(6):
            self._corrupt_one(db_path, queue, blob=blob)

        assert queue.quarantined_bytes() <= 250
        assert queue.quarantined_count() == 2
        queue.close()

    def test_a_blob_larger_than_the_whole_cap_is_dropped_not_kept(self, db_path):
        queue = SqliteQueue(db_path, max_quarantine_bytes=10)
        self._corrupt_one(db_path, queue, blob=b"g" * 5000)

        # Already-unusable data must not be able to defeat the cap by being
        # big; the row still leaves the active queue.
        assert queue.quarantined_count() == 0
        assert queue.quarantined_bytes() == 0
        assert queue.count() == 0
        queue.close()

    def test_quarantined_bytes_tracks_the_stored_blobs(self, db_path):
        queue = SqliteQueue(db_path)
        self._corrupt_one(db_path, queue, blob=b"g" * 40)
        self._corrupt_one(db_path, queue, blob=b"g" * 60)

        assert queue.quarantined_count() == 2
        assert queue.quarantined_bytes() == 100
        assert [row[2] for row in _quarantine_rows(db_path)] == [40, 60]
        queue.close()

    def test_quarantine_reason_is_length_bounded(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        # A deserialization error message can quote the offending bytes, so
        # the stored reason must not inherit an unbounded blob.
        _overwrite_blob(db_path, env.event_id, b"{" + b"z" * 20_000)
        queue.peek(10)

        assert len(_quarantine_rows(db_path)[0][1]) <= 500
        queue.close()

    def test_legacy_database_without_byte_size_is_migrated(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE quarantine (event_id TEXT PRIMARY KEY, quarantined_at TEXT NOT NULL, "
            "reason TEXT NOT NULL, raw_blob BLOB NOT NULL)"
        )
        conn.execute(
            "INSERT INTO quarantine VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), "2026-01-01T00:00:00.000000+00:00", "old", b"g" * 30),
        )
        conn.commit()
        conn.close()

        queue = SqliteQueue(db_path)
        # Rows written before the cap existed must still count toward it.
        assert queue.quarantined_count() == 1
        assert queue.quarantined_bytes() == 30
        queue.close()


class TestExpiry:
    def test_remove_expired_only_removes_past_expiry(self, db_path):
        queue = SqliteQueue(db_path)
        now = datetime.now(UTC)
        expiring_soon = _make(created_at=now, ttl=timedelta(seconds=1))
        long_lived = _make(created_at=now, ttl=timedelta(hours=1))
        queue.enqueue(expiring_soon)
        queue.enqueue(long_lived)

        removed = queue.remove_expired(now + timedelta(seconds=2))

        assert removed == 1
        remaining = queue.peek(10)
        assert [e.event_id for e in remaining] == [long_lived.event_id]
        queue.close()

    def test_remove_expired_rejects_naive_datetime(self, db_path):
        queue = SqliteQueue(db_path)
        with pytest.raises(ValueError, match="aware UTC"):
            queue.remove_expired(datetime.now())  # noqa: DTZ005 — intentional for the test
        queue.close()


class TestRetryOrderAndAcknowledgement:
    def test_peek_returns_oldest_first(self, db_path):
        queue = SqliteQueue(db_path)
        base = datetime.now(UTC)
        envs = [_make(created_at=base + timedelta(seconds=i)) for i in range(5)]
        # Enqueue out of order to prove ordering comes from created_at, not insertion order.
        for env in [envs[3], envs[1], envs[4], envs[0], envs[2]]:
            queue.enqueue(env)

        peeked = queue.peek(10)
        assert [e.event_id for e in peeked] == [e.event_id for e in envs]
        queue.close()

    def test_acknowledge_removes_exactly_one_record(self, db_path):
        queue = SqliteQueue(db_path)
        env1, env2 = _make(), _make()
        queue.enqueue(env1)
        queue.enqueue(env2)

        queue.acknowledge(env1.event_id)

        assert queue.count() == 1
        peeked = queue.peek(10)
        assert len(peeked) == 1
        assert peeked[0].event_id == env2.event_id
        queue.close()

    def test_double_acknowledge_is_a_safe_no_op(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        queue.acknowledge(env.event_id)
        queue.acknowledge(env.event_id)
        assert queue.count() == 0
        queue.close()

    def test_acknowledge_unknown_event_id_is_a_safe_no_op(self, db_path):
        queue = SqliteQueue(db_path)
        queue.acknowledge(str(uuid.uuid4()))
        assert queue.count() == 0
        queue.close()


class TestAttemptIncrement:
    def test_mark_attempt_increments_and_persists(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)

        updated = queue.mark_attempt(env.event_id)
        assert updated.attempt_count == 1

        peeked = queue.peek(10)
        assert len(peeked) == 1
        assert peeked[0].attempt_count == 1
        queue.close()

    def test_mark_attempt_unknown_event_id_returns_none(self, db_path):
        queue = SqliteQueue(db_path)
        assert queue.mark_attempt(str(uuid.uuid4())) is None
        queue.close()

    def test_mark_attempt_on_corrupted_row_quarantines_and_returns_none(self, db_path):
        queue = SqliteQueue(db_path)
        env = _make()
        queue.enqueue(env)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE queue SET envelope_blob = ? WHERE event_id = ?", (b"garbage", env.event_id)
        )
        conn.commit()
        conn.close()

        assert queue.mark_attempt(env.event_id) is None
        assert queue.quarantined_count() == 1
        queue.close()


class TestPeekValidation:
    def test_peek_rejects_non_positive_limit(self, db_path):
        queue = SqliteQueue(db_path)
        with pytest.raises(ValueError, match="limit"):
            queue.peek(0)
        queue.close()


class TestContextManager:
    def test_context_manager_closes_connection(self, db_path):
        with SqliteQueue(db_path) as queue:
            queue.enqueue(_make())
        with pytest.raises(sqlite3.ProgrammingError):
            queue.count()


class TestSimulatedBacklogDrain:
    def test_drains_a_full_24_hour_backlog_in_order(self, db_path):
        queue = SqliteQueue(db_path, max_records=10_000)
        start = datetime.now(UTC) - timedelta(hours=24)
        envelopes = [
            _make(created_at=start + timedelta(minutes=5 * i), ttl=timedelta(hours=48))
            for i in range(288)  # one every 5 minutes across 24 hours
        ]
        for env in envelopes:
            queue.enqueue(env)

        assert queue.count() == 288

        drained: list[str] = []
        while True:
            batch = queue.peek(25)
            if not batch:
                break
            for env in batch:
                queue.acknowledge(env.event_id)
                drained.append(env.event_id)

        assert drained == [e.event_id for e in envelopes]
        assert queue.count() == 0
        assert queue.quarantined_count() == 0
        queue.close()
