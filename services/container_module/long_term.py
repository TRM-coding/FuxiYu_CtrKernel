from __future__ import annotations

from ...constant import ContainerStatus, OperationType
from ...extensions import session_scope
from ...repositories import (
    containers_repo,
    long_term_container_repo,
    machine_repo,
    usercontainer_repo,
)
from ...repositories.containers_repo import _root_user_ids_from_bindings
from .. import settings_tasks
from ..operation_log_tasks import log_success
from .exceptions import NodeServiceError
from .operation_guard import ensure_container_operation_allowed
from .pydantic_models import _derive_effective_status
from .utils import _container_log_detail

####################################################
# 长期容器工具族
# 门户 set_long_term_container 在 services/container_tasks.py。
# 顺序 = 门户调用顺序：同一会话读事实 → 状态矩阵 → 方向静态守卫 → 落库 → 审计。
# 长期容器不受 SSH 判龄清理，配额按容器的 root 用户计数。
####################################################

def _read_long_term_target(session, container_id: int):
    """同一事务读取容器、绑定、长期标记与机器；写入前的唯一事实来源。"""
    try:
        container_id = int(container_id)
    except Exception:
        raise NodeServiceError("invalid container_id", reason="invalid_payload")
    container = containers_repo.get_by_id(container_id, session=session)
    if not container:
        raise NodeServiceError("Container not found", reason="container_not_found")
    bindings = usercontainer_repo.get_container_bindings(container_id, session=session) or []
    existing = long_term_container_repo.is_long_term(container_id, session=session)
    machine = machine_repo.get_by_id(container.machine_id, session=session)
    return container, bindings, existing, machine


def ensure_long_term_switch_allowed(
    container,
    bindings,
    existing: bool,
    target: bool,
    machine,
    *,
    session,
) -> None:
    """手工启用/取消长期的静态服务端守卫。

    先走既有状态矩阵，再按方向叠加规则：
    - 启用：root 用户配额 + 已知磁盘硬超限；
    - 取消：实际状态 paused（冻结中）拒绝。
    同目标值在矩阵之后直接返回，不写配额/磁盘/冻结字段。磁盘判断只读当前
    `disk_total_bytes` 与机器上限，不增加测量新鲜度、路径或冻结行门禁。
    """
    effective_status = _derive_effective_status(
        container.container_status, container.machine_id, container=container,
    )
    ensure_container_operation_allowed(effective_status, "set_long_term")

    target = bool(target)
    if bool(existing) == target:
        return

    if target:
        _ensure_long_term_capacity(bindings, session=session)
        _ensure_long_term_disk_hard_limit(container, machine)
        return

    status_value = effective_status.value if hasattr(effective_status, "value") else str(effective_status)
    if str(status_value).lower() == ContainerStatus.PAUSED.value:
        raise NodeServiceError(
            "Container is paused (frozen); long-term cannot be cancelled until it is actually resumed",
            reason="container_paused",
        )


def _ensure_long_term_disk_hard_limit(container, machine) -> None:
    """已知用量达到硬限制时拒绝启用；未知用量/未配置上限/软阈值都不阻断。"""
    total_bytes = getattr(container, "disk_total_bytes", None)
    max_disk_size_gb = getattr(machine, "max_disk_size_gb", None) if machine is not None else None
    hard_percent = settings_tasks.get_container_disk_hard_limit_percent()
    if total_bytes is None or not max_disk_size_gb or max_disk_size_gb <= 0:
        return
    if hard_percent is None or hard_percent <= 0:
        return
    limit_bytes = int(max_disk_size_gb * 1024**3)
    if limit_bytes <= 0:
        return
    if int(total_bytes) * 100 >= limit_bytes * int(hard_percent):
        raise NodeServiceError(
            f"Container disk usage {int(total_bytes)} bytes reached hard limit "
            f"{int(hard_percent)}% of {limit_bytes} bytes",
            reason="disk_usage_over_limit",
        )


def _ensure_long_term_capacity_for_users(user_ids, *, session=None) -> None:
    """配额校验：逐个 root 用户比对全局上限，超限抛 long_term_limit_reached（api 层回 409）。

    失败原因带上实际用量与上限（`used/limit`）——门户 set_long_term 与恢复入口共用这一份，
    用户看得见"已经用了几个、上限几个"，而不是只能说"超限了"。
    `session` 由门户传入时计数与写入共享同一事务；恢复预检不传，沿用只读会话。
    """
    limit = settings_tasks.get_long_term_container_limit()
    for user_id in user_ids:
        if session is not None:
            count = long_term_container_repo.count_by_user(int(user_id), session=session)
        else:
            with session_scope(commit=False) as own_session:
                count = long_term_container_repo.count_by_user(int(user_id), session=own_session)
        if count >= limit:
            raise NodeServiceError(
                f"User {user_id} has reached long-term container limit ({count}/{limit})",
                reason="long_term_limit_reached",
            )


def _ensure_long_term_capacity(bindings, *, session=None) -> None:
    """配额校验（bindings 形态）：取容器的各 root 用户后委托 _ensure_long_term_capacity_for_users。"""
    _ensure_long_term_capacity_for_users(_root_user_ids_from_bindings(bindings), session=session)


def _persist_long_term_state(container_id, is_long_term, existing, operator_user_id, *, session=None) -> None:
    """落库：设为长期（已长期则跳过）/ 取消长期（幂等删除）。"""

    def _apply(active_session) -> None:
        if is_long_term:
            if not existing:
                long_term_container_repo.add(
                    container_id, created_by_user_id=operator_user_id, session=active_session,
                )
        else:
            long_term_container_repo.remove(container_id, session=active_session)

    if session is not None:
        _apply(session)
        return
    with session_scope() as own_session:
        _apply(own_session)


def _audit_long_term(container_id, is_long_term, operator_user_id) -> None:
    """审计：只在实际新增/删除标记后记成功；失败由门户异常路径上抛，api 层记失败。"""
    with session_scope(commit=False) as session:
        container_name = getattr(containers_repo.get_by_id(container_id, session=session), "name", None)
    log_success(
        operator_user_id=operator_user_id, operation=OperationType.SET_LONG_TERM,
        target_type="container", target_id=container_id,
        detail=_container_log_detail(container_name, is_long_term=is_long_term),
    )
