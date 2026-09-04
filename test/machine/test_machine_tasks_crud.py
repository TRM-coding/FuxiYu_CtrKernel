import pytest

from sqlalchemy import select

from ...constant import MachineStatus, MachineTypes
from ...extensions import session_scope
from ...models.containers import Container
from ...models.machine import Machine
from ...repositories import machine_repo
from ...services import machine_tasks
from ..factories import create_container, create_machine


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

    machine = machine_repo.get_by_name("task_machine", session=db_session)
    assert machine is not None
    assert machine.machine_ip == "10.0.0.1"


def test_add_machine_with_null_max_shared_creates_machine(db_session):
    """回归：max_shared_gb=None（前端表单未填）时也必须真实入库。

    历史 bug：create_machine 调用曾被误缩进到 max_shared_gb 验证块内，
    None 时整段创建被跳过，Add_machine 返回 True 但库为空。
    """
    assert machine_tasks.Add_machine(**_machine_kwargs(max_shared_gb=None)) is True

    machine = machine_repo.get_by_name("task_machine", session=db_session)
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
    m1_id, m2_id = m1.id, m2.id

    result = machine_tasks.Remove_machine([m1_id, m2_id])
    assert result["blocked"] == []
    assert set(result["removed"]) == {m1_id, m2_id}

    db_session.expire_all()
    assert machine_repo.get_by_id(m1_id, session=db_session) is None
    assert machine_repo.get_by_id(m2_id, session=db_session) is None


def test_remove_machine_empty_list_returns_empty_result(db_session):
    assert machine_tasks.Remove_machine([]) == {"removed": [], "blocked": []}


def test_get_detail_information_success(db_session):
    machine = create_machine(machine_name="detail_machine", machine_status=MachineStatus.ONLINE)

    info = machine_tasks.Get_detail_information(machine.id)

    assert info.machine_name == "detail_machine"
    assert info.machine_status == MachineStatus.ONLINE.value
    assert info.containers == []


def test_get_detail_information_missing_machine_returns_none(db_session):
    assert machine_tasks.Get_detail_information(999999) is None


def test_remove_machine_refused_when_machine_has_containers(db_session):
    """机器上仍有容器 → 拒绝删除该台（2026-09 决策：不自动级联删物理容器）。"""
    from ...repositories import containers_repo

    m = create_machine(machine_name="has_containers")
    create_container(machine=m)
    db_session.commit()
    mid = m.id

    result = machine_tasks.Remove_machine([mid])

    assert result["removed"] == []
    assert result["blocked"] == [{"machine_id": mid, "name": "has_containers", "container_count": 1}]
    db_session.expire_all()
    assert machine_repo.get_by_id(mid, session=db_session) is not None, "有容器的机器不应被删除"

    # 清理容器后可删
    with session_scope() as session:
        containers_repo.delete_container(
            session.scalars(select(Container).where(Container.machine_id == mid)).first().id,
            session=session,
        )
    result = machine_tasks.Remove_machine([mid])
    assert result["removed"] == [mid]
    assert result["blocked"] == []


def test_update_machine_ip_change_repins_same_certificate(monkeypatch, db_session):
    """IP 变更自愈（2026-09）：新 IP 证书指纹与记录一致 → 自动导出新 pin。"""
    from pathlib import Path

    from ...services.container_module import node_comms

    machine = create_machine(machine_name="ip_change", machine_ip="10.0.0.1")
    machine.node_cert_fingerprint = "fp-same"
    db_session.commit()
    pin_dir = Path(node_comms.PINNED_CERTS_DIR)
    pin_dir.mkdir(parents=True, exist_ok=True)

    from ...utils import cert_utils

    monkeypatch.setattr(node_comms, "_fetch_peer_cert", lambda ip, timeout=5.0: ("fp-same", b"cert-der-bytes"))
    monkeypatch.setattr(node_comms, "request_wss_restart", lambda reason="pin_bundle_changed": {})
    monkeypatch.setattr(node_comms, "_pin_file", lambda ip: pin_dir / f"mocked_{ip}.pem")
    monkeypatch.setattr(cert_utils, "der_cert_to_pem", lambda der: b"pem-" + der)

    assert machine_tasks.Update_machine(machine.id, machine_ip="10.0.0.99") is True

    db_session.expire_all()
    assert db_session.get(Machine, machine.id).machine_ip == "10.0.0.99"
    assert (pin_dir / "mocked_10.0.0.99.pem").read_bytes() == b"pem-cert-der-bytes"


def test_update_machine_ip_change_refused_on_fingerprint_mismatch(monkeypatch, db_session):
    """换 IP 且证书指纹不一致 → 拒绝（防劫持），机器记录不变。"""
    from ...services.container_module import node_comms

    machine = create_machine(machine_name="ip_hijack", machine_ip="10.0.0.1")
    machine.node_cert_fingerprint = "fp-original"
    db_session.commit()

    monkeypatch.setattr(node_comms, "_fetch_peer_cert", lambda ip, timeout=5.0: ("fp-attacker", b"x"))

    with pytest.raises(ValueError) as excinfo:
        machine_tasks.Update_machine(machine.id, machine_ip="10.0.0.99")

    assert getattr(excinfo.value, "error_reason") == "ip_change_fingerprint_mismatch"
    db_session.expire_all()
    assert db_session.get(Machine, machine.id).machine_ip == "10.0.0.1"
