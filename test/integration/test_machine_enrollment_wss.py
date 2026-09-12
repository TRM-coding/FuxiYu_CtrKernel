"""Ctrl ↔ Node 真实链路集成测试。

拆成两层：
1. register_machine 闭环：真实 Node HTTPS identity 端点 + TOFU pin + 建档。
2. 链路闭环：真实 Node HTTPS/WSS 服务 + Ctrl 主动拨入 + snapshot_batch 落库。
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
import uvicorn

from FuxiYu_CtrKernel import create_app
from FuxiYu_CtrKernel.config import CommsConfig
from FuxiYu_CtrKernel.constant import ContainerStatus, MachineTypes
from FuxiYu_CtrKernel.extensions import session_scope
from FuxiYu_CtrKernel.repositories import containers_repo, machine_repo
from FuxiYu_CtrKernel.services import machine_tasks
from FuxiYu_CtrKernel.services.container_module import node_comms
from FuxiYu_CtrKernel.services.container_module.node_comms_modules import link, transport
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
        class _Server(uvicorn.Server):
            def install_signal_handlers(self):
                pass

        self.server = _Server(config)
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        try:
            self.server.run()
        except Exception as e:
            if e.__class__.__name__ == "InvalidState" and "connection is closing" in str(e):
                logging.getLogger(__name__).debug("test server ignored websocket close race: %s", e)
                return
            raise

    def start(self, port: int):
        self.thread.start()
        _wait_port(port)
        return self

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            logging.getLogger(__name__).warning("test server thread did not exit cleanly")


@contextmanager
def _node_https_server(tmp_path: Path, port: int, ctrl_ca_file: Path):
    """真实 Node 服务：HTTPS 操作通道与 /ws/ctrl 快照端点共用同一监听与证书。"""

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


def test_register_machine_builds_record_and_pin(app, tmp_path, monkeypatch):
    ctrl_certs_dir = tmp_path / "ctrl-certs"
    pin_dir = tmp_path / "pinned"
    port = _free_port()

    monkeypatch.setenv("CTRL_CERTS_DIR", str(ctrl_certs_dir))
    monkeypatch.setattr(transport, "PINNED_CERTS_DIR", str(pin_dir))
    monkeypatch.setattr(CommsConfig, "NODE_PORT", port)
    monkeypatch.setattr(CommsConfig, "NODE_URL_MIDDLE", f":{port}/api")
    ctrl_certs = ensure_ctrl_certificates()

    with _node_https_server(tmp_path, port, ctrl_certs.ca_cert):
        result = machine_tasks.Register_machine(
            machine_name="node-it-01",
            machine_ip="127.0.0.1",
            machine_description="integration node",
            timeout=5.0,
        )

        with session_scope(commit=False) as session:
            machine = machine_repo.get_by_id(result["machine_id"], session=session)
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

        status = node_comms.send(
            node_comms.get_full_url("127.0.0.1", "/machine_status"),
            {"config": {}},
            timeout=5.0,
        )
        assert status["success"] == 1
        assert status["machine_status"] == "online"

    # 建档即完成接入：pin 落盘供链路取信任锚，注册流程不再触发任何重载动作
    assert (pin_dir / "127.0.0.1.pem").exists()
    assert "wss_reload_required" not in result
    assert "wss_restart_requested" not in result


def test_ctrl_link_dials_node_and_applies_snapshot(app, tmp_path, monkeypatch):
    """换向闭环：Ctrl 主动拨 Node 的 /ws/ctrl，快照经链路落库。"""

    from FuxiYu_NodeKernel.network import wss as node_wss

    test_db = tmp_path / "ctrl-link.sqlite"
    create_app(
        overrides={
            **TEST_CONFIG_OVERRIDES,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{test_db}",
        }
    )

    ctrl_certs_dir = tmp_path / "ctrl-link-certs"
    pin_dir = tmp_path / "ctrl-link-pinned"
    monkeypatch.setenv("CTRL_CERTS_DIR", str(ctrl_certs_dir))
    monkeypatch.setattr(transport, "PINNED_CERTS_DIR", str(pin_dir))
    ctrl_certs = ensure_ctrl_certificates()

    port = _free_port()
    monkeypatch.setattr(CommsConfig, "NODE_PORT", port)

    uid = "ctrl-link-node-uid"
    monkeypatch.setattr(node_wss, "list_container_status", lambda: {"link_it_c": {"status": "offline"}})
    monkeypatch.setattr(node_wss, "list_last_ssh", lambda: {})
    monkeypatch.setattr(node_wss, "list_disk_usage", lambda: {"containers": {}})
    monkeypatch.setattr(node_wss, "list_sys_snapshot", lambda: dict(HARDWARE))

    with _node_https_server(tmp_path, port, ctrl_certs.ca_cert) as node_files:
        # Ctrl 侧建档 + pin（等价 register_machine 的第 6/7 步）
        machine = create_machine(
            machine_name="ctrl-link-machine",
            machine_ip="127.0.0.1",
            machine_type=MachineTypes.GPU,
            cpu_core_number=8,
            gpu_number=0,
            memory_size_gb=32,
            disk_size_gb=200,
        )
        with session_scope() as session:
            machine_repo.update_machine(
                machine.id,
                node_uid=uid,
                node_cert_fingerprint=certificate_sha256_fingerprint(node_files["cert"]),
                session=session,
            )
        container = create_container(machine=machine, name="link_it_c", status=ContainerStatus.ONLINE)
        machine_id, container_id = machine.id, container.id

        # Node 侧发牌：链路端点以本机身份牌校验 Ctrl 出示的 uid
        node_wss.save_ctrl_issued_uid(uid)
        pin_dir.mkdir(parents=True, exist_ok=True)
        (pin_dir / "127.0.0.1.pem").write_bytes(node_files["cert"].read_bytes())

        async def _run_link():
            task = asyncio.create_task(link.run_machine_link(machine_id, "127.0.0.1", uid))
            try:
                for _ in range(200):
                    await asyncio.sleep(0.05)
                    with session_scope(commit=False) as session:
                        current = containers_repo.get_by_id(container_id, session=session)
                    if current is not None and current.container_status == ContainerStatus.OFFLINE:
                        return
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise AssertionError("snapshot never landed through the Ctrl-initiated link")

        asyncio.run(_run_link())

    with session_scope(commit=False) as session:
        refreshed = machine_repo.get_by_id(machine_id, session=session)
        assert refreshed is not None
        # 连接成功 → 链路把机器置 ONLINE（拨号结果即状态）
        from FuxiYu_CtrKernel.constant import MachineStatus

        assert refreshed.machine_status == MachineStatus.ONLINE
