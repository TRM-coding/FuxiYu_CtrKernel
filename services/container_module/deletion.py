from __future__ import annotations

import logging

from ...constant import OperationType
from ...extensions import session_scope
from ...repositories import containers_repo, machine_repo
from ..operation_log_tasks import log_failure, log_success
from .deleted_containers import record_deleted_container_artifacts
from .exceptions import NodeServiceError, _raise_on_node_error
from . import node_comms
from .node_comms import get_full_url
from .utils import _container_log_detail

logger = logging.getLogger(__name__)

####################################################
# 删除工具族
# 门户 remove_container 在 services/container_tasks.py；顺序 = 门户调用顺序：
#   读容器 → 请求 Node 删除 → 本地软删落库 → 审计
# 软删语义：只置 is_valid=false 并写 deleted_* 元数据，原行与原 id 保留（可被恢复复用）。
####################################################

def _load_removal_container(container_id: int):
    """读容器及其机器归属；不存在或未绑机器一律 ValueError（api 层按 404/422 处理）。"""
    with session_scope(commit=False) as session:
        machine_id = containers_repo.get_machine_id_by_container_id(container_id, session=session)
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    with session_scope(commit=False) as session:
        container = containers_repo.get_by_id(container_id, session=session)
    if not container:
        raise ValueError("Container not found")
    return container


def _request_node_removal(container) -> None:
    """请求 Node 删容器。not_found（HTTP 404）视同成功：docker 已无残留，本地照删。"""
    with session_scope(commit=False) as session:
        machine_ip = machine_repo.get_machine_ip_by_id(container.machine_id, session=session)
    response = node_comms.send(
        get_full_url(machine_ip, "/remove_container"),
        {"config": {"container_name": container.name}},
    )
    logger.debug("remove_container: NODE response: %s", response)
    if isinstance(response, dict) and (
        response.get("error_reason") == "not_found" or response.get("status_code") == 404
    ):
        logger.warning("remove_container: NODE reports container absent (not_found), proceeding with local cleanup")
        response = {"success": 1}
    _raise_on_node_error(response, "remove")
    if response.get("success") is None:
        raise NodeServiceError(
            f"NODE remove returned unexpected response: {response}", reason="unexpected_response",
        )
    if response.get("success") != 1:
        raise NodeServiceError(
            f"NODE remove reported failure: {response}",
            reason=response.get("error_reason") or "remove_failed",
        )


def _persist_container_deletion(container_id: int, trigger: str, operator_user_id: int | None) -> None:
    """本地软删：同一事务内先落删除快照（供恢复/mount 清理用），再标记容器行失效。"""
    with session_scope() as session:
        record_deleted_container_artifacts(container_id, removed_trigger=trigger, session=session)
        containers_repo.delete_container(
            container_id, deleted_trigger=trigger, deleted_by_user_id=operator_user_id, session=session,
        )


def _audit_removal(container_id, container, trigger, operator_user_id, *, error=None) -> None:
    """审计：error 为空记成功、非空记失败（失败分支由门户在 except 里调用后原样上抛）。"""
    container_name = getattr(container, "name", None)
    machine_id = getattr(container, "machine_id", None)
    detail = {"mount_path": getattr(container, "bind_mount_path", None), "trigger": trigger}
    if error is not None:
        log_failure(
            OperationType.DELETE_CONTAINER, int(container_id or 0), target_type="container",
            operator_user_id=operator_user_id, container_name=container_name, machine_id=machine_id,
            error_reason=getattr(error, "reason", None) or getattr(error, "error_reason", None) or str(error),
            detail=detail,
        )
    else:
        log_success(
            operator_user_id=operator_user_id, operation=OperationType.DELETE_CONTAINER,
            target_type="container", target_id=int(container_id),
            detail={**_container_log_detail(container_name), "machine_id": machine_id, **detail},
        )
