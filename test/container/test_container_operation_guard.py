import pytest

from ...constant import ContainerStatus, ContainerEffectiveStatus
from ...services.container_module.exceptions import NodeServiceError
from ...services.container_module.operation_guard import ensure_container_operation_allowed


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
    ],
)
def test_derived_effective_status_rejects_node_writes(status, reason):
    with pytest.raises(NodeServiceError) as excinfo:
        ensure_container_operation_allowed(status, "restart")

    assert excinfo.value.reason == reason


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
