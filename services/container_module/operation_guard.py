from ...constant import ContainerStatus, ContainerEffectiveStatus
from .exceptions import NodeServiceError


UNSTABLE_CONTAINER_STATUSES = {
    ContainerStatus.BUILDING.value,
    ContainerStatus.CREATING.value,
    ContainerStatus.STARTING.value,
    ContainerStatus.STOPPING.value,
    ContainerStatus.RESTARTING.value,
}

ALL_CONTAINER_WRITE_OPS = {
    "start",
    "stop",
    "restart",
    "remove",
    "pause",
    "unpause",
    "set_long_term",
    "add_collaborator",
    "remove_collaborator",
    "update_role",
    "reset_container_password",
}

# node_vanished 只放行既有删除：删除是处理“容器已从 Node 消失”的出口，
# 其余写操作仍与 status_unknown 保持同一保守范围。
NODE_VANISHED_DENY_OPS = ALL_CONTAINER_WRITE_OPS - {"remove"}

CONTAINER_OPERATION_DENY_MATRIX = {
    "building": ALL_CONTAINER_WRITE_OPS,
    "creating": ALL_CONTAINER_WRITE_OPS,
    "starting": ALL_CONTAINER_WRITE_OPS,
    "stopping": ALL_CONTAINER_WRITE_OPS,
    "restarting": ALL_CONTAINER_WRITE_OPS,
    "online": {"start", "unpause"},
    "offline": {"stop", "restart", "pause", "unpause", "add_collaborator", "remove_collaborator", "update_role"},
    "paused": {"start", "stop", "restart", "pause", "add_collaborator", "remove_collaborator", "update_role"},
    "failed": {"start", "stop", "pause", "unpause", "set_long_term", "add_collaborator", "remove_collaborator", "update_role"},
    ContainerEffectiveStatus.HOST_OFFLINE.value: ALL_CONTAINER_WRITE_OPS,
    ContainerEffectiveStatus.HOST_MAINTENANCE.value: ALL_CONTAINER_WRITE_OPS,
    ContainerEffectiveStatus.STATUS_UNKNOWN.value: ALL_CONTAINER_WRITE_OPS,
    ContainerEffectiveStatus.NODE_VANISHED.value: NODE_VANISHED_DENY_OPS,
}

def _status_value(status) -> str:
    if hasattr(status, "value"):
        return str(status.value).lower()
    return str(status or "").lower()


def ensure_container_operation_allowed(
    effective_status,
    operation: str,
    *,
    require_online: bool = False,
) -> None:
    status = _status_value(effective_status)
    op = str(operation or "").lower()

    denied_operations = CONTAINER_OPERATION_DENY_MATRIX.get(status, set())
    if op in denied_operations:
        reason = "container_busy" if status in UNSTABLE_CONTAINER_STATUSES else f"container_{status}"
        raise NodeServiceError(
            f"Container operation {op} is not allowed while effective_status is {status}",
            reason=reason,
        )

    if require_online and status != ContainerStatus.ONLINE.value:
        raise NodeServiceError(
            f"Container is not online: status={status}",
            reason="container_offline",
        )
