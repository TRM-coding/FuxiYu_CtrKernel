"""动作任务的「管辖范畴」判定测试。

范畴 = 可达 且 非维护。三个动作任务（容器清理 / 挂载清理 / 磁盘检测）共用此判据。
维护是**独立标志**，机器状态可能仍是 ONLINE——只看状态会漏掉这一格。
"""

from ...constant import MachineStatus
from ...services import machine_tasks
from ..factories import create_machine


def test_online_without_maintenance_is_in_scope(db_session):
    machine = create_machine(machine_status=MachineStatus.ONLINE, is_maintenance=False)

    assert machine_tasks.machine_in_scope(machine.id) is True


def test_offline_machine_is_out_of_scope(db_session):
    machine = create_machine(machine_status=MachineStatus.OFFLINE)

    assert machine_tasks.machine_in_scope(machine.id) is False


def test_maintenance_machine_is_out_of_scope_while_online(db_session):
    """维护中且状态仍为 ONLINE → 范畴外（维护是独立标志，不能只看状态）。"""
    machine = create_machine(machine_status=MachineStatus.ONLINE, is_maintenance=True)

    assert machine_tasks.machine_in_scope(machine.id) is False


def test_missing_machine_is_out_of_scope(db_session):
    """记录缺失并入范畴外：判定不该在缺少依据时抛异常。"""
    assert machine_tasks.machine_in_scope(999999) is False


def test_none_machine_id_is_out_of_scope(db_session):
    """调用方拿不到 machine_id（如记录字段缺失）→ 范畴外，不抛异常。"""
    assert machine_tasks.machine_in_scope(None) is False
