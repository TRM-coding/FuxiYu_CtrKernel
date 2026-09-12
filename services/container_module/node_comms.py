from __future__ import annotations

import logging

import requests

from ...config import CommsConfig
from ...extensions import session_scope
from .node_comms_modules import runtime_cache as _runtime_cache
from .node_comms_modules.runtime_cache import (
    _split_container_runtime_snapshot,
    _update_container_runtime_cache,
    _write_machine_runtime_cache,
    _read_container_runtime_cache,
    _read_machine_runtime_cache,
)
from .node_comms_modules.runtime_push import _post_runtime_buffer, _read_internal_token
from .node_comms_modules.transport import _pin_file, _resolve_tls, _post_node_json, _decode_node_response
from .node_comms_modules.machine_access import _ensure_machine_online_for_operation
from .node_comms_modules.enrollment import _fetch_peer_cert
from .node_comms_modules.snapshots import (
    _NODE_STATUS_SKIP,
    _NODE_STATUS_TO_CTRL,
    _mark_machine_collect_error,
    _clear_machine_collect_error,
    _machine_containers_by_name,
    _prepare_status_runtime,
    _apply_container_status_entry,
    _log_container_snapshot_summary,
    _apply_last_ssh_entry,
    _apply_disk_usage_entry,
    _load_snapshot_machine,
    _derive_hardware_changes,
    _persist_hardware_changes,
    _log_system_snapshot,
    _resolve_snapshot_machine_id,
)
from .node_comms_modules.deletion import _handle_container_deleted
from .node_comms_modules.link import (
    LINK_PATH,
    build_link_ssl_context,
    link_url,
    load_link_targets,
    run_links_forever,
    sync_links,
)
from .node_comms_modules.websocket import (
    FRAME_QUEUE_MAXSIZE,
    _consume_frames,
    _consume_link,
    _enqueue_frame,
    _receive_node_frame,
    _route_node_frame,
)

# 上面从 link / websocket 引入的符号部分在本模块内不直接调用：
# 它们是门户对外的再导出面（run_node_links 与测试从这里取链路入口）。

logger = logging.getLogger(__name__)


############################################################
# HTTP Transport
############################################################

def get_full_url(machine_ip: str, endpoint: str) -> str:
    return f"https://{machine_ip}{CommsConfig.NODE_URL_MIDDLE}{endpoint}"


def send(url: str, payload: dict, timeout: float = 5.0, *, cert=None, verify=None) -> dict:
    """Send JSON over mTLS, retaining Node error bodies and transport failures."""
    cert, verify = _resolve_tls(url, cert=cert, verify=verify)
    try:
        response = _post_node_json(url, payload, timeout, cert, verify)
        return _decode_node_response(response)
    except requests.RequestException as exc:
        logger.error("Request error: %s", exc)
        return {"error": str(exc)}


############################################################
# Runtime Cache Reads and Writes
############################################################

def write_container_runtime_buffer(machine_id: int, snapshot: dict) -> int:
    if machine_id is None or not isinstance(snapshot, dict):
        return 0
    updates, clears = _split_container_runtime_snapshot(snapshot)
    if not updates and not clears:
        return 0
    _update_container_runtime_cache(machine_id, updates, clears)
    return len(updates) + len(clears)


def write_machine_runtime_buffer(machine_id: int, snapshot: dict) -> int:
    if machine_id is None or not isinstance(snapshot, dict):
        return 0
    _write_machine_runtime_cache(machine_id, snapshot)
    return 1


def get_cached_container_runtime_metrics(machine_id: int | None, container_name: str | None) -> dict | None:
    if machine_id is None or not container_name:
        return None
    return _read_container_runtime_cache(machine_id, container_name)


def get_cached_machine_runtime_snapshot(machine_id: int | None) -> dict | None:
    if machine_id is None:
        return None
    return _read_machine_runtime_cache(machine_id)


def clear_runtime_buffers() -> None:
    with _runtime_cache._RUNTIME_BUFFER_LOCK:
        _runtime_cache._CONTAINER_RUNTIME_BUFFER.clear()
        _runtime_cache._MACHINE_RUNTIME_BUFFER.clear()


############################################################
# Snapshot Application and Batch Dispatch
############################################################

def apply_container_status_snapshot(data: dict, machine_id: int | None = None) -> dict:
    """Apply machine-scoped status; empty/error snapshots never trigger disappearance cleanup."""
    result = {"updated": 0, "skipped": 0, "vanished": 0, "failed": 0}
    if not isinstance(data, dict):
        return result
    if "collect_error" in data:
        _mark_machine_collect_error(machine_id)
        return result
    if not data:
        logger.warning("apply_container_status_snapshot: empty snapshot (machine=%s) ignored", machine_id)
        return result
    runtime, missing_names = None, []
    try:
        with session_scope() as session:
            containers = _machine_containers_by_name(machine_id, session) or {}
            runtime, missing_names = _prepare_status_runtime(data, containers, machine_id, session)
            for name, entry in data.items():
                outcome = _apply_container_status_entry(name, entry, containers.get(name), session)
                result["updated"] += outcome != "skipped"
                result["skipped"] += outcome == "skipped"
                result["failed"] += outcome == "failed"
            _clear_machine_collect_error(machine_id, session)
    except Exception as exc:
        logger.warning("apply status snapshot failed: %s", exc)
        result["skipped"] += 1
    if runtime:
        _post_runtime_buffer("containers", {"machine_id": machine_id, "snapshot": runtime})
    for name in missing_names:
        _handle_container_deleted(name, machine_id)
        result["vanished"] += 1
    _log_container_snapshot_summary(machine_id, result, len(data))
    return result


def apply_last_ssh_snapshot(data: dict, machine_id: int | None = None) -> dict:
    result = {"updated": 0, "skipped": 0}
    if not isinstance(data, dict) or machine_id is None:
        return result
    try:
        with session_scope() as session:
            containers = _machine_containers_by_name(machine_id, session)
            for name, entry in data.items():
                updated = _apply_last_ssh_entry(entry, containers.get(name), session)
                result["updated" if updated else "skipped"] += 1
    except Exception as exc:
        logger.warning("apply last_ssh snapshot failed: %s", exc)
        result["skipped"] += 1
    return result


def apply_disk_usage_snapshot(data: dict, machine_id: int | None = None) -> dict:
    result = {"updated": 0, "skipped": 0}
    if not isinstance(data, dict) or machine_id is None:
        return result
    try:
        with session_scope() as session:
            containers = _machine_containers_by_name(machine_id, session)
            for name, usage in (data.get("containers") or {}).items():
                updated = _apply_disk_usage_entry(name, usage, containers.get(name), machine_id, session)
                result["updated" if updated else "skipped"] += 1
    except Exception as exc:
        logger.warning("apply disk snapshot failed: %s", exc)
        result["skipped"] += 1
    return result


def apply_sys_snapshot(data: dict, machine_id: int | None = None) -> dict:
    if not isinstance(data, dict) or machine_id is None:
        return {"checked": 0, "drifted": 0}
    if data:
        _post_runtime_buffer("machines", {"machine_id": machine_id, "snapshot": data})
    machine = _load_snapshot_machine(machine_id)
    if machine is None:
        logger.debug("apply_sys_snapshot: machine %s not found (deleted?)", machine_id)
        return {"checked": 0, "drifted": 0}
    drift, fields = _derive_hardware_changes(machine, data)
    if drift:
        _persist_hardware_changes(machine, data, drift, fields)
    _log_system_snapshot(machine, data)
    return {"checked": 1, "drifted": int(bool(drift))}


def apply_snapshot_batch(batch: dict) -> dict:
    """Resolve UID before dispatch; never fall back to a global container-name lookup."""
    result = {}
    if not isinstance(batch, dict):
        return result
    machine_id = _resolve_snapshot_machine_id(batch.get("node_uid"))
    if machine_id is None:
        return result
    handlers = {
        "container_status": apply_container_status_snapshot, "last_ssh": apply_last_ssh_snapshot,
        "disk_usage": apply_disk_usage_snapshot, "sys_snapshot": apply_sys_snapshot,
    }
    for frame in batch.get("payload") or []:
        if not isinstance(frame, dict) or frame.get("type") != "snapshot":
            continue
        topic = frame.get("topic")
        if isinstance(topic, str) and topic in handlers:
            result[topic] = handlers[topic](frame.get("payload"), machine_id)
        else:
            logger.warning("apply_snapshot_batch: unknown topic %r", topic)
    return result


############################################################
# Node Link Lifecycle
############################################################

# 链路的拨号、收帧与重连在 node_comms_modules.link / websocket 内实现；
# 本模块只负责把它们的门户与工具函数暴露给上层（run_node_links、machine_tasks）。
# machines 表即链路清单：表里有行就拨，停拨的唯一方式是删除机器行。
