"""机器端点解析与机器端口的建档 / 编辑（2026-09）。

端口此前是全局的（CommsConfig.NODE_PORT）。本组测试锁的是它成为机器属性之后的
三件事：**取值来源唯一**（机器列优先、留空回落、回落值调用时读取）、**三条出站
路径共用同一解析**、**pin 键与端口解耦**（换端口不必重新建立信任）。
"""

import pytest

from ...config import CommsConfig
from ...repositories import machine_repo
from ...services import machine_tasks
from ...services.container_module import node_comms
from ...services.container_module.node_comms_modules import link, transport
from ...services.container_module.node_comms_modules.endpoint import (
    bare_host,
    default_node_port,
    machine_endpoint,
    resolve_endpoint,
    resolve_port,
)
from ...services.container_module.node_comms_modules.enrollment import _validate_node_port
from ..factories import create_machine


############################################################
# 取值来源唯一
############################################################

def test_explicit_port_wins_over_global_default():
    assert resolve_port(6789) == 6789


def test_empty_port_falls_back_to_global_default(monkeypatch):
    monkeypatch.setattr(CommsConfig, "NODE_PORT", 5789)

    assert resolve_port(None) == 5789
    assert resolve_port(0) == 5789


def test_default_is_read_at_call_time_not_frozen(monkeypatch):
    """回落值必须现读：导入期冻结的派生串会形成第二个可漂移的真值来源。"""
    monkeypatch.setattr(CommsConfig, "NODE_PORT", 1111)
    assert default_node_port() == 1111

    monkeypatch.setattr(CommsConfig, "NODE_PORT", 2222)
    assert default_node_port() == 2222
    assert resolve_port(None) == 2222


def test_bare_host_drops_port_segment():
    assert bare_host("10.0.0.7:6789") == "10.0.0.7"
    assert bare_host("10.0.0.7") == "10.0.0.7"
    assert bare_host(None) == ""


def test_resolve_endpoint_pairs_host_and_port(monkeypatch):
    monkeypatch.setattr(CommsConfig, "NODE_PORT", 5789)

    assert resolve_endpoint("10.0.0.7", 6789) == ("10.0.0.7", 6789)
    assert resolve_endpoint("10.0.0.7", None) == ("10.0.0.7", 5789)


def test_machine_endpoint_reads_row(db_session):
    machine = create_machine(machine_name="ep_row", machine_ip="10.0.0.7")

    assert machine_endpoint(machine) == ("10.0.0.7", CommsConfig.NODE_PORT)
    machine.port = 6789
    assert machine_endpoint(machine) == ("10.0.0.7", 6789)


############################################################
# 三条出站路径共用同一端口
############################################################

def test_https_action_url_uses_machine_port():
    assert node_comms.get_full_url("10.0.0.7", "/create_container", 6789) == (
        "https://10.0.0.7:6789/api/create_container"
    )


def test_link_url_uses_machine_port():
    assert link.link_url("10.0.0.7", 6789, "uid-7") == "wss://10.0.0.7:6789/ws/ctrl?uid=uid-7"


def test_peer_cert_probe_uses_machine_port(monkeypatch):
    """TOFU 取证书也要走同一端口——取错端口会表现为「建档成功但拿不到身份」。"""
    from ...services.container_module.node_comms_modules import enrollment

    seen = []

    class _Sock:
        def getpeercert(self, binary_form=False):
            return b"der"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _Ctx:
        check_hostname = True
        verify_mode = None

        def wrap_socket(self, sock, server_hostname=None):
            return _Sock()

    monkeypatch.setattr(enrollment.ssl, "create_default_context", lambda: _Ctx())
    monkeypatch.setattr(
        enrollment.ssl, "create_connection",
        lambda addr, timeout=None: seen.append(addr) or object(),
    )

    enrollment._fetch_peer_cert("10.0.0.7", 6789, timeout=1.0)

    assert seen == [("10.0.0.7", 6789)]


def test_active_link_target_carries_resolved_port(db_session):
    """链路清单里的端点来自机器记录，不是全局默认。"""
    from ...extensions import session_scope
    from ...constant import MachineStatus

    machine = create_machine(machine_name="ep_target", machine_ip="10.0.0.7", machine_status=MachineStatus.ONLINE)
    with session_scope() as session:
        machine_repo.update_machine(machine.id, node_uid="uid-ep", port=6789, session=session)

    assert link.load_link_targets()[machine.id] == ("10.0.0.7", 6789, "uid-ep")


############################################################
# pin 键与端口解耦
############################################################

def test_pin_written_and_read_under_the_same_bare_host_key(monkeypatch, tmp_path):
    """写入侧与读取侧必须取同一个键，否则链路拒拨、HTTPS 静默降级 verify=False。"""
    from ...services.container_module.node_comms_modules import enrollment

    monkeypatch.setattr(transport, "PINNED_CERTS_DIR", str(tmp_path))
    monkeypatch.setattr(enrollment, "der_cert_to_pem", lambda der: b"pem-" + der)

    enrollment._persist_peer_pin("10.0.0.7:6789", b"der-cert")

    written = tmp_path / "10.0.0.7.pem"
    assert written.exists(), "pin 必须按裸 host 命名"
    # 读取侧（链路）按主机定位，命中同一文件
    seen = []
    monkeypatch.setattr(link, "_load_client_certificate", lambda: None)
    captured = {}

    class _Ctx:
        check_hostname = True
        verify_mode = None

        def load_cert_chain(self, certfile, keyfile):
            pass

    def _create(cafile=None):
        captured["cafile"] = cafile
        return _Ctx()

    monkeypatch.setattr(link.ssl, "create_default_context", _create)
    assert link.build_link_ssl_context("10.0.0.7") is not None
    assert captured["cafile"] == str(written)


def test_pin_survives_port_change(monkeypatch, tmp_path):
    """仅改端口、证书与主机不变 → 既有 pin 仍有效，无需重新建立信任。"""
    from ...services.container_module.node_comms_modules import enrollment

    monkeypatch.setattr(transport, "PINNED_CERTS_DIR", str(tmp_path))
    monkeypatch.setattr(enrollment, "der_cert_to_pem", lambda der: b"pem-" + der)
    enrollment._persist_peer_pin("10.0.0.7", b"der-cert")

    machine = create_machine(machine_name="ep_port_change", machine_ip="10.0.0.7")
    machine.port = 9999

    host, port = machine_endpoint(machine)

    assert (host, port) == ("10.0.0.7", 9999)
    assert (tmp_path / f"{host}.pem").exists(), "端口不参与 pin 键，换端口不该动 pin"


############################################################
# 建档与编辑：端口入参
############################################################

@pytest.mark.parametrize("value", [0, -1, 65536, "abc", 1.5, True])
def test_port_out_of_range_or_not_integer_is_rejected(value):
    from ...services.container_module.exceptions import NodeServiceError

    with pytest.raises(NodeServiceError) as exc:
        _validate_node_port(value)

    assert exc.value.reason == "invalid_node_port"


@pytest.mark.parametrize("value", [None, ""])
def test_empty_port_is_accepted_as_fallback(value):
    assert _validate_node_port(value) is None


@pytest.mark.parametrize("value", [1, 5789, 65535, "6789"])
def test_valid_port_is_normalised_to_int(value):
    assert _validate_node_port(value) == int(value)


def test_register_rejects_address_carrying_port(db_session):
    """地址是纯 IPv4，端口走独立字段。"""
    from ...services.container_module.exceptions import NodeServiceError

    with pytest.raises(NodeServiceError) as exc:
        machine_tasks.Register_machine("ep_bad_ip", "10.0.0.7:6789")

    assert exc.value.reason == "invalid_machine_ip"
    assert machine_repo.get_by_name("ep_bad_ip", session=db_session) is None


def test_register_blank_port_falls_back_and_stores_null(db_session, monkeypatch):
    """留空建档 → 记录里是 NULL（回落全局），**不**把当时的默认值固化进去。"""
    monkeypatch.setattr(CommsConfig, "NODE_PORT", 5789)
    machine_tasks._get_enrollment_client_cert = lambda: None
    monkeypatch.setattr(machine_tasks, "_get_enrollment_client_cert", lambda: None)
    monkeypatch.setattr(machine_tasks, "_fetch_peer_cert", lambda host, port, timeout: ("fp", b"der"))
    monkeypatch.setattr(machine_tasks, "_request_enrollment_profile", lambda *a, **k: {"gpu": []})
    monkeypatch.setattr(machine_tasks, "_issue_node_uid", lambda *a, **k: None)
    monkeypatch.setattr(machine_tasks, "_persist_peer_pin", lambda *a, **k: None)

    machine_tasks.Register_machine("ep_blank_port", "10.0.0.7")

    machine = machine_repo.get_by_name("ep_blank_port", session=db_session)
    assert machine.port is None
    assert machine_endpoint(machine) == ("10.0.0.7", 5789)


def test_register_with_explicit_port_persists_it(db_session, monkeypatch):
    monkeypatch.setattr(machine_tasks, "_get_enrollment_client_cert", lambda: None)
    seen = []
    monkeypatch.setattr(
        machine_tasks, "_fetch_peer_cert",
        lambda host, port, timeout: seen.append((host, port)) or ("fp", b"der"),
    )
    monkeypatch.setattr(machine_tasks, "_request_enrollment_profile", lambda *a, **k: {"gpu": []})
    monkeypatch.setattr(machine_tasks, "_issue_node_uid", lambda *a, **k: None)
    monkeypatch.setattr(machine_tasks, "_persist_peer_pin", lambda *a, **k: None)

    machine_tasks.Register_machine("ep_explicit_port", "10.0.0.7", port=6789)

    assert seen == [("10.0.0.7", 6789)], "建档时的取证必须走显式端口"
    machine = machine_repo.get_by_name("ep_explicit_port", session=db_session)
    assert machine.port == 6789
    assert machine_endpoint(machine) == ("10.0.0.7", 6789)
