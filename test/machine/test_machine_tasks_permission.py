import pytest

from ...repositories import machine_permission_repo
from ...services import machine_tasks
from ..factories import create_machine, create_user


def test_add_machine_permission_success(db_session):
    machine = create_machine()
    user = create_user()

    assert machine_tasks.Add_machine_permission(machine.id, user.id) is True

    assert machine_permission_repo.list_user_ids_by_machine(machine.id) == [user.id]


def test_add_machine_permission_machine_not_found(db_session):
    user = create_user()

    with pytest.raises(ValueError, match="machine_not_found"):
        machine_tasks.Add_machine_permission(999999, user.id)


def test_add_machine_permission_user_not_found(db_session):
    machine = create_machine()

    with pytest.raises(ValueError, match="user_not_found"):
        machine_tasks.Add_machine_permission(machine.id, 999999)


def test_remove_machine_permission_returns_repo_result(db_session):
    machine = create_machine()
    user = create_user()
    machine_permission_repo.add_permission(machine.id, user.id)

    assert machine_tasks.Remove_machine_permission(machine.id, user.id) is True
    assert machine_tasks.Remove_machine_permission(machine.id, user.id) is False


def test_list_machine_permissions_returns_repo_result(db_session):
    machine = create_machine()
    user = create_user()
    machine_permission_repo.add_permission(machine.id, user.id)

    assert machine_tasks.List_machine_permissions(machine.id) == [user.id]
