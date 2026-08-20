"""Node 加入 Ctrl 的真实链路集成测试。

拆成两层：
1. register_machine 闭环：真实 Node HTTPS identity 端点 + TOFU pin + 建档 + WSS reload marker。
2. WSS 推送闭环：真实 Ctrl WSS TLS 服务 + Node 客户端证书 + snapshot_batch 落库。
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import ssl
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI, WebSocket

from FuxiYu_CtrKernel import create_app
from FuxiYu_CtrKernel.config import CommsConfig
from FuxiYu_CtrKernel.constant import ContainerStatus, MachineTypes
from FuxiYu_CtrKernel.extensions import db
from FuxiYu_CtrKernel.models.machine import Machine
from FuxiYu_CtrKernel.repositories import machine_repo
from FuxiYu_CtrKernel.services.container_module import node_comms
from FuxiYu_CtrKernel.test.factories import create_container, create_machine
from FuxiYu_CtrKernel.test.conftest import TEST_CONFIG_OVERRIDES
from FuxiYu_CtrKernel.utils.cert_utils import certificate_sha256_fingerprint, ensure_ctrl_certificates

NODE_ROOT = Path(__file__).resolve().parents[3] / "FuxiYu_NodeKernel"
if str(NODE_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(NODE_ROOT.parent))

node_pkg = pytest.importorskip("FuxiYu_NodeKernel", reason="NodeKernel 仓库不在本机")

pytestmark = pytest.mark.integration


HARDWARE = {
    "hostname": "node-it-01",
    "platform": "Linux-test",
    "cpu": {"cores": 8, "usage_percent": 12.5},
    "memory": {"total_gb": 32, "used_gb": 4, "usage_percent": 12.5},
    "gpu": [{"index": 0, "vendor": "nvidia", "name": "RTX 4090", "memory_gb": 24}],
    "disk": {"total_gb": 200, "used_gb": 20, "free_gb": 180, "percent": 10.0},
    "collected_at": "2026-08-21T10:00:00",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_port(port: int, *, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"server on port {port} did not start")


@contextmanager
def _patched_env(values: dict[str, str]):
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _ThreadedServer:
    def __init__(self, config):
        import uvicorn

        class _Server(uvicorn.Server):
            def install_signal_handlers(self):
                pass

        self.server = _Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, port: int):
        self.thread.start()
        _wait_port(port)
        return self

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@contextmanager
def _node_https_server(tmp_path: Path, port: int, ctrl_ca_file: Path):
    import uvicorn
    from FuxiYu_NodeKernel import create_app as node_create_app
    from FuxiYu_NodeKernel.network import wss as node_wss

    node_cert = tmp_path / "node" / "node_cert.pem"
    node_key = tmp_path / "node" / "node_key.pem"
    identity_file = tmp_path / "node" / "identity.json"

    with _patched_env(
        {
            "NODE_TLS_CERT_FILE": str(node_cert),
            "NODE_TLS_KEY_FILE": str(node_key),
            "NODE_IDENTITY_FILE": str(identity_file),
            "NODE_CTRL_CA_FILE": str(ctrl_ca_file),
            "NODE_WSS_ENABLED": "0",
        }
    ):
        original_static = node_wss.static_sys_snapshot
        node_wss.static_sys_snapshot = lambda: dict(HARDWARE)
        try:
            certs = node_wss.ensure_self_signed_certificate()
            config = uvicorn.Config(
                node_create_app(),
                host="127.0.0.1",
                port=port,
                log_level="warning",
                lifespan="off",
                ssl_certfile=str(certs.cert_file),
                ssl_keyfile=str(certs.key_file),
                ssl_ca_certs=str(ctrl_ca_file),
                ssl_cert_reqs=ssl.CERT_REQUIRED,
            )
            server = _ThreadedServer(config).start(port)
            try:
                yield {"cert": certs.cert_file, "key": certs.key_file, "identity": identity_file}
            finally:
                server.stop()
        finally:
            node_wss.static_sys_snapshot = original_static


def test_register_machine_builds_record_pin_chain_and_wss_reload_request(app, tmp_path, monkeypatch):
    ctrl_certs_dir = tmp_path / "ctrl-certs"
    pin_dir = tmp_path / "pinned"
    marker = pin_dir / "_wss_reload_requested"
    port = _free_port()

    monkeypatch.setenv("CTRL_CERTS_DIR", str(ctrl_certs_dir))
    monkeypatch.setattr(node_comms, "PINNED_CERTS_DIR", str(pin_dir))
    monkeypatch.setattr(node_comms, "WSS_RELOAD_MARKER", str(marker))
    monkeypatch.setattr(CommsConfig, "NODE_PORT", port)
    monkeypatch.setattr(CommsConfig, "NODE_URL_MIDDLE", f":{port}/api")
    ctrl_certs = ensure_ctrl_certificates()

    with _node_https_server(tmp_path, port, ctrl_certs.ca_cert):
        with app.app_context():
            result = node_comms.register_machine(
                machine_name="node-it-01",
                machine_ip="127.0.0.1",
                machine_description="integration node",
                timeout=5.0,
            )

            machine = Machine.query.get(result["machine_id"])
            assert machine is not None
            assert machine.machine_type == MachineTypes.GPU
            assert machine.cpu_core_number == 8
            assert machine.memory_size_gb == 32
            assert machine.disk_size_gb == 200
            assert machine.gpu_number == 1
            assert machine.max_cpu_core_number == 4
            assert machine.max_memory_gb == 16
            assert machine.node_uid == result["uid"]
            assert machine.node_cert_fingerprint == result["certificate_fingerprint"]
            assert machine.cert_pinned_at is not None

    pin_file = pin_dir / "127.0.0.1.pem"
    chain_file = pin_dir / "_chain_bundle.pem"
    assert pin_file.exists()
    assert chain_file.exists()
    assert pin_file.read_bytes() in chain_file.read_bytes()
    assert marker.exists()
    assert result["wss_reload_required"] is True
    assert result["wss_restart_requested"] is True


@contextmanager
def _ctrl_wss_server(app, tmp_path: Path, node_cert: Path, port: int, monkeypatch):
    import uvicorn
    from FuxiYu_CtrKernel.services.container_module.node_comms import handle_node_ws
    from FuxiYu_CtrKernel.services.container_module.node_comms import rebuild_pinned_chain

    ctrl_certs_dir = tmp_path / "ctrl-wss-certs"
    pin_dir = tmp_path / "ctrl-wss-pinned"
    pin_dir.mkdir(parents=True, exist_ok=True)
    (pin_dir / "node.pem").write_bytes(node_cert.read_bytes())

    monkeypatch.setenv("CTRL_CERTS_DIR", str(ctrl_certs_dir))
    monkeypatch.setattr(node_comms, "PINNED_CERTS_DIR", str(pin_dir))
    ctrl_certs = ensure_ctrl_certificates()

    wss_app = FastAPI(title="FuxiYu CtrlKernel WSS Receiver Test")

    @wss_app.websocket("/ws/node")
    async def ws_node(websocket: WebSocket):
        with app.app_context():
            uid = websocket.query_params.get("uid")
            if uid and machine_repo.get_by_uid(uid) is None:
                logging.getLogger(__name__).error("test WSS cannot resolve uid %s", uid)
            await handle_node_ws(websocket)

    chain = rebuild_pinned_chain()
    config = uvicorn.Config(
        wss_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="off",
        ssl_certfile=str(ctrl_certs.cert_file),
        ssl_keyfile=str(ctrl_certs.key_file),
        ssl_ca_certs=str(chain),
        ssl_cert_reqs=ssl.CERT_REQUIRED,
    )
    server = _ThreadedServer(config).start(port)
    try:
        yield ctrl_certs
    finally:
        server.stop()


async def _send_wss_snapshot(port: int, uid: str, node_cert: Path, node_key: Path, ctrl_ca_file: Path):
    import websockets

    context = ssl.create_default_context(cafile=str(ctrl_ca_file))
    context.load_cert_chain(certfile=str(node_cert), keyfile=str(node_key))
    async with websockets.connect(f"wss://127.0.0.1:{port}/ws/node?uid={uid}", ssl=context) as websocket:
        await websocket.send(
            """
            {
              "type": "snapshot_batch",
              "node_uid": "%s",
              "payload": [
                {
                  "type": "snapshot",
                  "topic": "container_status",
                  "payload": {"wss_it_c": {"status": "offline"}}
                },
                {
                  "type": "snapshot",
                  "topic": "sys_snapshot",
                  "payload": {
                    "hostname": "node-it-01",
                    "cpu": {"cores": 8, "usage_percent": 10},
                    "memory": {"total_gb": 32, "used_gb": 5, "usage_percent": 15.6},
                    "disk": {"total_gb": 200, "used_gb": 50, "percent": 25},
                    "gpu": []
                  }
                }
              ]
            }
            """
            % uid
        )
        await asyncio.sleep(0.2)


def test_ctrl_wss_accepts_pinned_node_certificate_and_applies_snapshot(app, tmp_path, monkeypatch):
    from FuxiYu_NodeKernel.network import wss as node_wss

    test_db = tmp_path / "ctrl-wss.sqlite"
    fastapi_app = create_app(
        overrides={
            **TEST_CONFIG_OVERRIDES,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{test_db}",
        }
    )
    flask_app = fastapi_app.state.flask_app

    node_cert = tmp_path / "wss-node" / "node_cert.pem"
    node_key = tmp_path / "wss-node" / "node_key.pem"
    monkeypatch.setenv("NODE_TLS_CERT_FILE", str(node_cert))
    monkeypatch.setenv("NODE_TLS_KEY_FILE", str(node_key))
    node_files = node_wss.ensure_self_signed_certificate()

    port = _free_port()
    uid = "integration-node-uid"
    with flask_app.app_context():
        db.create_all()
        machine = create_machine(
            machine_name="wss-it-machine",
            machine_ip="127.0.0.1",
            machine_type=MachineTypes.GPU,
            cpu_core_number=8,
            gpu_number=0,
            memory_size_gb=32,
            disk_size_gb=200,
        )
        machine_repo.update_machine(
            machine.id,
            node_uid=uid,
            node_cert_fingerprint=certificate_sha256_fingerprint(node_files.cert_file),
        )
        container = create_container(machine=machine, name="wss_it_c", status=ContainerStatus.ONLINE)
        machine_id = machine.id
        container_id = container.id

    with _ctrl_wss_server(flask_app, tmp_path, node_files.cert_file, port, monkeypatch) as ctrl_certs:
        asyncio.run(_send_wss_snapshot(port, uid, node_files.cert_file, node_files.key_file, ctrl_certs.ca_cert))

    with flask_app.app_context():
        db.session.expire_all()
        refreshed = machine_repo.get_by_id(machine_id)
        refreshed_container = db.session.get(type(container), container_id)
        assert refreshed is not None
        assert refreshed_container is not None
        assert refreshed_container.container_status == ContainerStatus.OFFLINE
