"""Ctrl↔Node 链路测试共享基础设施。

- `node_server`：在进程内线程里拉起真实的 Node Flask 应用（FakeDockerClient + stub 服务层），
  返回可直连的 base_url。不依赖外部端口与 docker daemon。
- `node_transport`：链路测试统一走 transport 抽象，WSS 迁移后只换实现。

注意：链路测试都标记 integration（默认集排除），mock_external_services 对
integration 测试自动放行真实 requests.post —— 进程内 HTTP 是真实 socket 通信。
"""
import sys
import threading
from pathlib import Path

import pytest

NODE_ROOT = Path(__file__).resolve().parents[3] / "FuxiYu_NodeKernel"

if str(NODE_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(NODE_ROOT.parent))

node_pkg = pytest.importorskip("FuxiYu_NodeKernel", reason="NodeKernel 仓库不在本机，跳过链路测试")

from FuxiYu_NodeKernel import create_app as node_create_app  # noqa: E402
from FuxiYu_NodeKernel import extensions as node_ext  # noqa: E402
from FuxiYu_NodeKernel.utils.CheckKeys import KeyConfig  # noqa: E402


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
    """进程内 Node 服务（真实 Flask 栈 + 真实密钥 + 假 docker）。"""
    from werkzeug.serving import make_server

    patcher = _Patcher()
    patcher.setattr(KeyConfig, "PRIVATE_KEY_PATH", str(NODE_ROOT / "private_A.pem"))
    patcher.setattr(KeyConfig, "PUBLIC_KEY_PATH", str(NODE_ROOT / "public_A.pem"))
    patcher.setattr(KeyConfig, "PUBLIC_KEY_CONTROL", str(NODE_ROOT / "public_A.pem"))

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

    app = node_create_app()
    app.config.update(TESTING=True)

    server = make_server("127.0.0.1", 0, app)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    patcher.restore()


@pytest.fixture(scope="module")
def node_transport(node_server):
    from .transport import HttpNodeLinkTransport

    return HttpNodeLinkTransport(node_server)
