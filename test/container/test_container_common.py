import pytest

from ...constant import ROLE, MachineStatus
from ...extensions import session_scope
from ...repositories import usercontainer_repo
from ...services import machine_tasks
from ...services.container_module import node_comms
from ..factories import bind_user_container, create_container, create_machine, create_user


def test_container_fixture_creates_root_binding(container_graph):
    root, _machine, container = container_graph

    with session_scope(commit=False) as session:
        bindings = usercontainer_repo.get_container_bindings(container.id, session=session)

    assert bindings[0]["user_id"] == root.id
    assert getattr(bindings[0]["role"], "value", bindings[0]["role"]) == ROLE.ROOT.value


def test_node_send_mock_records_url_and_payload(mock_node_send):
    calls = mock_node_send({"success": 1})
    payload = {"config": {"container_name": "c1"}}

    res = node_comms.send("http://127.0.0.1:5789/api/demo", payload, timeout=3)

    assert res == {"success": 1}
    assert calls[0]["url"].endswith("/demo")
    assert calls[0]["timeout"] == 3
    assert calls[0]["payload"]["config"]["container_name"] == "c1"


def test_default_container_tests_do_not_call_requests_post():
    # 经真实门户 send 断言安全网：conftest 的 requests.post 守卫抛 AssertionError，
    # 而 send 只捕 requests.RequestException → 必炸穿（测试不直接引入 requests 模块）
    with pytest.raises(AssertionError, match="Real HTTP requests are blocked"):
        node_comms.send("http://127.0.0.1", {"config": {}})


def test_machine_status_reads_persisted_state_only(container_graph):
    # 换向后机器在线状态只由链路连接结果写入；读面没有任何出站探活路径，
    # 这里钉住的是「读面不会反向驱动 machine_status」这一结构性事实。
    _root, machine, _container = container_graph
    machine.machine_status = MachineStatus.ONLINE

    assert machine_tasks.get_machine_reachable(machine.id) is True
