from ...services.container_tasks import _derive_effective_status
from ...services.container_module import pydantic_models
from ...constant import ContainerStatus, ContainerEffectiveStatus


def test_host_offline_overrides_running_states(monkeypatch):
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: False)
    assert _derive_effective_status(ContainerStatus.ONLINE, 3) == ContainerEffectiveStatus.HOST_OFFLINE.value
    assert _derive_effective_status(ContainerStatus.OFFLINE, 3) == ContainerEffectiveStatus.HOST_OFFLINE.value
    assert _derive_effective_status(ContainerStatus.CREATING, 3) == ContainerEffectiveStatus.HOST_OFFLINE.value


def test_failed_not_masked_by_host_offline(monkeypatch):
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: False)
    assert _derive_effective_status(ContainerStatus.FAILED, 3) == ContainerStatus.FAILED.value


def test_host_maintenance_overrides_running_state(monkeypatch):
    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda mid: True)
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: True)
    assert _derive_effective_status(ContainerStatus.ONLINE, 3) == ContainerEffectiveStatus.HOST_MAINTENANCE.value


def test_failed_not_masked_by_host_maintenance(monkeypatch):
    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda mid: True)
    assert _derive_effective_status(ContainerStatus.FAILED, 3) == ContainerStatus.FAILED.value


def test_normal_when_reachable(monkeypatch):
    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda mid: False)
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: True)
    monkeypatch.setattr(pydantic_models, "is_machine_collect_error", lambda mid: False)
    assert _derive_effective_status(ContainerStatus.ONLINE, 3) == ContainerStatus.ONLINE.value
    assert _derive_effective_status(ContainerStatus.OFFLINE, 3) == ContainerStatus.OFFLINE.value


def test_status_unknown_when_machine_collect_error(monkeypatch):
    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda mid: False)
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: True)
    monkeypatch.setattr(pydantic_models, "is_machine_collect_error", lambda mid: True)
    assert _derive_effective_status(ContainerStatus.ONLINE, 3) == ContainerEffectiveStatus.STATUS_UNKNOWN.value
    assert _derive_effective_status(ContainerStatus.CREATING, 3) == ContainerEffectiveStatus.STATUS_UNKNOWN.value


def test_host_conditions_take_precedence(monkeypatch):
    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda mid: True)
    assert _derive_effective_status(ContainerStatus.ONLINE, 3) == ContainerEffectiveStatus.HOST_MAINTENANCE.value

    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda mid: False)
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: False)
    assert _derive_effective_status(ContainerStatus.ONLINE, 3) == ContainerEffectiveStatus.HOST_OFFLINE.value


def test_failed_not_masked_by_collect_error(monkeypatch):
    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda mid: False)
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: True)
    monkeypatch.setattr(pydantic_models, "is_machine_collect_error", lambda mid: True)
    assert _derive_effective_status(ContainerStatus.FAILED, 3) == ContainerStatus.FAILED.value


def test_no_machine_id_returns_raw_status(monkeypatch):
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: False)
    assert _derive_effective_status(ContainerStatus.ONLINE, None) == ContainerStatus.ONLINE.value
