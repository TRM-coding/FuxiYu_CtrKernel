from __future__ import annotations

import logging

from ...extensions import session_scope
from ...repositories import containers_repo, machine_repo
from ..operation_log_tasks import log_success
from .exceptions import NodeServiceError, _raise_on_node_error
from . import node_comms
from .node_comms import _ensure_machine_online_for_operation, get_full_url
from .operation_guard import ensure_container_operation_allowed
from .pydantic_models import _derive_effective_status
from .utils import _container_log_detail

logger = logging.getLogger(__name__)

####################################################
# 启停工具族（start / stop / restart，三族共用同一套步骤）
# 门户 start_container / stop_container / restart_container 在 services/container_tasks.py。
# 顺序 = 门户调用顺序：读容器 → 守卫 → 请求 Node → 审计（状态推进交给 WSS 快照，不直写库）。
# 协作者族与冻结族也复用本文件的 _load_container_target / _ensure_container_action。
####################################################

def _load_container_target(container_id: int):
    """读容器与所在机器 IP；不存在或未绑机器一律 ValueError（api 层按 404/422 处理）。"""
    with session_scope(commit=False) as session:
        machine_id = containers_repo.get_machine_id_by_container_id(container_id, session=session)
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    with session_scope(commit=False) as session:
        machine_ip = machine_repo.get_machine_ip_by_id(machine_id, session=session)
        container = containers_repo.get_by_id(container_id, session=session)
    if not container:
        raise ValueError("Container not found")
    return container, machine_ip


def _ensure_container_action(container, action: str, *, require_online: bool = False) -> None:
    """守卫：有效状态机校验 + 机器在线校验。require_online 供协作者族强制要求在线。"""
    ensure_container_operation_allowed(
        _derive_effective_status(container.container_status, container.machine_id, container=container),
        action, require_online=require_online,
    )
    _ensure_machine_online_for_operation(container.machine_id, action)


def _request_lifecycle_action(machine_ip: str, container_name: str, action: str) -> None:
    """网络出口：POST /{action}_container；Node 报错或非 success 一律上抛。"""
    response = node_comms.send(
        get_full_url(machine_ip, f"/{action}_container"),
        {"config": {"container_name": container_name}},
    )
    logger.debug("%s_container: NODE response: %s", action, response)
    _raise_on_node_error(response, action)
    if response.get("success") not in (1, True):
        raise NodeServiceError(
            f"NODE {action} returned failure: {response}",
            reason=response.get("error_reason") or f"{action}_failed",
        )


def _audit_container_action(container, operation, operator_user_id, extra_detail=None) -> None:
    """成功审计：容器族通用（冻结族借它记账，extra_detail 带磁盘策略明细）。"""
    log_success(
        operator_user_id=operator_user_id, operation=operation,
        target_type="container", target_id=container.id,
        detail=_container_log_detail(container.name, machine_id=container.machine_id, **(extra_detail or {})),
    )
