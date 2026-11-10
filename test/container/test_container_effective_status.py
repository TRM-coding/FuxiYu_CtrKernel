from types import SimpleNamespace

import pytest

from ...services.container_module.pydantic_models import _derive_effective_status
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


@pytest.mark.parametrize("source", ["snapshot_missing", "delete_frame"])
def test_vanished_clues_are_distinct_and_host_conditions_take_precedence(monkeypatch, source):
    row = SimpleNamespace(status_unknown_since=object(), status_source=source)
    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda _: False)
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda _: True)
    monkeypatch.setattr(pydantic_models, "is_machine_collect_error", lambda _: False)
    assert _derive_effective_status(ContainerStatus.BUILDING, 7, container=row) == ContainerEffectiveStatus.NODE_VANISHED.value
    assert _derive_effective_status(ContainerStatus.FAILED, 7, container=row) == ContainerStatus.FAILED.value
    monkeypatch.setattr(pydantic_models, "is_machine_collect_error", lambda _: True)
    assert _derive_effective_status(ContainerStatus.BUILDING, 7, container=row) == ContainerEffectiveStatus.STATUS_UNKNOWN.value
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda _: False)
    assert _derive_effective_status(ContainerStatus.BUILDING, 7, container=row) == ContainerEffectiveStatus.HOST_OFFLINE.value
    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda _: True)
    assert _derive_effective_status(ContainerStatus.BUILDING, 7, container=row) == ContainerEffectiveStatus.HOST_MAINTENANCE.value


def test_other_unknown_source_is_not_vanished(monkeypatch):
    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda _: False)
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda _: True)
    monkeypatch.setattr(pydantic_models, "is_machine_collect_error", lambda _: False)
    row = SimpleNamespace(status_unknown_since=object(), status_source="create_failed")
    assert _derive_effective_status(ContainerStatus.BUILDING, 7, container=row) == ContainerEffectiveStatus.STATUS_UNKNOWN.value
