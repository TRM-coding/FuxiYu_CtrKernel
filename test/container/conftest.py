import json

import pytest

from ...constant import ContainerStatus, MachineStatus, ROLE
from ...utils.Container import Container_info
from ..factories import create_container_graph, create_user


TEST_CONTAINER_NAME = "test_container_1"
TEST_CONTAINER_IMAGE = "ubuntu:22.04"
TEST_CONTAINER_PORT = 22001
TEST_MACHINE_IP = "127.0.0.1"
VALID_PUBLIC_KEY = "ssh-rsa AAAATEST"
NODE_SUCCESS_TRUE = {"success": 1}
NODE_SUCCESS_BOOL = {"success": True}
NODE_REMOVE_SUCCESS = {"success": 0}
NODE_REMOVE_NOT_FOUND = {"success": 1}
NODE_REMOVE_FAILED = {"success": 2, "error_reason": "remove_failed"}
NODE_STATUS_ONLINE = {"success": 1, "container_status": "online"}
NODE_STATUS_OFFLINE = {"success": 1, "container_status": "offline"}
NODE_STATUS_404 = {"status_code": 404, "error": "not found", "text": "not found"}
NODE_ENDPOINT_404_HTML = {"status_code": 404, "text": "<!doctype html> not found"}
NODE_LAST_SSH_FOUND = {"success": 1, "last_ssh_connect_time": "2026-05-25T10:00:00"}
NODE_LAST_SSH_NOT_FOUND = {"success": 0, "error_reason": "not_found"}


@pytest.fixture(autouse=True)
def mock_container_machine_online(monkeypatch):
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.container_module.node_comms.is_machine_online_remote",
        lambda machine_id: True,
    )


@pytest.fixture()
def container_info():
    return Container_info(
        gpu_list=[],
        cpu_number=2,
        memory=8,
        shared_memory=2,
        name=TEST_CONTAINER_NAME,
        image=TEST_CONTAINER_IMAGE,
    )


@pytest.fixture()
def container_graph(db_session):
    return create_container_graph()


@pytest.fixture()
def container_graph_with_collaborator(db_session):
    collaborator = create_user()
    root, machine, container = create_container_graph(
        collaborator_user=collaborator,
        collaborator_username=collaborator.username,
    )
    return root, collaborator, machine, container


@pytest.fixture()
def mock_node_send(monkeypatch):
    calls = []

    def _install(response):
        calls.clear()

        def _send(url, payload, timeout=5.0):
            calls.append({
                "url": url,
                "payload": payload,
                "timeout": timeout,
            })
            return dict(response)

        monkeypatch.setattr("FuxiYu_CtrKernel.services.container_tasks.send", _send)
        return calls

    return _install


