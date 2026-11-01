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
from . import node_comms
from .mount_usage import (
    MOUNT_INVALID_PATH,
    MOUNT_MISSING,
    MOUNT_PERMISSION_DENIED,
    MOUNT_PRESENT,
    probe_mount_path,
)
from .node_comms import get_full_url
from .node_comms_modules.endpoint import resolve_endpoint
from .utils import _container_log_detail

####################################################
# mount 清理工具族
# 结构：clean_mount_path 是对外门户（含失败留痕包装），_clean_mount_path_impl 是真正的动作序列。
# 门户被三类调用方共用：手动（manual_clean_mount）、定时（auto_mount_cleanup）、
# 磁盘升级即时清理（disk_escalation）；trigger 由调用方传入，operator_user_id 为 None 即系统动作。
####################################################

def _ensure_manual_clean_mount_path(machine_id, mount_path) -> None:
    """手动清理前的即时路径复核：不存在/不可读就拒绝，绝不带着旧采样去 rm。

    与恢复不同，``/clean_mount`` 对不存在路径返回成功（``rm -rf`` 幂等），
    因此这里不能把“未能校验”退化给动作端点——那会把缺失目录误标成已清理。
    只有 Node 明确给出 present（成功/pending/du 稳定错误均证明门禁 os.stat 已过）
    才继续；per-path not_found 明确拒绝；权限/非法路径/旧 Node/超时/离线/坏响应
    各自保留原因并拒绝。
    """

    probe = probe_mount_path(machine_id, mount_path)
    state = probe["state"]

    if state == MOUNT_PRESENT:
        return
    if state == MOUNT_MISSING:
        raise NodeServiceError(
            "mount path no longer exists; nothing was cleaned",
            reason="not_found",
        )
    if state == MOUNT_PERMISSION_DENIED:
        raise NodeServiceError(
            "mount path is not readable on the node; nothing was cleaned",
            reason=MOUNT_PERMISSION_DENIED,
        )
    if state == MOUNT_INVALID_PATH:
        raise NodeServiceError(
            "mount path is not a usable directory; nothing was cleaned",
            reason=MOUNT_INVALID_PATH,
        )
    raise NodeServiceError(
        f"cannot verify mount path ({state}); nothing was cleaned",
        reason=state,
    )

def clean_mount_path(
    mount_cleanup_id: int,
    *,
    operator_user_id: int | None = None,
    trigger: str = "auto_mount_cleanup",
    escalation: bool | None = None,
    verify_mount_path: bool = False,
) -> dict:
    """门户：执行清理并保证"抛错必留档"——失败时尽力回捞容器身份写一条失败 op-log，再原样上抛。

    ``verify_mount_path`` 只由手动入口开启：它在 ``/clean_mount`` 之前同步问 Node
    “这条保留路径现在是否仍是现存目录”，目录不存在时不会调用删除、更不会标记已清理。
    自动/升级清理维持既有语义（由服务端记录驱动，不消费浏览器采样）。
    """
    try:
        return _clean_mount_path_impl(
            mount_cleanup_id,
            operator_user_id=operator_user_id,
            trigger=trigger,
            escalation=escalation,
            verify_mount_path=verify_mount_path,
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
    verify_mount_path: bool = False,
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
        machine_ip, machine_port = machine_repo.get_machine_endpoint_by_id(machine_id, session=session)
        mount_path = (
            getattr(container, "bind_mount_path", None)
            or cleanup.mount_path
        )
        container_name = getattr(container, "name", None) or cleanup.container_name
        # 读写分离：会话内取值，避免关闭后依赖 ORM 对象的过期状态。
        container_is_valid = bool(getattr(container, "is_valid", False))

    if verify_mount_path and container_is_valid:
        # 恢复成功后原行重新变为有效，但历史 deleted/cleanup 记录可能因异常残留。
        # 此时 mount_path 是活容器的挂载目录，手动清理绝不能 rm 它；先拒绝，交由
        # 恢复/清理状态核对处理。不标记 cleaned_at/mount_cleaned。
        raise NodeServiceError(
            "container is valid again; live mount path must not be cleaned",
            reason="container_exists",
        )

    if verify_mount_path:
        # 读会话已结束：不会因校验而 commit 任何清理/快照状态。校验路径必须与下面
        # 真正下发给 /clean_mount 的 machine_id + mount_path 完全同源。
        _ensure_manual_clean_mount_path(machine_id, mount_path)

    host, port = resolve_endpoint(machine_ip, machine_port)
    full_url = get_full_url(host, "/clean_mount", port)
    res = node_comms.send(full_url, {"config": {"mount_path": mount_path}}, timeout=10.0)
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
