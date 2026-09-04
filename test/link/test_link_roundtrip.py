"""Ctrl -> Node HTTP 链路集成测试。

这些用例拉起真实 Node FastAPI 服务，并通过 Ctrl 的 node_comms/send 路径
发起 HTTP 请求。测试重点是跨仓库 HTTP 协议、路由和响应契约；Docker 与宿主
目录副作用在 endpoint 绑定的服务函数处 stub 掉。
"""

import time

import pytest

from .conftest import NODE_ROOT, node_pkg  # noqa: F401

pytestmark = pytest.mark.integration

node_service = node_pkg.services.container_service
node_api = node_pkg.network.api


VALID_CFG = {
    "gpu_list": [],
    "cpu_number": 2,
    "memory": 4,
    "shared_memory": 0,
    "name": "link_c",
    "port": 2233,
    "image": "ubuntu:22.04",
}


def test_create_container_roundtrip(node_transport, monkeypatch):
    """Ctrl 构造创建指令，Node FastAPI 接收后进入创建服务函数。"""

    calls = []

    def _stub(owner_name, cfg, public_key=None):
        calls.append((owner_name, cfg.name, public_key))
        return node_service.CreateContainerReturn("cid123", cfg.name)

    monkeypatch.setattr(node_api, "create_container", _stub)

    payload = {"owner_name": "admin", "config": VALID_CFG}
    res = node_transport.post("/api/create_container", payload)

    assert res.get("success") == 1
    assert res.get("container_status") == "creating"
    assert res.get("container_name") == "link_c"
    time.sleep(0.1)
    assert calls == [("admin", "link_c", None)]


def test_add_collaborator_roundtrip_echo(node_transport, monkeypatch):
    """Node 响应应回显 Ctrl 发送的原始消息体。"""

    monkeypatch.setattr(node_api, "add_collaborator", lambda *args: True)

    payload = {"config": {"container_name": "link_c", "user_name": "u1", "role": "admin"}}
    res = node_transport.post("/api/add_collaborator", payload)

    assert res.get("success") is True
    assert res.get("decrypted_message") == payload


def test_container_status_roundtrip(node_transport, monkeypatch):
    """真实 HTTP 链路下读取 Node 的状态快照。"""

    monkeypatch.setattr(
        node_api,
        "list_container_status",
        lambda: {
            "link_c": {
                "status": "online",
                "source": "snapshot",
                "cache_updated_at": "2026-08-21T10:00:00",
            }
        },
    )

    payload = {"config": {"container_name": "link_c"}}
    res = node_transport.post("/api/container_status", payload)

    assert res.get("success") == 1
    assert res.get("container_status") == "online"
