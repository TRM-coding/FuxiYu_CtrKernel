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

# 仍是过渡态时只更新最后已知状态，不解除“待核实”。缺席标记的清除条件必须是
# Node 给出可映射的稳定状态（online/offline/paused/failed），否则“重新出现”
# 只是又一次未完成，不能当作已恢复。
_TRANSITIONAL_CTRL_STATUSES = {
    ContainerStatus.BUILDING,
    ContainerStatus.CREATING,
    ContainerStatus.STARTING,
    ContainerStatus.STOPPING,
    ContainerStatus.RESTARTING,
}

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
    fields = {
        "container_status": ctrl_status,
        "failed_reason": failed_reason if ctrl_status == ContainerStatus.FAILED else None,
        "failed_detail": entry.get("failed_detail") if ctrl_status == ContainerStatus.FAILED else None,
        "port": entry.get("port"),
        "port_mappings": entry.get("port_mappings"),
    }
    if ctrl_status not in _TRANSITIONAL_CTRL_STATUSES:
        fields["status_unknown_since"] = None
        fields["status_source"] = None
    containers_repo.update_container(container.id, session=session, **fields)
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
    """接收一条磁盘样本：先落业务路径，再判断测量是否完整可信。

    `mount_path_status` 只在线路上用于“更新/保留/清空”，不落库、不参与资格判断。
    `measured_at` 是真实测量时间；缺失时只对旧 Node 兼容写入接收时间。失败/缺组成/
    路径不一致/时间无效都不写 0，也不刷新 `disk_checked_at`。
    """
    if not isinstance(usage, dict) or container is None:
        return False

    has_path_status = "mount_path_status" in usage
    path_status = None
    if has_path_status:
        raw_status = usage.get("mount_path_status")
        path_status = str(raw_status).strip().lower() if raw_status not in (None, "") else "unresolved"
        if path_status not in _DISK_PATH_STATUSES:
            logger.warning(
                "apply disk snapshot: unknown mount_path_status=%r machine_id=%s container=%s; preserve path",
                raw_status, machine_id, name,
            )
            path_status = "unresolved"

    frame_path = _normalize_disk_path(usage.get("bind_mount_path"))
    current_path = _normalize_disk_path(getattr(container, "bind_mount_path", None))
    no_bind_key = int(container.id)
    checked_at = getattr(container, "disk_checked_at", None)
    measured_at, measured_error = _parse_disk_measured_at(usage.get("measured_at"))

    # 已知旧帧不回退：先拒绝，再处理路径。真实测量时间相同但路径声明冲突的帧
    # 也不能改路径（路径修正必须先于测量，但冲突时宁可不改）。
    if measured_error == "invalid":
        pass  # 只拒绝测量，同帧合法路径仍可落库
    elif measured_at is not None and checked_at is not None and measured_at < checked_at:
        _log_disk_sample_rejected(
            machine_id, name, "measured_at_older_than_checkpoint", usage,
        )
        return False
    elif measured_at is not None and checked_at is not None and measured_at == checked_at:
        path_conflict = (
            (path_status == "resolved" and frame_path and frame_path != current_path)
            or (path_status == "no_bind" and current_path is not None)
        )
        if path_conflict:
            _log_disk_sample_rejected(
                machine_id, name, "same_measured_at_path_conflict", usage,
            )
            return False

    # 1) 路径：新协议按 status 更新/保留/清空；旧 Node 帧不得改写已校正路径。
    path_updates: dict = {}
    clear_fields: set[str] = set()
    measurement_path_ok = True
    if has_path_status:
        if path_status == "resolved" and frame_path:
            if frame_path != current_path:
                path_updates["bind_mount_path"] = frame_path
                clear_fields.update(_DISK_MEASUREMENT_FIELDS)
                logger.info(
                    "apply disk snapshot: path updated machine_id=%s container=%s %r -> %r",
                    machine_id, name, current_path, frame_path,
                )
            current_path = frame_path
            _NO_BIND_CONTAINERS.discard(no_bind_key)
        elif path_status == "no_bind":
            if current_path is not None:
                clear_fields.add("bind_mount_path")
                logger.info(
                    "apply disk snapshot: no_bind clears path machine_id=%s container=%s previous=%r",
                    machine_id, name, current_path,
                )
            current_path = None
            clear_fields.update(_DISK_MEASUREMENT_FIELDS)
            _NO_BIND_CONTAINERS.add(no_bind_key)
        # unresolved / not_running / resolved 但路径为空：保留当前路径，不清空。
    else:
        if current_path is None:
            if no_bind_key in _NO_BIND_CONTAINERS:
                if frame_path:
                    measurement_path_ok = False
                    _log_disk_sample_rejected(
                        machine_id, name, "legacy_frame_after_no_bind", usage,
                    )
            elif frame_path:
                # 旧协议兼容：仅当前无路径时允许建立（不是 Node 校正）。
                path_updates["bind_mount_path"] = frame_path
                clear_fields.update(_DISK_MEASUREMENT_FIELDS)
                current_path = frame_path
                logger.info(
                    "apply disk snapshot: legacy path established machine_id=%s container=%s path=%r",
                    machine_id, name, frame_path,
                )
        elif frame_path != current_path:
            measurement_path_ok = False
            _log_disk_sample_rejected(
                machine_id, name, "legacy_frame_path_mismatch", usage,
            )

    # 2) 测量：完整组成 + 路径一致 + 时间可解析。当前路径为空时只有明确 no_bind
    # 才允许 overlay-only。
    total_bytes = usage.get("total_bytes")
    overlay_rw_bytes = usage.get("overlay_rw_bytes")
    overlay_rw_source = usage.get("overlay_rw_source")
    bind_mount_bytes = usage.get("bind_mount_bytes")
    overlay_incomplete = (
        overlay_rw_bytes is None
        or overlay_rw_source in {"error", "missing", "not_found"}
    )
    measurement_accepted = False
    reject_reason = None
    if not measurement_path_ok:
        reject_reason = "path_inconsistent"
    elif measured_error == "invalid":
        reject_reason = "invalid_measured_at"
    elif has_path_status and measured_error == "missing":
        # 新协议必须带真实 measured_at；缺失只对无 mount_path_status 的旧 Node
        # 帧按接收时间兼容，不能把新协议的缓存心跳当成新测量。
        reject_reason = "measured_at_missing"
    elif total_bytes is None:
        reject_reason = "total_bytes_missing"
    elif overlay_incomplete:
        reject_reason = "overlay_incomplete"
    elif current_path is not None:
        if bind_mount_bytes is None:
            reject_reason = "bind_bytes_missing"
        elif frame_path != current_path:
            reject_reason = "path_inconsistent"
        else:
            measurement_accepted = True
    elif path_status != "no_bind":
        # 旧协议两者皆空无法证明 no_bind；新协议非 no_bind 也不允许 overlay-only。
        reject_reason = "no_bind_not_confirmed"
    elif frame_path is not None:
        # no_bind 与帧内非空路径自相矛盾，拒绝测量（路径已按 no_bind 清空）。
        reject_reason = "no_bind_with_path"
    else:
        measurement_accepted = True

    measurement_updates: dict = {}
    if measurement_accepted:
        measurement_updates = {
            "disk_overlay_rw_bytes": overlay_rw_bytes,
            "disk_bind_mount_bytes": bind_mount_bytes if current_path is not None else None,
            "disk_total_bytes": total_bytes,
            "disk_checked_at": measured_at or datetime.datetime.utcnow(),
        }
    else:
        _log_disk_sample_rejected(machine_id, name, reject_reason, usage)

    if not measurement_updates and not path_updates and not clear_fields:
        return False

    updates = {**measurement_updates, **path_updates}
    containers_repo.update_container(
        container.id,
        session=session,
        clear_fields=clear_fields or None,
        **updates,
    )
    return True


_DISK_PATH_STATUSES = {"resolved", "unresolved", "not_running", "no_bind"}
_DISK_MEASUREMENT_FIELDS = {
    "disk_overlay_rw_bytes",
    "disk_bind_mount_bytes",
    "disk_total_bytes",
    "disk_checked_at",
}
# 进程内 no_bind 标记：只用于拒绝旧 Node 帧把已明确清空的路径重建。不持久化；
# Ctrl 重启后丢失是已写明的兼容边界（不为此新增列）。
_NO_BIND_CONTAINERS: set[int] = set()
# 允许 5 分钟的 Node/Ctrl 时钟偏差；超过按无效测量处理，不刷新测量时间。
_MEASURED_AT_FUTURE_TOLERANCE = datetime.timedelta(minutes=5)


def _clear_no_bind_disk_markers() -> None:
    """测试用：清空进程内 no_bind 标记；生产路径不调用。"""

    _NO_BIND_CONTAINERS.clear()


def _normalize_disk_path(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_disk_measured_at(value) -> tuple[datetime.datetime | None, str | None]:
    """返回 (UTC naive 时间, 缺失/无效标记)。缺失 = None，无效 = 'invalid'。"""

    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "missing"
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None, "invalid"
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    if parsed > datetime.datetime.utcnow() + _MEASURED_AT_FUTURE_TOLERANCE:
        return None, "invalid"
    return parsed, None


def _log_disk_sample_rejected(machine_id, name, reason, usage: dict) -> None:
    logger.warning(
        "apply disk snapshot rejected: machine_id=%s container=%s reason=%s "
        "total=%s overlay=%s overlay_source=%s bind_bytes=%s path=%r status=%r measured_at=%r",
        machine_id, name, reason,
        usage.get("total_bytes"), usage.get("overlay_rw_bytes"), usage.get("overlay_rw_source"),
        usage.get("bind_mount_bytes"), usage.get("bind_mount_path"),
        usage.get("mount_path_status"), usage.get("measured_at"),
    )


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
        # 许可（gpu_allow_list）不自动 trim——GPU index 由
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
