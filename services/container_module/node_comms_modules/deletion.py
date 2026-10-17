from __future__ import annotations

import logging

from ....constant import OperationType
from ....extensions import session_scope
from ....repositories import containers_repo
from ...operation_log_tasks import log_failure, log_success
from ..deleted_containers import record_deleted_container_artifacts
from ..utils import _container_log_detail

logger = logging.getLogger(__name__)

def _handle_container_deleted(container_name: str, machine_id: int | None = None) -> None:
    """Node 推 delete 帧：容器在 Node 侧消失 → 抹 Ctrl DB 记录（绑定 + 容器行）。

    关联表（usercontainer/container_ssh_login/freeze/long_term）均 ondelete=CASCADE，
    删容器行即级联清理。外部删除是异常路径，记录 warning。

    作用域（2026-09 修复）：删除必须限定在发送机器内——容器名只在单机内唯一，
    machine_id 由链路归属确定（apply_snapshot_batch / _consume_frames 传入）；
    machine_id 缺失或名字不属于该机器 → 拒绝，避免跨机器重名误删他人容器记录。
    """
    container_id = None
    try:
        with session_scope() as session:
            if machine_id is None:
                logger.warning("node link delete: machine_id missing for %r (refuse)", container_name)
                log_failure(
                    operator_user_id=None,
                    operation=OperationType.DELETE_CONTAINER,
                    target_type="container",
                    target_id=0,
                    detail={
                        "name": container_name,
                        "container_name": container_name,
                        "original_container_name": container_name,
                        "machine_id": None,
                        "trigger": "node_vanished",
                    },
                    error_reason="machine_id_missing",
                )
                return
            container_id = containers_repo.get_id_by_name_machine(container_name, machine_id, session=session)
            if container_id is None:
                logger.debug("node link delete: container %r already gone or not on machine %s (skip)",
                             container_name, machine_id)
                return
            record_deleted_container_artifacts(
                container_id,
                removed_trigger="node_vanished",
                cleanup_context={"trigger": "node_vanished"},
                session=session,
            )
            containers_repo.delete_container(
                container_id,
                deleted_trigger="node_vanished",
                deleted_reason="vanished on node",
                session=session,
            )
        logger.warning("node link delete: container %r (id=%s) removed from DB (vanished on node)",
                       container_name, container_id)
        # 审计：外部消失是删除的另一条路径（trigger=node_vanished），与 api/cleanup 一致入 op-log
        try:
            log_success(
                         operator_user_id=None,
                         operation=OperationType.DELETE_CONTAINER,
                         target_type="container",
                         target_id=container_id,
                         detail={
                             "name": container_name,
                             "container_name": container_name,
                             "original_container_name": container_name,
                             "machine_id": machine_id,
                             "trigger": "node_vanished",
                         })
        except Exception as le:
            logger.warning("node link delete: op-log failed for %r: %s", container_name, le)
    except Exception as e:
        logger.warning("node link delete: failed to remove container %r: %s", container_name, e)
        log_failure(
            operator_user_id=None,
            operation=OperationType.DELETE_CONTAINER,
            target_type="container",
            target_id=int(container_id or 0),
            detail={
                "name": container_name,
                "container_name": container_name,
                "original_container_name": container_name,
                "machine_id": machine_id,
                "trigger": "node_vanished",
            },
            error_reason=str(e),
        )

