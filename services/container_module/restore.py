from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ...constant import OperationType, ROLE
from ...extensions import session_scope
from ...repositories import (
    container_mount_cleanup_repo,
    containers_repo,
    deleted_container_restore_snapshot_repo,
    long_term_container_repo,
    user_repo,
)
from ...utils.Container import Container_info
from ..operation_log_tasks import log_failure, log_success
from .deleted_containers import (
    delete_restore_artifacts,
    restore_accounts_from_snapshot,
)
from .exceptions import NodeServiceError
from .utils import _container_log_detail

####################################################
# 恢复工具族（复活软删容器）
# 门户 resurrect_container / clean_deleted_container_mount 在 services/container_tasks.py。
# 顺序 = 门户调用顺序：读快照 → 读账号 → 组容器 → 复用 Create_container 复活原行
# → 恢复长期态 → 清退恢复产物 → 审计。
# 命名冲突：原名被占用时自动改名 {name}_{YYYYMMDD}_{原 id}（带重试）。
# 恢复失败与 mount 预检失败的审计也在这里（各一条，互不重复）。
####################################################

def _resolve_restore_container_name(
    name: str,
    machine_id: int,
    original_container_id: int,
    removed_at: datetime | None,
) -> tuple[str, bool]:
    with session_scope(commit=False) as session:
        existing_id = containers_repo.get_id_by_name_machine(
            name,
            machine_id,
            session=session,
        )
    if not existing_id or int(existing_id) == int(original_container_id):
        return name, False

    suffix_date = (removed_at or datetime.utcnow()).strftime("%Y%m%d")
    for attempt in range(1, 100):
        suffix = (
            f"_{suffix_date}_{original_container_id}"
            if attempt == 1
            else f"_{suffix_date}_{original_container_id}_{attempt}"
        )
        stem = (name or "container")[: max(2, 115 - len(suffix))]
        candidate = f"{stem}{suffix}"[:115]
        with session_scope(commit=False) as session:
            candidate_id = containers_repo.get_id_by_name_machine(
                candidate,
                machine_id,
                session=session,
            )
        if not candidate_id or int(candidate_id) == int(original_container_id):
            return candidate, True

    raise NodeServiceError(
        "failed to allocate restore container name",
        reason="container_exists",
    )


@dataclass(frozen=True)
class _RestoreTarget:
    """恢复上下文：一次读齐后续步骤要用的快照信息（只读，步骤间不再回查）。"""
    snapshot: dict
    container_id: int
    machine_id: int
    mount_path: str
    mount_cleanup_id: int | None
    removed_at: datetime | None


def _audit_restore_failure(deleted_id, operator_user_id, exc) -> None:
    """失败审计：尽力从快照回捞容器身份；查不到也照记（target_id=0），不吞原异常。"""
    target_id = 0
    container_name = None
    machine_id = None
    try:
        with session_scope(commit=False) as session:
            deleted = deleted_container_restore_snapshot_repo.get_by_id(
                int(deleted_id),
                session=session,
            )
            if deleted is not None:
                snapshot = dict(deleted.snapshot or {})
                target_id = int(
                    snapshot.get("container_id")
                    or deleted.original_container_id
                    or 0
                )
                container_name = snapshot.get("container_name")
                machine_id = deleted.machine_id or snapshot.get("machine_id")
    except Exception:
        pass
    log_failure(
        OperationType.CREATE_CONTAINER,
        target_id,
        target_type="container",
        operator_user_id=operator_user_id,
        container_name=container_name,
        machine_id=machine_id,
        error_reason=getattr(exc, "reason", None)
        or getattr(exc, "error_reason", None)
        or str(exc),
        detail={"trigger": "resurrect", "deleted_id": deleted_id},
    )


def _load_restore_target(deleted_id: int) -> _RestoreTarget:
    """读恢复上下文，并做可恢复性预检。

    预检不过一律抛 NodeServiceError（reason 供 api 层映射状态码）：
    快照缺失 / 快照为空 / 无保留挂载路径 / 挂载已被清理 / 缺 machine_id 或原容器 id。
    """
    try:
        deleted_id = int(deleted_id)
    except Exception:
        raise NodeServiceError("invalid deleted_id", reason="invalid_payload")

    with session_scope(commit=False) as session:
        deleted = deleted_container_restore_snapshot_repo.get_by_id(
            deleted_id,
            session=session,
        )
        if deleted is None:
            raise NodeServiceError(
                "deleted container snapshot not found",
                reason="not_found",
            )
        cleanup = (
            container_mount_cleanup_repo.get_by_id(
                deleted.mount_cleanup_id,
                session=session,
            )
            if deleted.mount_cleanup_id
            else None
        )
        snapshot = dict(deleted.snapshot or {})
        if not snapshot:
            raise NodeServiceError(
                "deleted container snapshot is empty",
                reason="data_not_recoverable",
            )
        original_container_id = int(
            snapshot.get("container_id")
            or deleted.original_container_id
            or 0
        )
        container_record = (
            containers_repo.get_by_id(
                original_container_id,
                session=session,
                include_invalid=True,
            )
            if original_container_id
            else None
        )
        mount_path = (
            getattr(container_record, "bind_mount_path", None)
            or (getattr(cleanup, "mount_path", None) if cleanup else None)
            or snapshot.get("bind_mount_path")
        )
        if not mount_path:
            raise NodeServiceError(
                "deleted container has no retained mount path",
                reason="data_not_recoverable",
            )
        if bool(getattr(deleted, "mount_cleaned", False)):
            raise NodeServiceError(
                "deleted container mount has been cleaned",
                reason="data_not_recoverable",
            )
        machine_id = int(deleted.machine_id or snapshot.get("machine_id") or 0)
        if container_record is not None:
            machine_id = int(container_record.machine_id)
        mount_cleanup_id = deleted.mount_cleanup_id
        removed_at = deleted.removed_at

    if not machine_id:
        raise NodeServiceError(
            "deleted container snapshot has no machine_id",
            reason="invalid_payload",
        )
    if not original_container_id:
        raise NodeServiceError(
            "deleted container snapshot has no original container id",
            reason="data_not_recoverable",
        )

    return _RestoreTarget(snapshot, original_container_id, machine_id, mount_path, mount_cleanup_id, removed_at)


def _load_restore_accounts(snapshot: dict) -> tuple[dict, list[dict]]:
    """读账号：root（owner）必须仍存在；协作者逐个回查系统用户名，已注销的直接跳过。"""
    root_account, restored_accounts = restore_accounts_from_snapshot(snapshot)
    owner_user_id = root_account.get("user_id")
    if not owner_user_id:
        raise NodeServiceError(
            "deleted container snapshot has no owner user",
            reason="invalid_payload",
        )
    with session_scope(commit=False) as session:
        owner_name = user_repo.get_name_by_id(owner_user_id, session=session)
    if not owner_name:
        raise NodeServiceError(
            "deleted container owner no longer exists",
            reason="data_not_recoverable",
        )

    existing_accounts = []
    for account in restored_accounts:
        user_id = account.get("user_id")
        role_value = account.get("role") or ROLE.COLLABORATOR.value
        try:
            role = ROLE(role_value) if not isinstance(role_value, ROLE) else role_value
        except Exception:
            role = ROLE.COLLABORATOR
        if user_id is None or role == ROLE.ROOT:
            continue
        with session_scope(commit=False) as session:
            system_username = user_repo.get_name_by_id(user_id, session=session)
        if not system_username:
            continue
        existing_accounts.append(
            {
                **account,
                "user_id": int(user_id),
                "system_username": system_username,
                "role": role.value,
                "container_username": account.get("container_username")
                or system_username,
            }
        )

    return root_account, existing_accounts


def _build_restore_container(target: _RestoreTarget) -> tuple[Container_info, bool]:
    """组包：按快照重建 Container_info；原名被占用时用改名结果（返回 renamed 供审计）。"""
    snapshot = target.snapshot
    restore_name, restore_renamed = _resolve_restore_container_name(
        str(snapshot.get("container_name") or ""),
        target.machine_id,
        target.container_id,
        target.removed_at,
    )
    container = Container_info(
        gpu_list=list(snapshot.get("gpu_chosen_list") or []),
        cpu_number=int(snapshot.get("cpu_number") or 0),
        memory=int(snapshot.get("memory_gb") or 0),
        shared_memory=int(snapshot.get("shared_gb") or 0),
        name=restore_name,
        image=str(snapshot.get("image") or ""),
        port=0,
    )
    if not container.NAME or not container.image:
        raise NodeServiceError(
            "deleted container snapshot lacks name or image",
            reason="invalid_payload",
        )

    return container, restore_renamed


def _get_restored_container_id(container_name: str, machine_id: int) -> int:
    """回查复活后的容器 id（Create_container 只返回 bool，id 需按名字+机器再查一次）。"""
    with session_scope(commit=False) as session:
        container_id = containers_repo.get_id_by_name_machine(
            container_name=container_name,
            machine_id=machine_id,
            session=session,
        )
    if not container_id:
        raise NodeServiceError(
            "resurrected container record not found",
            reason="unexpected_response",
        )

    return int(container_id)


def _restore_long_term_state(container_id: int, snapshot: dict, operator_user_id: int | None) -> None:
    """恢复长期态：快照里是长期容器才补长期标记（否则不动）。"""
    if snapshot.get("is_long_term"):
        with session_scope() as session:
            long_term_container_repo.add(
                container_id,
                created_by_user_id=operator_user_id,
                session=session,
            )


def _delete_restore_artifacts(deleted_id: int, mount_cleanup_id: int | None) -> None:
    """清退恢复产物：恢复成功后删除 deleted 快照与 mount 清理记录（容器已复活）。"""
    with session_scope() as session:
        delete_restore_artifacts(deleted_id, mount_cleanup_id, session=session)


def _audit_restore_success(
    deleted_id, target, container_id, container, restore_renamed, restored_accounts_count, operator_user_id,
) -> None:
    """成功审计：恢复记一条 CREATE_CONTAINER（trigger=resurrect），含改名与原始名字对照。"""
    log_success(
        operator_user_id=operator_user_id,
        operation=OperationType.CREATE_CONTAINER,
        target_type="container",
        target_id=container_id,
        detail={
            "trigger": "resurrect",
            "deleted_id": deleted_id,
            "original_container_id": target.snapshot.get("container_id"),
            "restore_original_name": str(target.snapshot.get("container_name") or ""),
            "restore_renamed": restore_renamed,
            **_container_log_detail(container.NAME),
            "machine_id": target.machine_id,
            "restore_mount_path": target.mount_path,
            "restored_accounts": restored_accounts_count,
        },
    )


def _audit_mount_preflight_failure(deleted_id, mount_cleanup_id, operator_user_id, exc) -> None:
    """失败审计：手动 mount 清理在"解析入参"阶段就失败的场景（还没走到 clean_mount_path）。"""
    detail = {
        "trigger": "manual_clean_mount",
        "deleted_id": deleted_id,
        "mount_cleanup_id": mount_cleanup_id,
    }
    try:
        with session_scope(commit=False) as session:
            deleted = (
                deleted_container_restore_snapshot_repo.get_by_id(
                    int(deleted_id),
                    session=session,
                )
                if deleted_id is not None
                else None
            )
            legacy_cleanup = (
                container_mount_cleanup_repo.get_by_id(
                    int(mount_cleanup_id),
                    session=session,
                )
                if mount_cleanup_id is not None
                else None
            )
            context = deleted if deleted is not None else legacy_cleanup
            if context is not None:
                detail.update(_container_log_detail(context.container_name))
                detail["machine_id"] = context.machine_id
    except Exception:
        pass
    log_failure(
        operation=OperationType.DELETE_CONTAINER,
        target_type="container_mount_cleanup",
        target_id=int(mount_cleanup_id or 0),
        operator_user_id=operator_user_id,
        detail=detail,
        error_reason=getattr(exc, "reason", None) or str(exc),
    )
