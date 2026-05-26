import pytest

from ...repositories import container_ssh_login_repo
from ...services import container_tasks
from .conftest import NODE_ENDPOINT_404_HTML, NODE_LAST_SSH_FOUND, NODE_LAST_SSH_NOT_FOUND


def test_get_last_ssh_time_success_persists_record(
    db_session,
    container_graph,
    mock_node_send,
    mock_crypto,
):
    _root, machine, container = container_graph
    mock_node_send(NODE_LAST_SSH_FOUND)

    last_time = container_tasks.get_container_last_ssh_login_time(container.id)

    assert last_time == NODE_LAST_SSH_FOUND["last_ssh_connect_time"]
    record = container_ssh_login_repo.get_by_machine_container(machine.id, container.id)
    assert record.last_ssh_login_time == last_time


def test_get_last_ssh_time_not_found_persists_none(
    db_session,
    container_graph,
    mock_node_send,
    mock_crypto,
):
    _root, machine, container = container_graph
    mock_node_send(NODE_LAST_SSH_NOT_FOUND)

    last_time = container_tasks.get_container_last_ssh_login_time(container.id)

    assert last_time is None
    record = container_ssh_login_repo.get_by_machine_container(machine.id, container.id)
    assert record.last_ssh_login_time is None


def test_get_last_ssh_time_endpoint_404_raises_node_endpoint_not_found(
    db_session,
    container_graph,
    mock_node_send,
    mock_crypto,
):
    _root, _machine, container = container_graph
    mock_node_send(NODE_ENDPOINT_404_HTML)

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.get_container_last_ssh_login_time(container.id)

    assert excinfo.value.reason == "node_endpoint_not_found"


def test_get_last_ssh_time_invalid_container_id_returns_none(db_session):
    assert container_tasks.get_container_last_ssh_login_time("bad") is None
    assert container_tasks.get_container_last_ssh_login_time(999999) is None
