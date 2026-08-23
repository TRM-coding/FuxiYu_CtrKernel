"""机器可达性读面测试。

WSS 是机器状态主链路；普通 getter/API 只读 DB 状态，不主动打 Node。
"""

from ...constant import MachineStatus
from ...services import machine_tasks
from ..factories import create_machine


def test_get_machine_reachable_reads_online_from_db(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.ONLINE)

    monkeypatch.setattr(
        machine_tasks,
        "is_machine_online_remote",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not probe node")),
    )

    assert machine_tasks.get_machine_reachable(machine.id) is True


def test_get_machine_reachable_reads_offline_from_db(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.OFFLINE)

    monkeypatch.setattr(
        machine_tasks,
        "is_machine_online_remote",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not probe node")),
    )

    assert machine_tasks.get_machine_reachable(machine.id) is False


def test_get_machine_reachable_missing_machine_is_false(db_session):
    assert machine_tasks.get_machine_reachable(999999) is False
