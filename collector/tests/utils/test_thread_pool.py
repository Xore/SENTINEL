"""Tests for collector.utils.thread_pool — CPU-bound work offloading."""
from __future__ import annotations

import threading

import pytest
from collector.utils import thread_pool
from collector.utils.thread_pool import run_in_thread


@pytest.fixture(autouse=True)
def _reset_pool():
    """Every test starts and leaves the module unconfigured.

    The pool is process-global, so a test that configures it would otherwise
    decide the worker count for every test that runs after it.
    """
    thread_pool.shutdown()
    thread_pool._workers = None  # pylint: disable=protected-access
    yield
    thread_pool.shutdown()
    thread_pool._workers = None  # pylint: disable=protected-access


def test_default_worker_count_is_bounded_at_both_ends(monkeypatch):
    monkeypatch.setattr(thread_pool.os, "cpu_count", lambda: 1)
    assert thread_pool.default_worker_count() == 2

    monkeypatch.setattr(thread_pool.os, "cpu_count", lambda: 64)
    assert thread_pool.default_worker_count() == 8

    # cpu_count() is documented as possibly returning None.
    monkeypatch.setattr(thread_pool.os, "cpu_count", lambda: None)
    assert thread_pool.default_worker_count() == 2


def test_default_worker_count_on_the_reference_pi_5(monkeypatch):
    """Four Cortex-A76 cores — twice the retired Pi 3B literal (ADR 0012)."""
    monkeypatch.setattr(thread_pool.os, "cpu_count", lambda: 4)
    assert thread_pool.default_worker_count() == 4


def test_worker_count_falls_back_to_the_derived_default(monkeypatch):
    monkeypatch.setattr(thread_pool.os, "cpu_count", lambda: 4)
    assert thread_pool.worker_count() == 4


def test_configure_sets_the_pool_size():
    thread_pool.configure(6)
    assert thread_pool.worker_count() == 6
    # pylint: disable=protected-access
    assert thread_pool._executor()._max_workers == 6


def test_configure_rejects_zero_and_negative():
    for bad in (0, -1):
        with pytest.raises(ValueError, match="must be >= 1"):
            thread_pool.configure(bad)


async def test_configure_replaces_a_live_pool():
    first = thread_pool._executor()  # pylint: disable=protected-access
    await run_in_thread(lambda: None)

    thread_pool.configure(3)
    second = thread_pool._executor()  # pylint: disable=protected-access

    assert second is not first
    assert second._max_workers == 3  # pylint: disable=protected-access
    assert await run_in_thread(lambda: "still works") == "still works"


async def test_shutdown_then_reuse_creates_a_fresh_pool():
    assert await run_in_thread(lambda: 1) == 1
    thread_pool.shutdown()
    assert await run_in_thread(lambda: 2) == 2


async def test_runs_in_a_different_thread():
    caller_ident = threading.get_ident()

    def get_thread_ident():
        return threading.get_ident()

    worker_ident = await run_in_thread(get_thread_ident)
    assert worker_ident != caller_ident


async def test_returns_function_result():
    def add(a, b):
        return a + b

    result = await run_in_thread(add, 2, 3)
    assert result == 5


async def test_supports_kwargs():
    def greet(name, *, greeting="hello"):
        return f"{greeting}, {name}"

    result = await run_in_thread(greet, "world", greeting="hi")
    assert result == "hi, world"


async def test_exception_propagates():
    def boom():
        raise ValueError("bad")

    with pytest.raises(ValueError, match="bad"):
        await run_in_thread(boom)
