import pytest

from ...constant import ContainerStatus, ContainerEffectiveStatus
from ...services.container_module.exceptions import NodeServiceError
from ...services.container_module.operation_guard import (
    ALL_CONTAINER_WRITE_OPS,
    ensure_container_operation_allowed,
)


@pytest.mark.parametrize(
    "status",
    [
        ContainerStatus.BUILDING,
        ContainerStatus.CREATING,
        ContainerStatus.STARTING,
        ContainerStatus.STOPPING,
        ContainerStatus.RESTARTING,
    ],
)
@pytest.mark.parametrize(
    "operation",
    [
        "start",
        "stop",
        "restart",
        "remove",
        "set_long_term",
        "add_collaborator",
        "remove_collaborator",
        "update_role",
    ],
)
def test_unstable_effective_status_rejects_high_risk_operations(status, operation):
    with pytest.raises(NodeServiceError) as excinfo:
        ensure_container_operation_allowed(status, operation)

    assert excinfo.value.reason == "container_busy"


@pytest.mark.parametrize("operation", ["restart", "remove"])
def test_failed_container_allows_restart_and_remove(operation):
    assert ensure_container_operation_allowed(ContainerStatus.FAILED, operation) is None


@pytest.mark.parametrize("operation", ["start", "stop", "set_long_term", "add_collaborator"])
def test_failed_container_rejects_other_high_risk_operations(operation):
    with pytest.raises(NodeServiceError) as excinfo:
        ensure_container_operation_allowed(ContainerStatus.FAILED, operation)

    assert excinfo.value.reason == "container_failed"


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (ContainerEffectiveStatus.HOST_OFFLINE, "container_host_offline"),
        (ContainerEffectiveStatus.HOST_MAINTENANCE, "container_host_maintenance"),
        (ContainerEffectiveStatus.STATUS_UNKNOWN, "container_status_unknown"),
        (ContainerEffectiveStatus.NODE_VANISHED, "container_node_vanished"),
    ],
)
def test_derived_effective_status_rejects_node_writes(status, reason):
    with pytest.raises(NodeServiceError) as excinfo:
        ensure_container_operation_allowed(status, "restart")

    assert excinfo.value.reason == reason


@pytest.mark.parametrize("operation", sorted(ALL_CONTAINER_WRITE_OPS - {"remove"}))
def test_node_vanished_rejects_every_write_operation_except_delete(operation):
    """删除是 node_vanished 的唯一写操作出口；其余写操作仍全部拒绝。"""
    with pytest.raises(NodeServiceError) as excinfo:
        ensure_container_operation_allowed(ContainerEffectiveStatus.NODE_VANISHED, operation)

    assert excinfo.value.reason == "container_node_vanished"


def test_node_vanished_allows_existing_delete():
    assert ensure_container_operation_allowed(
        ContainerEffectiveStatus.NODE_VANISHED, "remove",
    ) is None


def test_status_unknown_still_rejects_delete():
    with pytest.raises(NodeServiceError) as excinfo:
        ensure_container_operation_allowed(ContainerEffectiveStatus.STATUS_UNKNOWN, "remove")

    assert excinfo.value.reason == "container_status_unknown"


def test_require_online_preserves_derived_effective_status_reason():
    with pytest.raises(NodeServiceError) as excinfo:
        ensure_container_operation_allowed(
            ContainerEffectiveStatus.HOST_OFFLINE,
            "add_collaborator",
            require_online=True,
        )

    assert excinfo.value.reason == "container_host_offline"


def test_require_online_preserves_container_offline_reason():
    with pytest.raises(NodeServiceError) as excinfo:
        ensure_container_operation_allowed(ContainerStatus.OFFLINE, "add_collaborator", require_online=True)

    assert excinfo.value.reason == "container_offline"
