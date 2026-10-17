"""Ctrl↔Node 链路测试共享基础设施。

- `node_server`：在进程内线程里拉起真实的 Node FastAPI 应用（FakeDockerClient + stub 服务层），
  返回可直连的 base_url。不依赖外部端口与 docker daemon。
- `node_transport`：链路测试统一走 transport 抽象，WSS 迁移后只换实现。

注意：链路测试都标记 integration（默认集排除），mock_external_services 对
integration 测试自动放行真实 requests.post —— 进程内 HTTP 是真实 socket 通信。
"""
import sys
import threading
import time
from pathlib import Path

import pytest

NODE_ROOT = Path(__file__).resolve().parents[3] / "FuxiYu_NodeKernel"

if str(NODE_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(NODE_ROOT.parent))

node_pkg = pytest.importorskip("FuxiYu_NodeKernel", reason="NodeKernel 仓库不在本机，跳过链路测试")

from FuxiYu_NodeKernel import create_app as node_create_app  # noqa: E402
from FuxiYu_NodeKernel import extensions as node_ext  # noqa: E402


class _Patcher:
    """module 级手动 patch（pytest 无 module 级 monkeypatch 内置 fixture）。"""

    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name, None)))
        setattr(obj, name, value)

    def restore(self):
        for obj, name, old in reversed(self._undo):
            if old is None:
                try:
                    delattr(obj, name)
                except AttributeError:
                    pass
            else:
                setattr(obj, name, old)


@pytest.fixture(scope="module")
def node_server():
    """进程内 Node 服务（真实 FastAPI + uvicorn + 假 docker）。

    check_keys 已退役：Node 端点直接收明文 JSON（TLS 承担身份，链路测试内用 http）。
    """
    import uvicorn

    patcher = _Patcher()

    # 假 docker client：Node 端点会直接访问 extensions.docker_client
    import docker as docker_pkg

    class _FakeContainers:
        def get(self, name_or_id):
            class _Resp:
                status_code = 404
                content = b"not found"
                url = "http://docker/containers/ghost"
                reason = "Not Found"

            raise docker_pkg.errors.NotFound("no such container", response=_Resp())

    class _FakeDocker:
        def __init__(self):
            self.containers = _FakeContainers()

    patcher.setattr(node_ext, "docker_client", _FakeDocker())

    class _Server(uvicorn.Server):
        def install_signal_handlers(self):
            pass  # 线程内不允许信号处理

    port = 5788
    server = _Server(uvicorn.Config(node_create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # 等待端口就绪
    import socket

    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    patcher.restore()


@pytest.fixture(scope="module")
def node_transport(node_server):
    from .transport import HttpNodeLinkTransport

    return HttpNodeLinkTransport(node_server)
