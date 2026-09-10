"""已删容器 mount 目录的清理执行逻辑（统一入口）。

三条路径共用同一份动作逻辑——手动（管理页触发）、调度扫描（mount_cleanup_task）、
磁盘升级即时清理（disk_check_task escalation）：
- 幂等：已清理（cleaned_at 非空）直接返回 already_cleaned，不重复请求
- Node 请求经 node_comms 门户（get_full_url/send），错误经 _raise_on_node_error 逐级上报
- 成功 mark_cleaned + 写 op-log（trigger 由调用方表达：manual_clean_mount /
  auto_mount_cleanup / disk_escalation），operator_user_id 为 None 即系统动作
"""

from ...constant import OperationType
from ...extensions import session_scope
from ...repositories import (
    container_mount_cleanup_repo,
    containers_repo,
    deleted_container_restore_snapshot_repo,
    machine_repo,
)
from ..operation_log_tasks import log_failure, log_success
from .exceptions import NodeServiceError, _raise_on_node_error
from .node_comms import get_full_url, send
from .utils import _container_log_detail


def clean_mount_path(
    mount_cleanup_id: int,
    *,
    operator_user_id: int | None = None,
    trigger: str = "auto_mount_cleanup",
    escalation: bool | None = None,
) -> dict:
    try:
        return _clean_mount_path_impl(
            mount_cleanup_id,
            operator_user_id=operator_user_id,
            trigger=trigger,
            escalation=escalation,
        )
    except Exception as exc:
        container_name = None
        machine_id = None
        deleted_id = None
        mount_path = None
        try:
            with session_scope(commit=False) as session:
                cleanup = container_mount_cleanup_repo.get_by_id(
                    int(mount_cleanup_id),
                    session=session,
                )
                if cleanup is not None:
                    deleted_id = getattr(cleanup, "deleted_id", None)
                    mount_path = getattr(cleanup, "mount_path", None)
                    machine_id = getattr(cleanup, "machine_id", None)
                    container = containers_repo.get_by_id(
                        cleanup.container_id,
                        session=session,
                        include_invalid=True,
                    )
                    if container is not None:
                        container_name = container.name
                        machine_id = getattr(container, "machine_id", None) or machine_id
                        mount_path = getattr(container, "bind_mount_path", None) or mount_path
        except Exception:
            pass
        log_failure(
            operator_user_id=operator_user_id,
            operation=OperationType.DELETE_CONTAINER,
            target_type="container_mount_cleanup",
            target_id=int(mount_cleanup_id or 0),
            detail={
                **_container_log_detail(container_name),
                "mount_path": mount_path,
                "trigger": trigger,
                "deleted_id": deleted_id,
                "machine_id": machine_id,
            },
            error_reason=getattr(exc, "reason", None)
            or getattr(exc, "error_reason", None)
            or str(exc),
        )
        raise


def _clean_mount_path_impl(
    mount_cleanup_id: int,
    *,
    operator_user_id: int | None = None,
    trigger: str = "auto_mount_cleanup",
    escalation: bool | None = None,
) -> dict:
    """执行一次 mount 目录清理：Node clean_mount → mark_cleaned → op-log。

    抛错语义（NodeServiceError，逐级上报）：
    - 记录不存在 → reason="not_found"（调用方按角色处理；调度循环需自行容错）
    - Node 拒绝/网络错误 → _raise_on_node_error / reason="clean_mount_failed"
    escalation：仅 disk 升级即时清理传 True（保持记录 escalation 标记）；
    默认 None 不改记录列。
    返回 {"cleaned": bool, "already_cleaned": bool, "mount_cleanup_id": int}。
    """
    with session_scope(commit=False) as session:
        cleanup = container_mount_cleanup_repo.get_by_id(int(mount_cleanup_id), session=session)
        if cleanup is None:
            raise NodeServiceError("mount cleanup record not found", reason="not_found")
        deleted_id = getattr(cleanup, "deleted_id", None)
        deleted = (
            deleted_container_restore_snapshot_repo.get_by_id(deleted_id, session=session)
            if deleted_id is not None
            else deleted_container_restore_snapshot_repo.get_by_mount_cleanup_id(
                cleanup.id,
                session=session,
            )
        )
        if deleted is not None and bool(getattr(deleted, "mount_cleaned", False)):
            return {
                "mount_cleanup_id": cleanup.id,
                "deleted_id": deleted.id,
                "cleaned": False,
                "already_cleaned": True,
            }
        if cleanup.cleaned_at is not None:
            if deleted is not None:
                # This read scope intentionally does not commit. Persist the
                # legacy-state convergence in its own transaction.
                with session_scope() as write_session:
                    deleted_container_restore_snapshot_repo.mark_mount_cleaned(
                        deleted.id,
                        session=write_session,
                    )
            return {
                "mount_cleanup_id": cleanup.id,
                "deleted_id": deleted.id if deleted is not None else None,
                "cleaned": False,
                "already_cleaned": True,
            }
        container = containers_repo.get_by_id(
            cleanup.container_id,
            session=session,
            include_invalid=True,
        )
        machine_id = getattr(container, "machine_id", None) or cleanup.machine_id
        machine_ip = machine_repo.get_machine_ip_by_id(machine_id, session=session)
        mount_path = (
            getattr(container, "bind_mount_path", None)
            or cleanup.mount_path
        )
        container_name = getattr(container, "name", None) or cleanup.container_name

    full_url = get_full_url(machine_ip, "/clean_mount")
    res = send(full_url, {"config": {"mount_path": mount_path}}, timeout=10.0)
    _raise_on_node_error(res, "clean_mount")
    if res.get("success") != 1:
        raise NodeServiceError(f"NODE clean_mount unexpected response: {res}", reason="clean_mount_failed")

    with session_scope() as session:
        ok = container_mount_cleanup_repo.mark_cleaned(
            int(mount_cleanup_id), session=session, escalation=escalation
        )
        if not ok:
            raise NodeServiceError("mount cleanup record not found", reason="not_found")
        cleanup = container_mount_cleanup_repo.get_by_id(int(mount_cleanup_id), session=session)
        deleted_id = getattr(cleanup, "deleted_id", None) if cleanup is not None else None
        deleted = (
            deleted_container_restore_snapshot_repo.get_by_id(deleted_id, session=session)
            if deleted_id is not None
            else deleted_container_restore_snapshot_repo.get_by_mount_cleanup_id(
                int(mount_cleanup_id),
                session=session,
            )
        )
        if deleted is not None:
            deleted_container_restore_snapshot_repo.mark_mount_cleaned(
                deleted.id,
                session=session,
            )

    log_success(
        operator_user_id=operator_user_id,
        operation=OperationType.DELETE_CONTAINER,
        target_type="container_mount_cleanup",
        target_id=int(mount_cleanup_id),
        detail={
            **_container_log_detail(container_name),
            "mount_path": mount_path,
            "trigger": trigger,
            "deleted_id": deleted.id if deleted is not None else None,
        },
    )
    return {
        "mount_cleanup_id": int(mount_cleanup_id),
        "deleted_id": deleted.id if deleted is not None else None,
        "cleaned": True,
        "already_cleaned": False,
    }
