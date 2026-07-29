"""测试 utils/parallel.py —— parallel_node_calls 工具函数。"""

import time

import pytest

from ...utils.parallel import parallel_node_calls


def _fast() -> str:
    return "ok"


def _slow(seconds: float = 10.0) -> str:
    time.sleep(seconds)
    return "slow_done"


def _failing() -> str:
    raise ValueError("intentional failure")


class TestParallelNodeCalls:
    def test_all_success_preserves_order(self):
        calls = [lambda i=i: f"_{i}_" for i in range(3)]
        results = parallel_node_calls(calls)
        assert results == ["_0_", "_1_", "_2_"]

    def test_partial_failure_does_not_interrupt_others(self):
        calls = [
            lambda: "a",
            _failing,
            lambda: "c",
        ]
        results = parallel_node_calls(calls)
        assert results[0] == "a"
        assert isinstance(results[1], ValueError)
        assert results[2] == "c"

    def test_timeout_per_call_returns_exception(self):
        calls = [
            lambda: "fast",
            lambda: _slow(10.0),
        ]
        results = parallel_node_calls(calls, timeout_per_call=0.3)
        assert results[0] == "fast"
        assert isinstance(results[1], TimeoutError)

    def test_empty_calls_returns_empty_list(self):
        assert parallel_node_calls([]) == []

    def test_pool_size_limit_is_honoured_by_concurrent_execution(self):
        """pool_size=1 时调用串行执行，总耗时接近各调用耗时之和。"""
        calls = [lambda: time.sleep(0.1) for _ in range(3)]
        t0 = time.time()
        results = parallel_node_calls(calls, pool_size=1, timeout_per_call=5)
        elapsed = time.time() - t0
        # 3 calls × 0.1s ≈ 0.3s serial; parallel would be ~0.1s
        assert elapsed > 0.25
        assert all(r is None for r in results)  # sleep returns None

    def test_custom_pool_size_overrides_config(self, app):
        calls = [lambda i=i: i for i in range(5)]
        results = parallel_node_calls(calls, pool_size=2, timeout_per_call=5)
        assert results == [0, 1, 2, 3, 4]
