from ...constant import MachineStatus, MachineTypes
from ...repositories import machine_permission_repo, machine_repo
from ...services import machine_tasks
from ..factories import create_container, create_machine, create_user


def _machine_kwargs(**overrides):
    data = {
        "machine_name": "repo_machine",
        "machine_ip": "10.0.0.10",
        "machine_type": MachineTypes.GPU,
        "machine_description": "repository-backed test machine",
        "cpu_core_number": 16,
        "gpu_number": 2,
        "gpu_type": "A100",
        "memory_size": 128,
        "max_shared_gb": 4,
        "disk_size": 512,
        "max_memory_gb": 128,
        "max_gpu_number": 2,
        "max_cpu_core_number": 16,
    }
    data.update(overrides)
    return data


def test_add_and_update_machine_with_real_repository(db_session):
    assert machine_tasks.Add_machine(**_machine_kwargs()) is True
    machine = machine_repo.get_by_name("repo_machine", session=db_session)
    assert machine is not None

    assert machine_tasks.Update_machine(machine.id, machine_name="repo_machine_updated") is True

    db_session.expire_all()
    assert machine_repo.get_by_id(machine.id, session=db_session).machine_name == "repo_machine_updated"


def test_list_machine_bref_updates_status_with_mocked_probe(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.OFFLINE)
    create_container(machine=machine)
    monkeypatch.setattr(machine_tasks, "is_machine_online_remote", lambda machine_id, timeout=2.0: True)

    machines, total_pages = machine_tasks.List_all_machine_bref_information(0, 10)

    assert total_pages == 1
    assert machines[0].id == machine.id
    assert machines[0].machine_status == MachineStatus.ONLINE.value
    db_session.expire_all()
    assert machine_repo.get_by_id(machine.id, session=db_session).machine_status == MachineStatus.ONLINE


def test_machine_permission_create_and_list_with_real_repository(db_session):
    machine = create_machine()
    user = create_user()

    assert machine_tasks.Add_machine_permission(machine.id, user.id) is True

    assert machine_permission_repo.list_user_ids_by_machine(machine.id, session=db_session) == [user.id]
    assert machine_tasks.List_machine_permissions(machine.id) == [user.id]
