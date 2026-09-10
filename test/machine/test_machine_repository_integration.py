from ...constant import MachineStatus
from ...repositories import machine_permission_repo, machine_repo
from ...services import machine_tasks
from ..factories import create_container, create_machine, create_user


def test_update_machine_with_real_repository(db_session):
    machine = create_machine(machine_name="repo_machine")

    assert machine_tasks.Update_machine(machine.id, machine_name="repo_machine_updated") is True

    db_session.expire_all()
    assert machine_repo.get_by_id(machine.id, session=db_session).machine_name == "repo_machine_updated"


def test_list_machine_bref_reads_status_without_probing(monkeypatch, db_session):
    """列表只读状态机落库状态，不再反向探活驱动（WSS 推送即采集）。"""
    machine = create_machine(machine_status=MachineStatus.OFFLINE)
    create_container(machine=machine)
    monkeypatch.setattr(machine_tasks, "is_machine_online_remote", lambda machine_id, timeout=2.0: True)

    machines, total_pages = machine_tasks.List_all_machine_bref_information(0, 10)

    assert total_pages == 1
    assert machines[0].id == machine.id
    assert machines[0].machine_status == MachineStatus.OFFLINE.value  # 即使探活为 True，列表也不反向改状态
    db_session.expire_all()
    assert machine_repo.get_by_id(machine.id, session=db_session).machine_status == MachineStatus.OFFLINE


def test_machine_permission_create_and_list_with_real_repository(db_session):
    machine = create_machine()
    user = create_user()

    assert machine_tasks.Add_machine_permission(machine.id, user.id) is True

    assert machine_permission_repo.list_user_ids_by_machine(machine.id, session=db_session) == [user.id]
    assert machine_tasks.List_machine_permissions(machine.id) == [user.id]
