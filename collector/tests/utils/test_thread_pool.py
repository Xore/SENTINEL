"""Tests for collector.utils.thread_pool — CPU-bound work offloading."""
from __future__ import annotations

import threading

import pytest
from collector.utils.thread_pool import _CPU_POOL, run_in_thread


def test_pool_capped_at_two_workers():
    assert _CPU_POOL._max_workers == 2


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
