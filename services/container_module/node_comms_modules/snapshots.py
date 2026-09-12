from __future__ import annotations

import datetime
import logging
import time

from ....constant import ContainerStatus, MachineStatus
from ....extensions import session_scope
from ....repositories import containers_repo, machine_repo
from ....repositories.container_ssh_login_repo import upsert_last_ssh_login_time
from ..utils import _parse_last_ssh_time
from .heartbeat import _last_container_summary, _log_heartbeat

logger = logging.getLogger(__name__)

_NODE_STATUS_TO_CTRL = {
    "online": ContainerStatus.ONLINE,
    "offline": ContainerStatus.OFFLINE,
    "building": ContainerStatus.BUILDING,
    "creating": ContainerStatus.CREATING,
    "starting": ContainerStatus.STARTING,
    "restarting": ContainerStatus.RESTARTING,
    "stopping": ContainerStatus.STOPPING,
    "paused": ContainerStatus.PAUSED,
    "failed": ContainerStatus.FAILED,
}
_NODE_STATUS_SKIP = {"pausing", "unpausing", "unknown"}

def _mark_machine_collect_error(machine_id: int | None) -> None:
    if machine_id is None:
        logger.warning("apply status snapshot: collect_error without machine_id; skipped")
        return
    try:
        with session_scope() as session:
            machine = machine_repo.get_by_id(machine_id, session=session)
            if machine is not None and machine.collect_error_at is None:
                machine_repo.update_machine(
                    machine_id, collect_error_at=datetime.datetime.utcnow(), session=session,
                )
    except Exception as exc:
        logger.warning("apply collect_error snapshot failed: machine=%s err=%s", machine_id, exc)
    logger.info("apply_container_status_snapshot: collect_error machine=%s", machine_id)


def _clear_machine_collect_error(machine_id, session) -> None:
    if machine_id is not None:
        machine = machine_repo.get_by_id(machine_id, session=session)
        if machine is not None and machine.collect_error_at is not None:
            # update_machine skips None; clearing the marker needs an explicit assignment.
            machine.collect_error_at = None
            session.flush()


def _machine_containers_by_name(machine_id: int, session) -> dict | None:
    """机器作用域容器名映射（数据通路对账契约 C5：快照落库按机器内查找，避免跨机器重名误写）。

    机器归位缺失（不降级全局 name 查找）→ 返回 None，调用方跳过该帧。
    """
    if machine_id is None:
        return None
    containers = containers_repo.list_containers(
        limit=1000000,
        offset=0,
        machine_id=machine_id,
        session=session,
    )
    return {container.name: container for container in containers}


def _prepare_status_runtime(data, containers_by_name, machine_id, session) -> tuple[dict, list[str]]:
    if machine_id is None:
        return {}, []
    machine = machine_repo.get_by_id(machine_id, session=session)
    status = getattr(machine, "machine_status", None)
    status_value = status.value if hasattr(status, "value") else str(status or "")
    known_snapshot = {name: entry for name, entry in data.items() if name in containers_by_name}
    if known_snapshot and status_value != MachineStatus.ONLINE.value:
        known_snapshot = {
            name: {
                "status": (entry or {}).get("status"),
                "failed_reason": (entry or {}).get("failed_reason") or (entry or {}).get("error_reason"),
                "failed_detail": (entry or {}).get("failed_detail"),
            }
            for name, entry in known_snapshot.items()
        }
    return known_snapshot, sorted(set(containers_by_name) - set(data))


def _apply_unknown_container_status(container, entry, session) -> str:
    if container is None:
        return "skipped"
    source = str(entry.get("status_source") or "unknown")
    since = None
    if entry.get("unknown_since"):
        try:
            since = datetime.datetime.fromisoformat(str(entry["unknown_since"]))
        except ValueError:
            pass
    since = since or datetime.datetime.utcnow()
    if container.status_source == source and container.status_unknown_since == since:
        return "skipped"
    containers_repo.update_container(
        container.id, status_unknown_since=since, status_source=source, session=session,
    )
    logger.warning("apply status snapshot: container %s status_unknown source=%s since=%s", container.name, source, since)
    return "updated"


def _apply_container_status_entry(name, entry, container, session) -> str:
    entry = entry or {}
    raw_status = str(entry.get("status", ""))
    if raw_status == "unknown":
        return _apply_unknown_container_status(container, entry, session)
    ctrl_status = _NODE_STATUS_TO_CTRL.get(raw_status)
    if ctrl_status is None:
        if raw_status in _NODE_STATUS_SKIP:
            logger.debug("apply status snapshot: transition state %r skipped (name=%s)", raw_status, name)
        else:
            logger.warning("apply status snapshot: unmapped status %r skipped (name=%s)", raw_status, name)
        return "skipped"
    if container is None:
        return "skipped"
    failed_reason = entry.get("failed_reason") or entry.get("error_reason")
    containers_repo.update_container(
        container.id, container_status=ctrl_status,
        failed_reason=failed_reason if ctrl_status == ContainerStatus.FAILED else None,
        failed_detail=entry.get("failed_detail") if ctrl_status == ContainerStatus.FAILED else None,
        status_unknown_since=None, status_source=None,
        port=entry.get("port"), port_mappings=entry.get("port_mappings"), session=session,
    )
    return "failed" if ctrl_status == ContainerStatus.FAILED else "updated"


def _log_container_snapshot_summary(machine_id, result, snapshot_size: int) -> None:
    summary = (result["updated"], result["skipped"], result["vanished"], snapshot_size)
    previous = _last_container_summary.get(str(machine_id))
    _last_container_summary[str(machine_id)] = summary
    noteworthy = bool(result["vanished"]) or summary != previous
    _log_heartbeat(
        f"cont-{machine_id}", logging.INFO if noteworthy else logging.DEBUG,
        "apply_container_status_snapshot: machine=%s updated=%s skipped=%s vanished=%s snapshot=%s",
        machine_id, *summary, anomaly=False,
    )


def _apply_last_ssh_entry(entry, container, session) -> bool:
    last_time = (entry or {}).get("last_ssh_connect_time")
    if not last_time or container is None:
        return False
    parsed = _parse_last_ssh_time(str(last_time))
    if parsed is not None:
        last_time = parsed.strftime("%Y-%m-%dT%H:%M:%S")
    upsert_last_ssh_login_time(
        machine_id=container.machine_id, container_id=container.id,
        last_ssh_login_time=last_time, session=session,
    )
    return True


def _apply_disk_usage_entry(name, usage, container, machine_id, session) -> bool:
    if not isinstance(usage, dict) or container is None:
        return False
    total_bytes = usage.get("total_bytes")
    overlay_rw_bytes = usage.get("overlay_rw_bytes")
    overlay_rw_source = usage.get("overlay_rw_source")
    bind_mount_path = usage.get("bind_mount_path")
    bind_mount_bytes = usage.get("bind_mount_bytes")
    overlay_incomplete = overlay_rw_bytes is None or overlay_rw_source in {"error", "missing", "not_found"}
    if total_bytes is None or overlay_incomplete or (bind_mount_path and bind_mount_bytes is None):
        logger.warning(
            "apply disk snapshot skipped incomplete measurement: machine_id=%s container=%s total=%s overlay=%s overlay_source=%s bind=%s path=%s",
            machine_id, name, total_bytes, overlay_rw_bytes, overlay_rw_source, bind_mount_bytes, bind_mount_path,
        )
        return False
    containers_repo.update_container(
        container.id, disk_overlay_rw_bytes=overlay_rw_bytes, disk_bind_mount_bytes=bind_mount_bytes,
        disk_total_bytes=total_bytes, bind_mount_path=bind_mount_path,
        disk_checked_at=datetime.datetime.utcnow(), session=session,
    )
    return True


def _load_snapshot_machine(machine_id: int):
    try:
        with session_scope(commit=False) as session:
            return machine_repo.get_by_id(machine_id, session=session)
    except Exception:
        return None


def _derive_hardware_changes(machine, data: dict) -> tuple[dict, dict]:
    cpu = (data.get("cpu") or {}).get("cores")
    mem = (data.get("memory") or {}).get("total_gb")
    # disk 新契约（2026-08）：bind_mount/docker_data 两挂载点，disk_size_gb 存 bind_mount 分区容量（显示用）
    disk = (data.get("disk") or {}).get("bind_mount", {}).get("total_gb")
    gpus = data.get("gpu") or []

    new_cpu = int(cpu) if cpu is not None else None
    new_mem = int(mem) if mem is not None else None
    new_disk = int(disk) if disk is not None else None
    new_gpu_count = len(gpus)

    drift = {}
    if new_cpu is not None and new_cpu != (machine.cpu_core_number or 0):
        drift["cpu_core_number"] = f"{machine.cpu_core_number} -> {new_cpu}"
    if new_mem is not None and new_mem != (machine.memory_size_gb or 0):
        drift["memory_size_gb"] = f"{machine.memory_size_gb} -> {new_mem}"
    if new_disk is not None and new_disk != (machine.disk_size_gb or 0):
        drift["disk_size_gb"] = f"{machine.disk_size_gb} -> {new_disk}"
    if new_gpu_count != (machine.gpu_number or 0):
        drift["gpu_number"] = f"{machine.gpu_number} -> {new_gpu_count}"

    fields: dict = {}
    if "cpu_core_number" in drift:
        fields["cpu_core_number"] = new_cpu
        if (machine.max_cpu_core_number or 0) > new_cpu:
            fields["max_cpu_core_number"] = new_cpu
    if "memory_size_gb" in drift:
        fields["memory_size_gb"] = new_mem
        if (machine.max_memory_gb or 0) > new_mem:
            fields["max_memory_gb"] = new_mem
    if "disk_size_gb" in drift:
        fields["disk_size_gb"] = new_disk
    if "gpu_number" in drift:
        fields["gpu_number"] = new_gpu_count
        gpu_type = (gpus[0].get("name", "") if gpus else "")
        if gpu_type:
            fields["gpu_type"] = gpu_type
        # GPU 三集合建模（决策）：gpu_list 是事实（smi 枚举）随帧更新；
        # 许可（gpu_allow_list）与 max_gpu_number 不自动 trim——GPU index 由
        # nvidia-smi 决定、非系统可控，许可调整走人工（枚举变化时告警见上）。
        gpu_indices = []
        for g in gpus:
            idx = g.get("index")
            if idx is not None:
                try:
                    gpu_indices.append(int(idx))
                except (TypeError, ValueError):
                    continue
        fields["gpu_list"] = gpu_indices
    return drift, fields


def _persist_hardware_changes(machine, data, drift, fields) -> None:
    if fields:
        try:
            with session_scope() as session:
                machine_repo.update_machine(machine.id, session=session, **fields)
        except Exception as exc:
            logger.warning("apply_sys_snapshot: hardware db update failed for machine %s: %s", machine.id, exc)
    logger.warning(
        "apply_sys_snapshot: HARDWARE DRIFT on machine %s (%s): %s -> db updated, max_* trimmed",
        machine.id, data.get("hostname"), drift,
    )


def _log_system_snapshot(machine, data) -> None:
    cpu_usage = (data.get("cpu") or {}).get("usage_percent")
    mem_usage = (data.get("memory") or {}).get("usage_percent")
    disk_percent = (data.get("disk") or {}).get("percent")
    collect_error = bool(data.get("collect_error"))
    machine_status = getattr(machine, "machine_status", None)
    status_value = machine_status.value if hasattr(machine_status, "value") else str(machine_status or "")
    anomalous = (
        cpu_usage is None or mem_usage is None or disk_percent is None
        or collect_error
        or status_value.lower() != "online"
    )
    _log_heartbeat(
        f"sys-{machine.id}",
        logging.INFO if anomalous else logging.DEBUG,
        "apply_sys_snapshot: machine %s (%s) cpu=%s%% mem=%s%% disk=%s%% (collect_error=%s, machine_status=%s)",
        machine.id, data.get("hostname"), cpu_usage, mem_usage, disk_percent,
        collect_error, status_value,
        anomaly=anomalous,
    )


def _resolve_snapshot_machine_id(node_uid) -> int | None:
    if node_uid:
        try:
            with session_scope(commit=False) as session:
                machine = machine_repo.get_by_uid(node_uid, session=session)
            if machine is not None:
                return machine.id
        except Exception:
            pass
    logger.warning("apply_snapshot_batch: node_uid %r unresolved or missing; dropping batch", node_uid)
    return None


############################################################
# 采集心跳（last_seen_at）
############################################################

# 同一机器 60s 内只写一次库。快照每 5s 一批，逐批 UPDATE 没有必要；
# 而窗口语义以天计，60s 粒度绰绰有余。
_LAST_SEEN_MIN_INTERVAL = 60.0
_last_seen_written: dict[int, float] = {}


def _touch_machine_last_seen(machine_id: int) -> None:
    """记下「Ctrl 此刻听到过这台机器」。

    只要批次被应用就算听到——**含采集异常批**（对端可达但采集失败），
    语义是链路层的事实，与采集内容是否正常无关。

    失败只告警：心跳丢了不影响本批快照落库，下一批还会再来。
    """

    now = time.time()
    if now - _last_seen_written.get(machine_id, 0.0) < _LAST_SEEN_MIN_INTERVAL:
        return
    _last_seen_written[machine_id] = now
    try:
        with session_scope() as session:
            machine_repo.touch_last_seen(machine_id, datetime.datetime.utcnow(), session=session)
    except Exception as exc:
        logger.warning("touch last_seen failed for machine %s: %s", machine_id, exc)
