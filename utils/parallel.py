"""NodeKernel 并发调用工具。

提供 `parallel_node_calls` 用于将多个独立的 NodeKernel HTTP 调用并行化，
从而避免串行 for 循环导致的延迟线性叠加。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, TypeVar

from flask import current_app

T = TypeVar("T")


def parallel_node_calls(
    calls: list[Callable[[], T]],
    pool_size: int | None = None,
    timeout_per_call: float | None = None,
) -> list[T | Exception]:
    """并发执行一组 NodeKernel 调用，返回与输入顺序一致的结果列表。

    每个 callable 在其自己的线程中执行。成功的返回值原样保留，失败或超时的
    调用返回对应的 Exception 对象供调用方按 ``isinstance(r, Exception)`` 判错。

    Args:
        calls: 无参 callable 列表，各自封装一次 NodeKernel HTTP 请求。
        pool_size: 线程池大小，默认读取 ``AppConfig.NODE_REQUEST_POOL_SIZE``。
        timeout_per_call: 单次调用的最长等待秒数，``None`` 表示不设上限
            （由 callable 内部的 requests timeout 自行控制）。

    Returns:
        与 *calls* 顺序一致的结果列表，成功元素为 ``T``，失败元素为 ``Exception``。
    """
    if not calls:
        return []

    if pool_size is None:
        try:
            pool_size = current_app.config.get("NODE_REQUEST_POOL_SIZE", 8)
        except RuntimeError:
            pool_size = 8
    pool_size = max(1, int(pool_size))

    results: list[T | Exception] = [Exception("unreachable")] * len(calls)

    with ThreadPoolExecutor(max_workers=pool_size) as executor:
        future_to_index = {
            executor.submit(call): idx for idx, call in enumerate(calls)
        }

        for future in future_to_index:  # pragma: no cover – as_completed 语义
            idx = future_to_index[future]
            try:
                if timeout_per_call is not None:
                    results[idx] = future.result(timeout=timeout_per_call)
                else:
                    results[idx] = future.result()
            except FutureTimeoutError:
                results[idx] = TimeoutError(
                    f"parallel_node_calls: callable[{idx}] timed out "
                    f"after {timeout_per_call}s"
                )
            except Exception as exc:
                results[idx] = exc

    return results
