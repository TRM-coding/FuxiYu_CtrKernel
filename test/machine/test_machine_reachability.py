"""机器可达性读面测试。

链路（Ctrl 主动拨 Node）是机器状态主链路；普通 getter/API 只读 DB 状态，
不主动打 Node。换向后「不打 Node」已是结构性成立——机器状态只由链路连接
结果写入，读面没有任何出站探活路径可走。
"""

from ...constant import MachineStatus
from ...services import machine_tasks
from ..factories import create_machine


def test_get_machine_reachable_reads_online_from_db(db_session):
    machine = create_machine(machine_status=MachineStatus.ONLINE)

    assert machine_tasks.get_machine_reachable(machine.id) is True


def test_get_machine_reachable_reads_offline_from_db(db_session):
    machine = create_machine(machine_status=MachineStatus.OFFLINE)

    assert machine_tasks.get_machine_reachable(machine.id) is False


def test_get_machine_reachable_missing_machine_is_false(db_session):
    assert machine_tasks.get_machine_reachable(999999) is False
