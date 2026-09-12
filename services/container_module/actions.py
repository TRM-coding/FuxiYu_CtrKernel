from __future__ import annotations

import logging

from ...constant import ContainerStatus
from ...extensions import session_scope
from ...repositories import containers_repo, machine_repo, container_disk_freeze_state_repo
from .. import settings_tasks
from ..operation_log_tasks import log_failure
from .exceptions import _raise_on_node_error
from .lifecycle import _ensure_container_action
from . import node_comms
from .node_comms import get_full_url

logger = logging.getLogger(__name__)

####################################################
# 冻结 / 解冻工具族（磁盘超限动作）
# 门户 pause_container / unpause_container 在 services/container_tasks.py。
# 顺序 = 门户调用顺序：读容器 → 守卫 → 请求 Node → 落库 → 审计；
# 与启停族的差别：这两个动作的每一步失败都要单独留一条失败审计（调用方多为调度器，无人看返回值）。
####################################################

def _audit_pause_failure(container_id, container, operation, operator_user_id, reason, extra_detail=None) -> None:
    """失败审计助手：统一把 reason / 容器身份 / 磁盘策略明细写成一条失败 op-log。"""
    log_failure(
        operation, container_id, target_type="container", operator_user_id=operator_user_id,
        container_name=getattr(container, "name", None), machine_id=getattr(container, "machine_id", None),
        error_reason=reason, detail=extra_detail,
    )


def _load_pause_container(container_id, operation, operator_user_id, extra_detail=None):
    """读容器；id 非法或容器不存在时先记失败审计再返回 None（门户据此直接 return False）。"""
    try:
        container_id = int(container_id)
    except Exception:
        _audit_pause_failure(0, None, operation, operator_user_id, "invalid_payload", extra_detail)
        return None
    with session_scope(commit=False) as session:
        container = containers_repo.get_by_id(container_id, session=session)
    if not container:
        _audit_pause_failure(container_id, None, operation, operator_user_id, "container_not_found", extra_detail)
    return container


def _ensure_pause_allowed(container, action, operation, operator_user_id, extra_detail=None) -> None:
    """守卫：状态机与机器在线校验（复用启停族的 _ensure_container_action），失败留审计后上抛。"""
    try:
        _ensure_container_action(container, action)
    except Exception as exc:
        _audit_pause_failure(
            container.id, container, operation, operator_user_id,
            getattr(exc, "reason", None) or getattr(exc, "error_reason", None) or str(exc), extra_detail,
        )
        raise


def _request_pause_action(container, action, operation, operator_user_id, extra_detail=None) -> bool:
    """网络出口：POST /pause_container（action 区分 pause/unpause）。

    返回 False 只在"已留过失败审计"的分支——调用方无需再记账；异常分支仍上抛。
    """
    with session_scope(commit=False) as session:
        machine_ip = machine_repo.get_machine_ip_by_id(container.machine_id, session=session)
    url = get_full_url(machine_ip, "/pause_container")
    payload = {"config": {"container_name": container.name, "action": action}}
    try:
        response = node_comms.send(url, payload, timeout=10.0)
    except Exception as exc:
        logger.error("%s_container send error: %s", action, exc)
        _audit_pause_failure(
            container.id, container, operation, operator_user_id,
            getattr(exc, "reason", None) or str(exc), extra_detail,
        )
        return False
    try:
        _raise_on_node_error(response, action)
    except Exception as exc:
        _audit_pause_failure(
            container.id, container, operation, operator_user_id,
            getattr(exc, "reason", None) or str(exc), extra_detail,
        )
        raise
    if response.get("success") == 1:
        return True
    _audit_pause_failure(
        container.id, container, operation, operator_user_id,
        response.get("error_reason") or f"{action}_failed", extra_detail,
    )
    return False


def _persist_paused_status(container_id: int) -> None:
    """落库：仅 pause 走即时回执（unpause 不直写 ONLINE，状态推进交给 WSS 快照）。"""
    try:
        with session_scope() as session:
            containers_repo.update_container(container_id, container_status=ContainerStatus.PAUSED, session=session)
    except Exception as exc:
        logger.warning("pause: failed to update container %s status to PAUSED: %s", container_id, exc)


def _grant_unpause_grace(container) -> None:
    """解冻后重开磁盘宽限：只改 grace_until，不重置 first_frozen_at（升级倒计时不重来）。

    尽力而为：失败只告警，不影响解冻本身的成功返回。
    """
    try:
        with session_scope() as session:
            freeze_state = container_disk_freeze_state_repo.get(container.id, session=session)
            if freeze_state is None:
                return
            grace_days = settings_tasks.get_container_disk_freeze_grace_days()
            container_disk_freeze_state_repo.set_grace(container.id, grace_days, session=session)
            # 在 session 存活期内取值：不依赖 expire_on_commit 的配置
            grace_until = freeze_state.grace_until
        logger.info(
            "[disk-check] grace period set for container %s (%s) (%s days, until %s)",
            container.id, container.name, grace_days, grace_until,
        )
    except Exception as exc:
        logger.warning("[disk-check] failed to set grace for container %s: %s", container.id, exc)
