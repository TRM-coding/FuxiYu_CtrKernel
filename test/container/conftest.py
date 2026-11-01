import json

import pytest

from ...constant import ContainerStatus, MachineStatus, ROLE
from ...utils.Container import Container_info
from ..factories import create_container_graph, create_user


TEST_CONTAINER_NAME = "test_container_1"
TEST_CONTAINER_IMAGE = "ubuntu:22.04"
VALID_PUBLIC_KEY = "ssh-rsa AAAATEST"
NODE_SUCCESS_TRUE = {"success": 1}
# remove_container 的真实 wire（Node network/api.py）：docker 已删除 → 200 {"success": 1}；
# docker 中不存在 → HTTP 404 {"success": 0, error_reason: not_found}；删除失败 → HTTP 500 remove_failed
NODE_REMOVE_SUCCESS = {"success": 1}
NODE_REMOVE_NOT_FOUND = {"success": 0, "error": "container not found", "error_reason": "not_found", "status_code": 404}
NODE_REMOVE_FAILED = {"success": 0, "error": "failed to remove container", "error_reason": "remove_failed", "status_code": 500}
NODE_STATUS_ONLINE = {"success": 1, "container_status": "online"}
NODE_STATUS_OFFLINE = {"success": 1, "container_status": "offline"}
NODE_STATUS_404 = {"status_code": 404, "error": "not found", "text": "not found"}


def _mount_check_exists_response(payload):
    """Legacy tests configure a single generic Node reply; give the new action-time
    path probe a well-formed "path exists" answer so those tests still exercise the
    action under test. New tests that need a specific probe result install their own
    send handler instead of this fixture.
    """

    paths = ((payload or {}).get("config") or {}).get("mount_paths") or []
    return {
        "success": 1,
        "mounts": [
            {
                "path": path,
                "bytes": 0,
                "measured_at": "2026-01-01T00:00:00Z",
                "pending": False,
                "error": None,
            }
            for path in paths
        ],
    }


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
            if url.endswith("/check_mount_usage"):
                configured = response if isinstance(response, dict) else {}
                # 404/405 是“旧 Node 无接口”，坏的/显式的 mounts 形状也照原样返回；
                # 其余泛化成功/失败回复默认视为“路径存在”，让旧用例继续测动作本身。
                if "mounts" not in configured and configured.get("status_code") not in (404, 405):
                    return _mount_check_exists_response(payload)
            return dict(response)

        monkeypatch.setattr("FuxiYu_CtrKernel.services.container_module.node_comms.send", _send)
        return calls

    return _install


