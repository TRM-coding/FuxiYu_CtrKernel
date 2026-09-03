import pytest

from ...constant import MachineStatus, MachineTypes
from ...models.machine import Machine
from ...services import machine_tasks
from ..factories import create_machine


def _machine_kwargs(**overrides):
    data = {
        "machine_name": "task_machine",
        "machine_ip": "10.0.0.1",
        "machine_type": MachineTypes.GPU,
        "machine_description": "desc",
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


def test_add_machine_success_creates_machine(db_session):
    assert machine_tasks.Add_machine(**_machine_kwargs()) is True

    machine = Machine.query.filter_by(machine_name="task_machine").first()
    assert machine is not None
    assert machine.machine_ip == "10.0.0.1"


def test_add_machine_with_null_max_shared_creates_machine(db_session):
    """回归：max_shared_gb=None（前端表单未填）时也必须真实入库。

    历史 bug：create_machine 调用曾被误缩进到 max_shared_gb 验证块内，
    None 时整段创建被跳过，Add_machine 返回 True 但库为空。
    """
    assert machine_tasks.Add_machine(**_machine_kwargs(max_shared_gb=None)) is True

    machine = Machine.query.filter_by(machine_name="task_machine").first()
    assert machine is not None
    assert machine.machine_ip == "10.0.0.1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("machine_name", "m" * 116),
        ("gpu_type", "g" * 116),
        ("machine_type", "t" * 256),
    ],
)
def test_add_machine_rejects_long_string_fields(db_session, field, value):
    with pytest.raises(ValueError):
        machine_tasks.Add_machine(**_machine_kwargs(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("max_shared_gb", "bad", "max_shared_gb must be an integer"),
        ("max_shared_gb", 0, "shared size out of range"),
        ("max_memory_gb", "bad", "max_memory_gb must be an integer"),
        ("max_shared_gb", 9, "cannot be greater than max_memory_gb"),
    ],
)
def test_add_machine_rejects_invalid_shared_memory_config(db_session, field, value, message):
    kwargs = _machine_kwargs(max_memory_gb=8)
    kwargs[field] = value

    with pytest.raises(ValueError, match=message) as excinfo:
        machine_tasks.Add_machine(**kwargs)

    assert getattr(excinfo.value, "error_reason") == "create_failed"


def test_remove_machine_deletes_each_id(db_session):
    m1 = create_machine(machine_name="remove_1")
    m2 = create_machine(machine_name="remove_2")

    assert machine_tasks.Remove_machine([m1.id, m2.id]) is True

    assert Machine.query.get(m1.id) is None
    assert Machine.query.get(m2.id) is None


def test_remove_machine_empty_list_returns_true(db_session):
    assert machine_tasks.Remove_machine([]) is True


def test_get_detail_information_success(db_session):
    machine = create_machine(machine_name="detail_machine", machine_status=MachineStatus.ONLINE)

    info = machine_tasks.Get_detail_information(machine.id)

    assert info.machine_name == "detail_machine"
    assert info.machine_status == MachineStatus.ONLINE.value
    assert info.containers == []


def test_get_detail_information_missing_machine_returns_none(db_session):
    assert machine_tasks.Get_detail_information(999999) is None
