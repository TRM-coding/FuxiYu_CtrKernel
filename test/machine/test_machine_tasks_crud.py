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
    monkeypatch.setattr(machine_tasks, "_fetch_peer_cert", lambda host, port, timeout: ("fingerprint", b"certificate"))
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

    def _fetch_peer_cert(host, port, timeout=8.0):
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


def test_update_machine_ip_change_is_pure_registration(monkeypatch, db_session):
    """改地址只写记录，不发出站连接、不动 pin。

    2026-09 曾在此做「新址首连 → 指纹比对 → 相符则导出新 pin」的自愈。那次反转的理由：
    可达性是连接期的事实，不该成为登记的前置条件——要改地址的场景往往正是端点不通的时候。
    身份判据落在对端（Node 校验链路携带的 uid），不靠 Ctrl 在写记录时判定。
    """
    from ...services.container_module import node_comms

    machine = create_machine(machine_name="ip_change", machine_ip="10.0.0.1")
    machine.node_cert_fingerprint = "fp-same"
    db_session.commit()

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("登记路径不得发出站取证")

    monkeypatch.setattr(node_comms, "_fetch_peer_cert", _must_not_be_called)

    assert machine_tasks.Update_machine(machine.id, machine_ip="10.0.0.99") is True

    db_session.expire_all()
    assert db_session.get(Machine, machine.id).machine_ip == "10.0.0.99"


def test_update_machine_ip_change_succeeds_while_new_address_unreachable(monkeypatch, db_session):
    """新地址当前不可达也能登记成功——可达性不是登记的前置条件。"""
    machine = create_machine(machine_name="ip_down", machine_ip="10.0.0.1")
    db_session.commit()

    assert machine_tasks.Update_machine(machine.id, machine_ip="10.0.0.200") is True

    db_session.expire_all()
    assert db_session.get(Machine, machine.id).machine_ip == "10.0.0.200"


def test_update_machine_rejects_address_carrying_port(db_session):
    """主机地址保持纯 IPv4：端口走独立字段，拒绝 `host:port` 的隐式写法。"""
    machine = create_machine(machine_name="ip_with_port", machine_ip="10.0.0.1")
    db_session.commit()

    with pytest.raises(ValueError) as excinfo:
        machine_tasks.Update_machine(machine.id, machine_ip="10.0.0.99:6789")

    assert getattr(excinfo.value, "error_reason") == "invalid_machine_ip"
    db_session.expire_all()
    assert db_session.get(Machine, machine.id).machine_ip == "10.0.0.1"


def test_update_machine_accepts_port_and_can_clear_it(db_session):
    """端口可设可清：清空即回到「回落全局默认」。"""
    machine = create_machine(machine_name="port_edit", machine_ip="10.0.0.1")
    db_session.commit()

    assert machine_tasks.Update_machine(machine.id, port=6789) is True
    db_session.expire_all()
    assert db_session.get(Machine, machine.id).port == 6789

    assert machine_tasks.Update_machine(machine.id, port=None) is True
    db_session.expire_all()
    assert db_session.get(Machine, machine.id).port is None


class TestGpuAllowance:
    """单容器 GPU 上限的唯一落点：许可列表长度，未配置回退实装卡数。

    旧列 max_gpu_number 已删——它退役后上限改由本规则表达，而那一列既不读也不写，
    留着只会让人以为改它有效。详情响应仍以 `max_gpu_number` 为名暴露，但值是现算的，
    所以前端零改动。
    """

    def test_allow_list_length_wins(self, db_session):
        machine = create_machine(gpu_number=8, gpu_allow_list=[0, 1, 2, 3, 4])

        assert machine_repo.gpu_allowance(machine) == 5

    def test_falls_back_to_installed_count(self, db_session):
        machine = create_machine(gpu_number=8, gpu_allow_list=None)

        assert machine_repo.gpu_allowance(machine) == 8

    def test_empty_list_means_unconfigured_not_zero(self, db_session):
        """空列表 = 未配置（等同全量），不是「一张都不许」。"""
        machine = create_machine(gpu_number=3, gpu_allow_list=[])

        assert machine_repo.gpu_allowance(machine) == 3

    def test_cpu_machine_reports_zero(self, db_session):
        machine = create_machine(machine_type=MachineTypes.CPU, gpu_number=0, gpu_allow_list=None)

        assert machine_repo.gpu_allowance(machine) == 0

    def test_detail_response_reports_the_derived_value(self, db_session):
        """详情响应里的 max_gpu_number 是派生值，不是读列。"""
        machine = create_machine(gpu_number=8, gpu_allow_list=[0, 1, 2])

        info = machine_tasks.Get_detail_information(machine.id)

        assert info.max_gpu_number == 3

    def test_model_no_longer_declares_the_column(self, db_session):
        """锁住删除：列不得回来（回来也只会有列没人写，误导改它的人）。"""
        assert "max_gpu_number" not in Machine.__table__.columns
