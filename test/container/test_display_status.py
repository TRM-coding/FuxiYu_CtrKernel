"""容器展示态派生规则测试（DB 状态不动，仅派生 display_status）。"""

from ...services.container_tasks import (
    _derive_display_status,
    DISPLAY_STATUS_HOST_MAINTENANCE,
    DISPLAY_STATUS_HOST_OFFLINE,
)
from ...services.container_module import pydantic_models
from ...constant import ContainerStatus


def test_host_offline_overrides_running_states(monkeypatch):
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: False)
    assert _derive_display_status(ContainerStatus.ONLINE, 3) == DISPLAY_STATUS_HOST_OFFLINE
    assert _derive_display_status(ContainerStatus.OFFLINE, 3) == DISPLAY_STATUS_HOST_OFFLINE
    assert _derive_display_status(ContainerStatus.CREATING, 3) == DISPLAY_STATUS_HOST_OFFLINE


def test_failed_not_masked_by_host_offline(monkeypatch):
    """failed 是终态诊断，即使宿主机不可达也不覆盖。"""
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: False)
    assert _derive_display_status(ContainerStatus.FAILED, 3) == ContainerStatus.FAILED.value


def test_host_maintenance_uses_existing_display_status_derivation(monkeypatch):
    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda mid: True)
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: True)

    assert _derive_display_status(ContainerStatus.ONLINE, 3) == DISPLAY_STATUS_HOST_MAINTENANCE


def test_failed_not_masked_by_host_maintenance(monkeypatch):
    monkeypatch.setattr(pydantic_models, "is_machine_in_maintenance", lambda mid: True)

    assert _derive_display_status(ContainerStatus.FAILED, 3) == ContainerStatus.FAILED.value


def test_normal_when_reachable(monkeypatch):
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: True)
    assert _derive_display_status(ContainerStatus.ONLINE, 3) == ContainerStatus.ONLINE.value
    assert _derive_display_status(ContainerStatus.OFFLINE, 3) == ContainerStatus.OFFLINE.value


def test_no_machine_id_returns_raw_status(monkeypatch):
    monkeypatch.setattr(pydantic_models, "get_machine_reachable", lambda mid: False)
    assert _derive_display_status(ContainerStatus.ONLINE, None) == ContainerStatus.ONLINE.value
