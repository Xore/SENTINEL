"""Tests for collector.store.sqlite_queue — the durable SQLite cold queue."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from collector.store.envelope import ENVELOPE_VERSION, Envelope
from collector.store.sqlite_queue import SqliteQueue


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

    def test_oversize_single_record_is_still_inserted(self, db_path):
        queue = SqliteQueue(db_path, max_bytes=1)
        env = _make(payload=b"x" * 1000)
        queue.enqueue(env)
        assert queue.count() == 1
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
