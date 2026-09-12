import pytest

from sqlalchemy import select

from ...constant import MachineStatus, MachineTypes, OperationType
from ...extensions import session_scope
from ...models.containers import Container
from ...models.machine import Machine
from ...models.operation_log import OperationLog
from ...repositories import machine_repo
from ...services import machine_tasks
from ...services.container_module.node_comms_modules import transport as comms_transport
from ..factories import create_container, create_machine, create_user


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
    # 换向后注册不再触发任何重载动作：机器行落库即完成接入，
    # 链路进程下一轮集合对齐会自行拨通它。
    assert "wss_restart_requested" not in result


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


def test_register_machine_same_ip_twice_is_rejected(db_session, enrollment_transport):
    """现状：对已登记的 IP 再注册一次会被唯一约束拒绝，没有就地更新路径。

    这条是「重新 TOFU」的拦路虎——Update_machine 的换 IP 分支在证书变更时
    提示调用方 "re-register instead"，但重复注册本身并不通。
    """

    machine_tasks.Register_machine("task_machine", "10.0.0.1")

    with pytest.raises(machine_tasks.NodeServiceError) as exc:
        machine_tasks.Register_machine("task_machine_again", "10.0.0.1")

    assert exc.value.reason == "persist_failed"
    assert machine_repo.get_by_name("task_machine_again", session=db_session) is None


@pytest.fixture
def renew_transport(monkeypatch):
    """重钉路径的全部外部接缝替身；返回可编程状态。"""

    state = {
        "fingerprint": "fp-new",
        "cert_der": b"cert-der-new",
        "profile": {"identity_initialized": True, "uid": "uid-from-node"},
        "issued_uids": [],
        "pins": [],
        "unreachable": False,
    }

    def _fetch_peer_cert(machine_ip, timeout=8.0):
        if state["unreachable"]:
            raise OSError("connect refused")
        return state["fingerprint"], state["cert_der"]

    monkeypatch.setattr(machine_tasks, "_get_enrollment_client_cert", lambda: None)
    monkeypatch.setattr(machine_tasks, "_fetch_peer_cert", _fetch_peer_cert)
    monkeypatch.setattr(machine_tasks, "_fetch_enrollment_profile", lambda *a, **k: dict(state["profile"]))
    monkeypatch.setattr(
        machine_tasks, "_issue_node_uid",
        lambda url, ip, uid, cert, timeout: state["issued_uids"].append(uid),
    )
    monkeypatch.setattr(machine_tasks, "_persist_peer_pin", lambda ip, der: state["pins"].append((ip, der)))
    return state


def _enrolled_machine(db_session, *, uid="old-uid", fingerprint="fp-old"):
    machine = create_machine(machine_name="renew_target", machine_ip="10.0.0.9")
    with session_scope() as session:
        machine_repo.update_machine(
            machine.id, node_uid=uid, node_cert_fingerprint=fingerprint, session=session,
        )
    return machine


def test_renew_machine_trust_updates_row_in_place(db_session, renew_transport):
    """证书变化 → pin 覆盖、指纹更新；id / name / ip 一律不动（UPDATE，不建行）。"""
    machine = _enrolled_machine(db_session)
    before = (machine.id, machine.machine_name, machine.machine_ip)
    rows_before = db_session.scalars(select(Machine)).all()

    result = machine_tasks.Renew_machine_trust(machine.id)

    db_session.expire_all()
    row = db_session.get(Machine, machine.id)
    assert (row.id, row.machine_name, row.machine_ip) == before
    assert len(db_session.scalars(select(Machine)).all()) == len(rows_before)
    assert row.node_cert_fingerprint == "fp-new"
    assert row.cert_pinned_at is not None
    assert renew_transport["pins"] == [("10.0.0.9", b"cert-der-new")]
    assert result["certificate_fingerprint"] == "fp-new"
    assert result["previous_certificate_fingerprint"] == "fp-old"


def test_renew_machine_trust_keeps_uid_when_certificate_only_changed(db_session, renew_transport):
    """证书轮换不该扰动应用层身份：对端身份牌完好 → uid 原样保留。"""
    machine = _enrolled_machine(db_session, uid="stable-uid")
    renew_transport["profile"] = {"identity_initialized": True, "uid": "stable-uid"}

    result = machine_tasks.Renew_machine_trust(machine.id)

    db_session.expire_all()
    assert db_session.get(Machine, machine.id).node_uid == "stable-uid"
    assert renew_transport["issued_uids"] == []
    assert (result["uid_reissued"], result["uid_adopted"], result["uid_mismatch"]) == (False, False, False)


def test_renew_machine_trust_missing_machine(db_session, renew_transport):
    with pytest.raises(machine_tasks.NodeServiceError) as exc:
        machine_tasks.Renew_machine_trust(999999)
    assert exc.value.reason == "machine_not_found"
    assert db_session.scalars(select(Machine)).all() == []


def test_renew_machine_trust_unreachable_leaves_everything_intact(db_session, renew_transport):
    """「随时可按」的前提：抓不到对端就整体不落地，旧信任一个字节都不许动。"""
    machine = _enrolled_machine(db_session, uid="keep-me", fingerprint="fp-old")
    renew_transport["unreachable"] = True

    with pytest.raises(machine_tasks.NodeServiceError) as exc:
        machine_tasks.Renew_machine_trust(machine.id)

    assert exc.value.reason == "machine_unreachable"
    db_session.expire_all()
    row = db_session.get(Machine, machine.id)
    assert row.node_uid == "keep-me"
    assert row.node_cert_fingerprint == "fp-old"
    assert renew_transport["pins"] == []


def test_renew_machine_trust_reissues_uid_when_peer_lost_identity(db_session, renew_transport):
    """对端丢了身份牌（Node 重装）→ 重发 uid 并下发。"""
    machine = _enrolled_machine(db_session)
    renew_transport["profile"] = {"identity_initialized": False, "uid": None}

    result = machine_tasks.Renew_machine_trust(machine.id)

    db_session.expire_all()
    row = db_session.get(Machine, machine.id)
    assert result["uid_reissued"] is True
    assert renew_transport["issued_uids"] == [row.node_uid]
    assert row.node_uid not in (None, "old-uid")


def test_renew_machine_trust_adopts_reported_uid_when_db_has_none(db_session, renew_transport):
    """库里本无 uid，对端自报一个 → 采纳（Ctrl 在那行上没有主张，不算覆盖）。"""
    machine = _enrolled_machine(db_session, uid=None)
    renew_transport["profile"] = {"identity_initialized": True, "uid": "node-self-reported"}

    result = machine_tasks.Renew_machine_trust(machine.id)

    db_session.expire_all()
    assert db_session.get(Machine, machine.id).node_uid == "node-self-reported"
    assert result["uid_adopted"] is True
    assert renew_transport["issued_uids"] == []


def test_renew_machine_trust_flags_uid_mismatch_without_overwriting(db_session, renew_transport):
    """两边都有 uid 且不一致 → 保持库里的值，只把不一致报出来由人判断。"""
    machine = _enrolled_machine(db_session, uid="db-uid")
    renew_transport["profile"] = {"identity_initialized": True, "uid": "node-uid-other"}

    result = machine_tasks.Renew_machine_trust(machine.id)

    db_session.expire_all()
    assert db_session.get(Machine, machine.id).node_uid == "db-uid"
    assert result["uid_mismatch"] is True


def test_renew_machine_trust_writes_op_log_on_success(db_session, renew_transport):
    machine = _enrolled_machine(db_session)
    operator = create_user()

    machine_tasks.Renew_machine_trust(machine.id, operator_user_id=operator.id)

    log = db_session.scalars(
        select(OperationLog).filter_by(operation=OperationType.RENEW_MACHINE_TRUST.value)
    ).one()
    assert log.success is True
    assert log.target_id == machine.id
    assert log.detail["fingerprint_before"] == "fp-old"
    assert log.detail["fingerprint_after"] == "fp-new"
    # 详情节只记指纹，不落证书正文
    assert "cert-der-new" not in str(log.detail)


def test_renew_machine_trust_writes_op_log_on_failure(db_session, renew_transport):
    machine = _enrolled_machine(db_session)
    renew_transport["unreachable"] = True

    with pytest.raises(machine_tasks.NodeServiceError):
        machine_tasks.Renew_machine_trust(machine.id)

    log = db_session.scalars(
        select(OperationLog).filter_by(operation=OperationType.RENEW_MACHINE_TRUST.value)
    ).one()
    assert log.success is False
    assert log.error_reason == "machine_unreachable"


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
    pin_dir = Path(comms_transport.PINNED_CERTS_DIR)
    pin_dir.mkdir(parents=True, exist_ok=True)

    from ...utils import cert_utils

    monkeypatch.setattr(node_comms, "_fetch_peer_cert", lambda ip, timeout=5.0: ("fp-same", b"cert-der-bytes"))
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
