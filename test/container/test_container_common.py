import pytest

from ...constant import ROLE
from ...services import container_tasks
from ..factories import bind_user_container, create_container, create_machine, create_user


def test_container_fixture_creates_root_binding(container_graph):
    root, _machine, container = container_graph

    bindings = container_tasks.get_container_bindings(container.id)

    assert bindings[0]["user_id"] == root.id
    assert getattr(bindings[0]["role"], "value", bindings[0]["role"]) == ROLE.ROOT.value


def test_node_send_mock_records_url_and_payload(mock_node_send):
    calls = mock_node_send({"success": 1})
    payload = {"config": {"container_name": "c1"}}

    res = container_tasks.send("http://127.0.0.1:5789/api/demo", payload, timeout=3)

    assert res == {"success": 1}
    assert calls[0]["url"].endswith("/demo")
    assert calls[0]["timeout"] == 3
    assert calls[0]["payload"]["config"]["container_name"] == "c1"


def test_default_container_tests_do_not_call_requests_post():
    with pytest.raises(AssertionError, match="Real HTTP requests are blocked"):
        container_tasks.requests.post("http://127.0.0.1")


def test_container_heartbeats_are_mocked_by_default(container_graph):
    _root, machine, container = container_graph

    thread = container_tasks.container_starting_status_heartbeat(
        machine.machine_ip,
        container.name,
        container_id=container.id,
    )

    assert thread.is_alive() is True


def test_machine_online_check_is_mocked_by_default(container_graph):
    from ...services.container_module import node_comms

    _root, machine, _container = container_graph

    assert node_comms.is_machine_online_remote(machine.id) is True
