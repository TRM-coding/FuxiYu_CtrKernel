import pytest

from ...constant import ContainerStatus, MachineStatus, PERMISSION
from ...models.containers import Container
from ...models.machine import Machine
from ...repositories import machine_permission_repo
from ...services import machine_tasks
from ..factories import bind_user_container, create_container, create_machine, create_user


def test_update_machine_missing_machine_returns_false(db_session):
    assert machine_tasks.Update_machine(999999, machine_name="missing") is False


def test_update_machine_regular_update_calls_repo(db_session):
    machine = create_machine(machine_name="update_machine")

    assert machine_tasks.Update_machine(machine.id, machine_name="updated_machine") is True

    assert Machine.query.get(machine.id).machine_name == "updated_machine"


@pytest.mark.parametrize("value", ["bad", 9, -1])
def test_update_machine_rejects_invalid_shared_size(db_session, value):
    machine = create_machine(max_memory_gb=8)

    with pytest.raises(ValueError) as excinfo:
        machine_tasks.Update_machine(machine.id, max_shared_gb=value)

    assert getattr(excinfo.value, "error_reason") == "update_failed"


def test_update_machine_rejects_max_shared_greater_than_target_memory(db_session):
    machine = create_machine(max_memory_gb=8)

    with pytest.raises(ValueError, match="cannot be greater"):
        machine_tasks.Update_machine(machine.id, max_shared_gb=6, max_memory_gb=4)


def test_update_machine_sets_maintenance_switch(db_session):
    # 维护态为纯开关，不写入 machine_status。
    machine = create_machine(machine_status=MachineStatus.ONLINE, machine_description="old")

    assert machine_tasks.Update_machine(machine.id, is_maintenance=True, machine_description="new") is True

    refreshed = Machine.query.get(machine.id)
    assert refreshed.machine_status == MachineStatus.ONLINE
    assert refreshed.is_maintenance is True
    assert refreshed.machine_description == "new"


def test_update_machine_rejects_maintenance_as_machine_status(db_session):
    machine = create_machine(machine_status=MachineStatus.ONLINE)

    with pytest.raises(ValueError, match="is_maintenance"):
        machine_tasks.Update_machine(machine.id, machine_status="maintenance")


def test_is_machine_online_remote_true_when_node_online(monkeypatch, db_session):
    machine = create_machine(machine_ip="10.0.0.8")
    monkeypatch.setattr(machine_tasks, "send", lambda url, payload, timeout=2.0: {"success": 1, "machine_status": "online"})

    assert machine_tasks.is_machine_online_remote(machine.id) is True


def test_is_machine_online_remote_false_when_machine_missing(db_session):
    assert machine_tasks.is_machine_online_remote(999999) is False


def test_is_machine_online_remote_false_when_node_offline(monkeypatch, db_session):
    machine = create_machine()
    monkeypatch.setattr(machine_tasks, "send", lambda url, payload, timeout=2.0: {"success": 1, "machine_status": "offline"})

    assert machine_tasks.is_machine_online_remote(machine.id) is False


def test_is_machine_online_remote_false_when_send_raises(monkeypatch, db_session):
    machine = create_machine()
    monkeypatch.setattr(machine_tasks, "send", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network")))

    assert machine_tasks.is_machine_online_remote(machine.id) is False


def test_list_machine_bref_marks_online_machine_online(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.OFFLINE)
    monkeypatch.setattr(machine_tasks, "is_machine_online_remote", lambda machine_id, timeout=2.0: True)

    result, total_pages = machine_tasks.List_all_machine_bref_information(0, 10)

    assert total_pages == 1
    assert result[0].id == machine.id
    assert Machine.query.get(machine.id).machine_status == MachineStatus.ONLINE


def test_list_machine_bref_marks_offline_machine_and_containers_offline(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.ONLINE)
    container = create_container(machine=machine, status=ContainerStatus.ONLINE)
    monkeypatch.setattr(machine_tasks, "is_machine_online_remote", lambda machine_id, timeout=2.0: False)

    result, _ = machine_tasks.List_all_machine_bref_information(0, 10)

    assert result[0].machine_status == MachineStatus.OFFLINE.value
    assert Container.query.get(container.id).container_status == ContainerStatus.OFFLINE


def test_list_machine_bref_keeps_maintenance_display_when_remote_online(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.OFFLINE, is_maintenance=True)
    monkeypatch.setattr(machine_tasks, "is_machine_online_remote", lambda machine_id, timeout=2.0: True)

    result, _ = machine_tasks.List_all_machine_bref_information(0, 10)

    assert result[0].machine_status == MachineStatus.ONLINE.value
    assert result[0].is_maintenance is True
    assert result[0].display_status == "maintenance"


def test_list_machine_bref_marks_connection_offline_but_keeps_maintenance_display(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.ONLINE, is_maintenance=True)
    monkeypatch.setattr(machine_tasks, "is_machine_online_remote", lambda machine_id, timeout=2.0: False)

    result, _ = machine_tasks.List_all_machine_bref_information(0, 10)

    assert result[0].machine_status == MachineStatus.OFFLINE.value
    assert result[0].is_maintenance is True
    assert result[0].display_status == "maintenance"


def test_list_machine_bref_filters_non_operator_by_machine_permission(monkeypatch, db_session):
    user = create_user(permission=PERMISSION.USER)
    allowed = create_machine(machine_name="allowed_machine")
    create_machine(machine_name="blocked_machine")
    machine_permission_repo.add_permission(allowed.id, user.id)
    monkeypatch.setattr(machine_tasks, "is_machine_online_remote", lambda machine_id, timeout=2.0: True)

    result, _ = machine_tasks.List_all_machine_bref_information(0, 10, user_id=user.id)

    assert [m.id for m in result] == [allowed.id]


def test_list_machine_bref_operator_bypasses_machine_permission(monkeypatch, db_session):
    operator = create_user(permission=PERMISSION.OPERATOR)
    m1 = create_machine(machine_name="operator_machine_1")
    m2 = create_machine(machine_name="operator_machine_2")
    monkeypatch.setattr(machine_tasks, "is_machine_online_remote", lambda machine_id, timeout=2.0: True)

    result, _ = machine_tasks.List_all_machine_bref_information(0, 10, user_id=operator.id)

    assert {m.id for m in result} == {m1.id, m2.id}
