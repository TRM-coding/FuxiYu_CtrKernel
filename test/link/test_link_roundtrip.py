"""Ctrl ↔ Node 真实链路 roundtrip 测试（integration）。

链路：Ctrl CheckKeys 加密+签名 → 真实 HTTP（进程内 Node Flask 服务）
     → Node 验签+解密 → 服务层（stub）→ 响应 → Ctrl 解析。

WSS 迁移约定：本文件的断言只依赖 transport 抽象（test/link/transport.py），
迁移时新增 WssNodeLinkTransport 实现，本文件不用改。

运行：WSL 下 `pytest test/link -m integration`；默认集排除（需要跨仓库）。
"""
import time
from pathlib import Path

import pytest

from FuxiYu_CtrKernel.utils.CheckKeys import KeyConfig as CtrlKeyConfig

from .conftest import NODE_ROOT, node_pkg  # noqa: F401  (导入 conftest 以完成跨仓库准备)

pytestmark = pytest.mark.integration

CTRL_ROOT = Path(__file__).resolve().parents[2]

node_blueprints = node_pkg.blueprints


@pytest.fixture()
def ctrl_key_paths(monkeypatch):
    monkeypatch.setattr(CtrlKeyConfig, "PRIVATE_KEY_PATH", str(CTRL_ROOT / "private_A.pem"))
    monkeypatch.setattr(CtrlKeyConfig, "PUBLIC_KEY_PATH", str(CTRL_ROOT / "public_A.pem"))


VALID_CFG = {
    "gpu_list": [],
    "cpu_number": 2,
    "memory": 4,
    "shared_memory": 0,
    "name": "link_c",
    "port": 2233,
    "image": "ubuntu:22.04",
}


def test_create_container_roundtrip(ctrl_key_paths, node_transport, monkeypatch):
    """真实方向：Ctrl 构造创建指令 → Node 验签解密 → stub 服务层 → 响应。"""
    calls = []

    def _stub(owner_name, cfg, public_key=None):
        calls.append((owner_name, cfg.name, public_key))
        return node_pkg.services.container_service.CreateContainerReturn("cid123", cfg.name)

    monkeypatch.setattr(node_blueprints, "create_container", _stub)

    payload = {"owner_name": "admin", "config": VALID_CFG}
    res = node_transport.post("/api/create_container", payload)

    assert res.get("success") == 1
    assert res.get("container_status") == "creating"
    assert res.get("container_name") == "link_c"
    time.sleep(0.1)  # 等 Node 端后台线程调用 stub
    assert len(calls) == 1
    assert calls[0] == ("admin", "link_c", None)


def test_invalid_signature_rejected_by_node(ctrl_key_paths, node_transport, monkeypatch):
    """链路级安全断言：错误签名在 Node 端被拒（401），不触达服务层。"""
    calls = []

    monkeypatch.setattr(node_blueprints, "create_container", lambda *a, **k: calls.append(a) or True)

    import base64

    from FuxiYu_CtrKernel.services import container_tasks

    # 用 Ctrl 的 send 发一个签名伪造的请求（真实 wire 格式 + 假签名）
    res = container_tasks.send(
        b"not-encrypted",
        base64.b64decode(base64.b64encode(b"x" * 256)),
        _node_base_url(node_transport) + "/api/create_container",
    )
    assert res.get("error_reason") == "invalid_signature"
    assert calls == []


def test_add_collaborator_roundtrip_echo(ctrl_key_paths, node_transport, monkeypatch):
    """消息层闭环锚点：Node 回显 decrypted_message == Ctrl 发送的原始 dict。"""
    monkeypatch.setattr(node_blueprints, "add_collaborator", lambda *a: True)

    payload = {"config": {"container_name": "link_c", "user_name": "u1", "role": "admin"}}
    res = node_transport.post("/api/add_collaborator", payload)

    assert res.get("success") is True
    assert res.get("decrypted_message") == payload


def test_container_status_roundtrip(ctrl_key_paths, node_transport, monkeypatch):
    """真实链路下 container_status 的 online 判定（fake 容器 + exec 成功 → online）。"""
    from FuxiYu_NodeKernel import extensions as node_ext

    class _Running:
        def __init__(self):
            self.name = "link_c"
            self.attrs = {"State": {"Status": "running"}}

        def exec_run(self, *a, **k):
            class _R:
                exit_code = 0

                # 生产代码 getattr(r, 'exit_code', r[0]) 会急切求值 r[0]，必须支持下标
                def __getitem__(self, idx):
                    if idx == 0:
                        return self.exit_code
                    raise IndexError(idx)

            return _R()

    class _FakeContainers:
        def get(self, name_or_id):
            return _Running()

    class _FakeDocker:
        def __init__(self):
            self.containers = _FakeContainers()

    monkeypatch.setattr(node_ext, "docker_client", _FakeDocker())

    payload = {"config": {"container_name": "link_c"}}
    res = node_transport.post("/api/container_status", payload)

    assert res.get("success") == 1
    assert res.get("container_status") == "online"


def _node_base_url(transport) -> str:
    return transport.base_url
