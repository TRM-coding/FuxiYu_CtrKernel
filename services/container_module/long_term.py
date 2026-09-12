from __future__ import annotations

from ...constant import OperationType
from ...extensions import session_scope
from ...repositories import containers_repo, long_term_container_repo, usercontainer_repo
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
# 顺序 = 门户调用顺序：读目标 → 配额校验（仅"设为长期"时） → 落库 → 审计。
# 长期容器不受 SSH 判龄清理，配额按容器的 root 用户计数。
####################################################

def _load_long_term_target(container_id: int):
    """读容器 + 绑定 + 当前是否长期；顺带做状态机守卫（运行/暂停态才允许切换）。"""
    try:
        container_id = int(container_id)
    except Exception:
        raise NodeServiceError("invalid container_id", reason="invalid_payload")
    with session_scope(commit=False) as session:
        container = containers_repo.get_by_id(container_id, session=session)
    if not container:
        raise NodeServiceError("Container not found", reason="container_not_found")
    ensure_container_operation_allowed(
        _derive_effective_status(container.container_status, container.machine_id, container=container),
        "set_long_term",
    )
    with session_scope(commit=False) as session:
        bindings = usercontainer_repo.get_container_bindings(container_id, session=session) or []
    with session_scope(commit=False) as session:
        existing = long_term_container_repo.is_long_term(container_id, session=session)
    return container, bindings, existing


def _ensure_long_term_capacity(bindings) -> None:
    """配额校验：逐个 root 用户比对全局上限，超限抛 long_term_limit_reached（api 层回 409）。"""
    limit = settings_tasks.get_long_term_container_limit()
    for user_id in _root_user_ids_from_bindings(bindings):
        with session_scope(commit=False) as session:
            count = long_term_container_repo.count_by_user(user_id, session=session)
        if count >= limit:
            raise NodeServiceError(
                f"User {user_id} has reached long-term container limit",
                reason="long_term_limit_reached",
            )


def _persist_long_term_state(container_id, is_long_term, existing, operator_user_id) -> None:
    """落库：设为长期（已长期则跳过）/ 取消长期（幂等删除）。"""
    if is_long_term:
        if not existing:
            with session_scope() as session:
                long_term_container_repo.add(container_id, created_by_user_id=operator_user_id, session=session)
    else:
        with session_scope() as session:
            long_term_container_repo.remove(container_id, session=session)


def _audit_long_term(container_id, is_long_term, operator_user_id) -> None:
    """审计：只记成功（失败由门户的异常路径自然上抛，api 层不额外留痕）。"""
    with session_scope(commit=False) as session:
        container_name = getattr(containers_repo.get_by_id(container_id, session=session), "name", None)
    log_success(
        operator_user_id=operator_user_id, operation=OperationType.SET_LONG_TERM,
        target_type="container", target_id=container_id,
        detail=_container_log_detail(container_name, is_long_term=is_long_term),
    )
