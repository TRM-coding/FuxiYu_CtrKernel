import pytest

from sqlalchemy import select

from ...constant import MachineStatus, MachineTypes
from ...extensions import session_scope
from ...models.containers import Container
from ...models.machine import Machine
from ...repositories import machine_repo
from ...services import machine_tasks
from ..factories import create_container, create_machine


@pytest.fixture
def enrollment_transport(monkeypatch):
    from ...services.container_module import node_comms
    from ...services.container_module.node_comms_modules import enrollment

    hardware = {"cpu": {"cores": 16}, "memory": {"total_gb": 128}, "disk": {"total_gb": 512}, "gpu": [{"name": "A100"}]}
    monkeypatch.setattr(enrollment, "DEFAULT_RESOURCE_RATIO", 0.5)
    monkeypatch.setattr(machine_tasks, "_get_enrollment_client_cert", lambda: None)
    monkeypatch.setattr(machine_tasks, "_fetch_peer_cert", lambda ip, timeout: ("fingerprint", b"certificate"))
    monkeypatch.setattr(machine_tasks, "_request_enrollment_profile", lambda *args: hardware)
    monkeypatch.setattr(machine_tasks, "_issue_node_uid", lambda *args: None)
    monkeypatch.setattr(machine_tasks, "_persist_peer_pin", lambda *args: None)
    monkeypatch.setattr(node_comms, "request_wss_restart", lambda **kwargs: {"wss_restart_requested": True})
    return hardware


def test_register_machine_persists_identity_hardware_and_limits(db_session, enrollment_transport):
    result = machine_tasks.Register_machine("task_machine", "10.0.0.1", "registered host")
    machine = machine_repo.get_by_name("task_machine", session=db_session)
    assert result["success"] is True
    assert machine.id == result["machine_id"]
    assert machine.node_uid == result["uid"]
    assert machine.node_cert_fingerprint == "fingerprint"
    assert machine.machine_type == MachineTypes.GPU
    assert machine.cpu_core_number == 16
    assert machine.max_cpu_core_number == 8
    assert machine.memory_size_gb == 128
    assert machine.max_memory_gb == 64
    assert machine.machine_description == "registered host"
    assert result["hardware"] == enrollment_transport
    assert result["wss_restart_requested"] is True


@pytest.mark.parametrize(("name", "ip"), [("", "10.0.0.1"), ("node", "")])
def test_register_machine_rejects_missing_trust_anchor(db_session, name, ip):
    with pytest.raises(machine_tasks.NodeServiceError) as exc:
        machine_tasks.Register_machine(name, ip)
    assert exc.value.reason == "invalid_trust_anchor"
    assert db_session.scalars(select(Machine)).all() == []


def test_register_machine_failed_uid_issue_does_not_create_record(db_session, enrollment_transport, monkeypatch):
    def fail(*args):
        raise machine_tasks.NodeServiceError("rejected", reason="issue_uid_rejected")

    monkeypatch.setattr(machine_tasks, "_issue_node_uid", fail)
    with pytest.raises(machine_tasks.NodeServiceError) as exc:
        machine_tasks.Register_machine("task_machine", "10.0.0.1")
    assert exc.value.reason == "issue_uid_rejected"
    assert machine_repo.get_by_name("task_machine", session=db_session) is None


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
