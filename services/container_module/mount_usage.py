"""已删除容器遗留挂载用量的只读查询编排。

口径（见 openspec show-mount-path-and-deleted-usage）：

- 只从既有删除快照/清理记录解析 ``machine_id``/``mount_path``，复用
  ``_get_deleted_container_context`` 的只读语义；不调用 ensure/adopt/写库路径。
- Ctrl 不缓存、不轮询；每次请求按 ``(machine_id, path)`` 去重后向对应 Node
  批量查询，按机器有限并发、短超时。
- Node 回显 path 必须与请求路径精确匹配；成功/pending/错误三态严格校验，
  不填 0、不伪造成功。
"""

from __future__ import annotations

import re
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
from datetime import datetime, timedelta

import requests

from ...constant import MachineStatus
from ...extensions import session_scope
from ...repositories import (
    container_mount_cleanup_repo,
    deleted_container_restore_snapshot_repo,
    machine_repo,
)
from . import deleted_containers, node_comms
from .node_comms_modules import endpoint as node_endpoint

MAX_DELETED_IDS = 100
# Node 侧慢 du 只返回 pending，故查询本身用短超时；不继承动作通道的 30 秒默认值。
NODE_QUERY_TIMEOUT_SECONDS = 5.0
# Web 本轮专用超时为 10 秒；整批预算留在 8 秒，给 HTTP 传输与渲染留余量。
NODE_BATCH_DEADLINE_SECONDS = 8.0
MAX_CONCURRENT_NODE_REQUESTS = 8

NODE_UNSUPPORTED = "node_unsupported"
NODE_TIMEOUT = "node_timeout"
NODE_UNAVAILABLE = "node_unavailable"
NODE_BAD_RESPONSE = "node_bad_response"
NOT_FOUND = "not_found"

_MOUNT_FIELDS = ("path", "bytes", "measured_at", "pending", "error")
_UTC_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)
_STABLE_ERROR_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _is_int(value) -> bool:
    """bool 是 int 的子类，但绝不是这里要的整数。"""

    return type(value) is int


def _is_utc_timestamp(value) -> bool:
    """只接受带 ``T`` 时间部分的 UTC ISO-8601；拒绝日期、空格分隔和本地时间。"""

    if not isinstance(value, str) or not _UTC_ISO_RE.fullmatch(value):
        return False
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _is_stable_error(value) -> bool:
    """Node per-path 错误是稳定代码，不是可任意拼接的 stderr 文案。"""

    return isinstance(value, str) and _STABLE_ERROR_RE.fullmatch(value) is not None


def _bad(reason: str) -> dict:
    return {
        "bytes": None,
        "measured_at": None,
        "pending": False,
        "error": reason,
    }


def _pending() -> dict:
    return {
        "bytes": None,
        "measured_at": None,
        "pending": True,
        "error": None,
    }


def _success(bytes_value: int, measured_at: str) -> dict:
    return {
        "bytes": bytes_value,
        "measured_at": measured_at,
        "pending": False,
        "error": None,
    }


def _normalize_mount_state(entry: dict) -> dict | None:
    """严格校验三态组合；任一字段越界或缺失即整条作废，不采纳部分字段。"""

    if any(field not in entry for field in _MOUNT_FIELDS):
        return None

    bytes_value = entry.get("bytes")
    measured_at = entry.get("measured_at")
    pending = entry.get("pending")
    error = entry.get("error")

    if pending is True:
        if bytes_value is None and measured_at is None and error is None:
            return _pending()
        return None

    if pending is not False:
        return None

    if error is None:
        if _is_int(bytes_value) and bytes_value >= 0 and _is_utc_timestamp(measured_at):
            return _success(bytes_value, measured_at)
        return None

    if bytes_value is None and measured_at is None and _is_stable_error(error):
        return _bad(error)
    return None


def _parse_mount_response(response, requested_paths: list[str]) -> dict[str, dict]:
    """把 Node 响应映射为 ``path -> 三态``；任何不确定都回退为 bad_response。"""

    bad_all = {path: _bad(NODE_BAD_RESPONSE) for path in requested_paths}
    if not isinstance(response, dict) or not (type(response.get("success")) is int and response["success"] == 1):
        return bad_all

    mounts = response.get("mounts")
    if not isinstance(mounts, list):
        return bad_all

    requested = set(requested_paths)
    entries: dict[str, dict] = {}
    duplicates: set[str] = set()
    for entry in mounts:
        if not isinstance(entry, dict) or "path" not in entry:
            return bad_all
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            return bad_all
        if path not in requested:
            # 未请求的额外 path 不参与映射，更不借用它的结果。
            continue
        if path in entries:
            duplicates.add(path)
        else:
            entries[path] = entry

    resolved: dict[str, dict] = {}
    for path in requested_paths:
        if path in duplicates or path not in entries:
            resolved[path] = _bad(NODE_BAD_RESPONSE)
            continue
        state = _normalize_mount_state(entries[path])
        resolved[path] = state if state is not None else _bad(NODE_BAD_RESPONSE)
    return resolved


def _transport_reason(response=None, exc: Exception | None = None) -> str:
    """把 Node HTTP/传输失败归入稳定契约原因。"""

    if exc is not None:
        if isinstance(exc, requests.Timeout) or "timeout" in type(exc).__name__.lower():
            return NODE_TIMEOUT
        return NODE_UNAVAILABLE

    if not isinstance(response, dict):
        return NODE_BAD_RESPONSE

    status = response.get("status_code")
    if _is_int(status) and not (200 <= status <= 299):
        if status in (404, 405):
            return NODE_UNSUPPORTED
        if 500 <= status <= 599:
            return NODE_UNAVAILABLE
        return NODE_BAD_RESPONSE

    message = str(response.get("error") or "").lower()
    if "timeout" in message or "timed out" in message:
        return NODE_TIMEOUT
    if "error" in response:
        return NODE_UNAVAILABLE
    return NODE_BAD_RESPONSE


def _query_machine(group: dict) -> dict[str, dict]:
    """单机批量查询。一个机器的失败只落到本组，不抛给其他机器。"""

    paths = list(group["paths"])
    if not group.get("online") or not group.get("host"):
        return {path: _bad(NODE_UNAVAILABLE) for path in paths}

    url = node_comms.get_full_url(
        group["host"],
        "/check_mount_usage",
        group["port"],
    )
    payload = {"config": {"mount_paths": paths}}
    try:
        response = node_comms.send(url, payload, timeout=NODE_QUERY_TIMEOUT_SECONDS)
    except Exception as exc:
        return {path: _bad(_transport_reason(exc=exc)) for path in paths}

    if not isinstance(response, dict):
        return {path: _bad(NODE_BAD_RESPONSE) for path in paths}

    status = response.get("status_code")
    if _is_int(status) and not (200 <= status <= 299):
        return {path: _bad(_transport_reason(response=response)) for path in paths}
    # 没有 HTTP 状态、也没有业务字段，只有 error：这是 send 折叠后的传输失败。
    # 有 2xx 状态的同类 body 属于坏响应，交给下面的严格解析。
    if (
        "status_code" not in response
        and "success" not in response
        and "mounts" not in response
        and "error" in response
    ):
        return {path: _bad(_transport_reason(response=response)) for path in paths}
    return _parse_mount_response(response, paths)


def _query_groups(
    machines: dict[int, dict],
    *,
    deadline_seconds: float | None = None,
) -> dict[int, dict[str, dict]]:
    """按机器有限并发查询，并在整批预算内返回。

    预算用完时：已完成的机器保留结果，运行中/排队的机器统一回 ``node_timeout``，
    并取消尚未启动的 future。这里刻意不用 ``with ThreadPoolExecutor``，
    因为它的 ``shutdown(wait=True)`` 会等慢机器，把整批预算重新拖长。
    """

    if not machines:
        return {}

    budget = NODE_BATCH_DEADLINE_SECONDS if deadline_seconds is None else deadline_seconds
    deadline = time.monotonic() + max(float(budget), 0.0)
    results: dict[int, dict[str, dict]] = {}
    workers = min(MAX_CONCURRENT_NODE_REQUESTS, len(machines))
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mount-usage")
    futures = {
        executor.submit(_query_machine, group): machine_id
        for machine_id, group in machines.items()
    }
    pending = set(futures)

    def _collect(future):
        machine_id = futures[future]
        try:
            results[machine_id] = future.result()
        except Exception:
            results[machine_id] = {
                path: _bad(NODE_UNAVAILABLE) for path in machines[machine_id]["paths"]
            }

    try:
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                for future in as_completed(pending, timeout=remaining):
                    pending.discard(future)
                    _collect(future)
                    if time.monotonic() >= deadline:
                        break
            except FuturesTimeoutError:
                break
    finally:
        for future in list(pending):
            machine_id = futures[future]
            if future.done() and not future.cancelled():
                pending.discard(future)
                _collect(future)
                continue
            future.cancel()
            pending.discard(future)
            results[machine_id] = {
                path: _bad(NODE_TIMEOUT) for path in machines[machine_id]["paths"]
            }
        # 不等待运行中的 HTTP；它们受 NODE_QUERY_TIMEOUT_SECONDS 约束。
        executor.shutdown(wait=False, cancel_futures=True)

    for machine_id, group in machines.items():
        results.setdefault(
            machine_id,
            {path: _bad(NODE_TIMEOUT) for path in group["paths"]},
        )
    return results


def _normalize_machine_id(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _machine_is_online(machine) -> bool:
    status = getattr(machine, "machine_status", None)
    value = getattr(status, "value", status)
    return str(value or "").lower() == MachineStatus.ONLINE.value


def _unique_deleted_ids(deleted_ids: list[int]) -> list[int]:
    if not isinstance(deleted_ids, list):
        raise ValueError("deleted_ids must be a list")
    if len(deleted_ids) > MAX_DELETED_IDS:
        raise ValueError("deleted_ids exceeds the maximum of 100")
    unique: list[int] = []
    seen: set[int] = set()
    for value in deleted_ids:
        if not _is_int(value) or value < 1:
            raise ValueError("deleted_ids must contain positive integers only")
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _resolve_targets(deleted_ids: list[int]):
    """只读解析请求记录；返回 (outcomes, machines)，不写任何表。"""

    outcomes: dict[int, dict] = {}
    machines: dict[int, dict] = {}

    with session_scope(commit=False) as session:
        for deleted_id in deleted_ids:
            row = deleted_container_restore_snapshot_repo.get_by_id(deleted_id, session=session)
            if row is None:
                outcomes[deleted_id] = {"deleted_id": deleted_id, **_bad(NOT_FOUND)}
                continue

            cleanup = None
            if row.mount_cleanup_id:
                cleanup = container_mount_cleanup_repo.get_by_id(
                    row.mount_cleanup_id,
                    session=session,
                )
            else:
                cleanup = container_mount_cleanup_repo.get_by_deleted_id(
                    row.id,
                    session=session,
                )

            context = deleted_containers._get_deleted_container_context(
                row,
                cleanup,
                session=session,
            )
            mount_path = context.get("mount_path")
            if not isinstance(mount_path, str) or not mount_path:
                continue

            machine_id = _normalize_machine_id(context.get("machine_id"))
            if machine_id is None:
                # 兼容历史清理记录：machine_id 只存在于 cleanup 行时仍按该行定向。
                machine_id = _normalize_machine_id(getattr(cleanup, "machine_id", None))
            if machine_id is None:
                outcomes[deleted_id] = {"deleted_id": deleted_id, **_bad(NOT_FOUND)}
                continue

            machine = context.get("machine")
            if machine is None or _normalize_machine_id(getattr(machine, "id", None)) != machine_id:
                machine = machine_repo.get_by_id(machine_id, session=session)

            if machine is None:
                host, port, online = None, None, False
            else:
                try:
                    host, port = node_endpoint.machine_endpoint(machine)
                    online = bool(host) and _machine_is_online(machine)
                except Exception:
                    # 端点本身不可解析也只影响这台机器，不拖垮同页其他机器。
                    host, port, online = None, None, False

            group = machines.get(machine_id)
            if group is None:
                group = {
                    "machine_id": machine_id,
                    "host": host,
                    "port": port,
                    "online": online,
                    "paths": {},
                }
                machines[machine_id] = group
            group["paths"].setdefault(mount_path, []).append(deleted_id)

    return outcomes, machines


def get_deleted_container_mount_usage(
    deleted_ids: list[int],
    *,
    deadline_seconds: float | None = None,
) -> dict:
    """只读查询当前页已删容器的挂载用量；不持久化、不轮询。"""

    ordered_ids = _unique_deleted_ids(deleted_ids)
    outcomes, machines = _resolve_targets(ordered_ids)

    machine_results = _query_groups(machines, deadline_seconds=deadline_seconds)
    for machine_id, group in machines.items():
        states = machine_results.get(machine_id) or {}
        for path, target_ids in group["paths"].items():
            state = states.get(path)
            if state is None:
                state = _bad(NODE_BAD_RESPONSE)
            for deleted_id in target_ids:
                outcomes[deleted_id] = {"deleted_id": deleted_id, **state}

    return {"usages": [outcomes[deleted_id] for deleted_id in ordered_ids if deleted_id in outcomes]}
