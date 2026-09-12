"""Ctrl → Node 出站链路（node_comms_modules.link）函数级测试。

换向后数据通道由 Ctrl 主动拨 Node：machines 表即链路清单，连接成功即判
ONLINE、断开即判 OFFLINE，每台机器独立退避，集合变更由周期对齐跟随。
"""

import asyncio
import ssl

import pytest

from ...constant import MachineStatus
from ...extensions import session_scope
from ...repositories import machine_repo
from ...services.container_module.node_comms_modules import link
from ..factories import create_machine


def _recording_link(record):
    """可记录的链路替身：记下入参后长挂，直到被取消。"""

    async def _run(machine_id, machine_ip, uid):
        record.append((machine_id, machine_ip, uid))
        await asyncio.sleep(3600)

    return _run


def _cancel_all(tasks):
    for task in tasks.values():
        task.cancel()


############################################################
# URL 与 TLS 组装
############################################################

def test_link_url_composes_node_snapshot_endpoint():
    assert link.link_url("10.0.0.7", "uid-7") == "wss://10.0.0.7:5789/ws/ctrl?uid=uid-7"


def test_link_url_honours_explicit_port_in_machine_ip():
    assert link.link_url("10.0.0.7:6789", "uid-7") == "wss://10.0.0.7:6789/ws/ctrl?uid=uid-7"


def test_build_link_ssl_context_without_pin_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(link, "_pin_file", lambda host: tmp_path / f"{host}.pem")

    assert link.build_link_ssl_context("10.0.0.7") is None


def _recording_ssl_context(monkeypatch):
    """记录 cafile 的 SSLContext 替身，避免测试依赖真实证书字节。"""

    captured = {}

    class _Context:
        check_hostname = True
        verify_mode = None

        def load_cert_chain(self, certfile, keyfile):
            captured["client_cert"] = (certfile, keyfile)

    def _create(cafile=None):
        captured["cafile"] = cafile
        return _Context()

    monkeypatch.setattr(link.ssl, "create_default_context", _create)
    return captured


def test_build_link_ssl_context_trusts_machine_pin(monkeypatch, tmp_path):
    pin = tmp_path / "10.0.0.7.pem"
    pin.write_bytes(b"pinned node certificate")
    monkeypatch.setattr(link, "_pin_file", lambda host: tmp_path / f"{host}.pem")
    monkeypatch.setattr(link, "_load_client_certificate", lambda: None)
    captured = _recording_ssl_context(monkeypatch)

    context = link.build_link_ssl_context("10.0.0.7")

    assert context is not None
    assert captured["cafile"] == str(pin)  # 按机器 pin 作信任锚，不用共享 bundle
    # TOFU：pin 已把身份钉死，hostname 校验对新链路关闭（Node 证书 SAN 不含业务 IP）
    assert context.check_hostname is False
    assert context.verify_mode.name == "CERT_REQUIRED"


def test_build_link_ssl_context_loads_ctrl_client_certificate(monkeypatch, tmp_path):
    pin = tmp_path / "10.0.0.7.pem"
    pin.write_bytes(b"pinned node certificate")
    monkeypatch.setattr(link, "_pin_file", lambda host: tmp_path / f"{host}.pem")
    monkeypatch.setattr(link, "_load_client_certificate", lambda: ("ctrl.pem", "ctrl-key.pem"))
    captured = _recording_ssl_context(monkeypatch)

    assert link.build_link_ssl_context("10.0.0.7") is not None
    assert captured["client_cert"] == ("ctrl.pem", "ctrl-key.pem")


def test_build_link_ssl_context_keys_pin_by_bare_host(monkeypatch, tmp_path):
    """machine_ip 带端口时按裸主机取 pin——与操作通道 transport._resolve_tls 一致。"""
    seen = []
    pin = tmp_path / "10.0.0.7.pem"
    pin.write_bytes(b"pinned node certificate")
    monkeypatch.setattr(link, "_pin_file", lambda host: seen.append(host) or pin)
    monkeypatch.setattr(link, "_load_client_certificate", lambda: None)
    _recording_ssl_context(monkeypatch)

    assert link.build_link_ssl_context("10.0.0.7:6789") is not None
    assert seen == ["10.0.0.7"]


############################################################
# 目标集合解析
############################################################

def test_load_link_targets_includes_offline_machines(db_session):
    online = create_machine(machine_name="l_online", machine_status=MachineStatus.ONLINE)
    offline = create_machine(machine_name="l_offline", machine_status=MachineStatus.OFFLINE)
    with session_scope() as session:
        machine_repo.update_machine(online.id, node_uid="uid-online", session=session)
        machine_repo.update_machine(offline.id, node_uid="uid-offline", session=session)

    targets = link.load_link_targets()

    # OFFLINE 同样在清单内——这就是离线发现
    assert targets[online.id] == (online.machine_ip, "uid-online")
    assert targets[offline.id] == (offline.machine_ip, "uid-offline")


def test_load_link_targets_skips_machines_without_uid(db_session):
    enrolled = create_machine(machine_name="l_enrolled")
    pending = create_machine(machine_name="l_pending")
    with session_scope() as session:
        machine_repo.update_machine(enrolled.id, node_uid="uid-enrolled", session=session)

    targets = link.load_link_targets()

    assert enrolled.id in targets
    assert pending.id not in targets


def test_load_link_targets_pages_through_whole_table(monkeypatch, db_session):
    for idx in range(5):
        machine = create_machine(machine_name=f"l_page_{idx}")
        with session_scope() as session:
            machine_repo.update_machine(machine.id, node_uid=f"uid-page-{idx}", session=session)
    monkeypatch.setattr(link, "_MACHINE_PAGE_SIZE", 2)

    assert len(link.load_link_targets()) == 5


############################################################
# 集合对齐（差集动作，不打断存活链路）
############################################################

def test_sync_links_starts_link_for_new_machine(monkeypatch):
    async def _main():
        started = []
        monkeypatch.setattr(link, "load_link_targets", lambda: {7: ("10.0.0.7", "uid-7")})
        monkeypatch.setattr(link, "run_machine_link", _recording_link(started))
        tasks = {}

        link.sync_links(tasks)
        await asyncio.sleep(0.01)

        assert started == [(7, "10.0.0.7", "uid-7")]
        _cancel_all(tasks)
        await asyncio.gather(*tasks.values(), return_exceptions=True)

    asyncio.run(_main())


def test_sync_links_keeps_live_links_untouched(monkeypatch):
    """已存在且存活的链路绝不重连——重连会把 5s 一帧的数据通道打成筛子。"""

    async def _main():
        started = []
        monkeypatch.setattr(link, "load_link_targets", lambda: {7: ("10.0.0.7", "uid-7")})
        monkeypatch.setattr(link, "run_machine_link", _recording_link(started))
        tasks = {}

        link.sync_links(tasks)
        await asyncio.sleep(0.01)
        first = tasks[7]
        link.sync_links(tasks)

        assert tasks[7] is first
        assert len(started) == 1
        _cancel_all(tasks)
        await asyncio.gather(*tasks.values(), return_exceptions=True)

    asyncio.run(_main())


def test_sync_links_cancels_link_for_removed_machine(monkeypatch):
    async def _main():
        targets = {7: ("10.0.0.7", "uid-7")}
        monkeypatch.setattr(link, "load_link_targets", lambda: dict(targets))
        monkeypatch.setattr(link, "run_machine_link", _recording_link([]))
        tasks = {}

        link.sync_links(tasks)
        await asyncio.sleep(0.01)
        removed = tasks[7]

        targets.clear()
        link.sync_links(tasks)

        assert tasks == {}
        await asyncio.sleep(0.01)
        assert removed.cancelled()

    asyncio.run(_main())


def test_sync_links_restarts_dead_link(monkeypatch):
    async def _main():
        started = []
        monkeypatch.setattr(link, "load_link_targets", lambda: {7: ("10.0.0.7", "uid-7")})

        async def _dies(machine_id, machine_ip, uid):
            started.append(machine_id)

        monkeypatch.setattr(link, "run_machine_link", _dies)
        tasks = {}

        link.sync_links(tasks)
        await asyncio.gather(*tasks.values(), return_exceptions=True)  # 链路自行结束
        assert tasks[7].done()

        link.sync_links(tasks)
        await asyncio.sleep(0.01)

        assert len(started) == 2
        _cancel_all(tasks)
        await asyncio.gather(*tasks.values(), return_exceptions=True)

    asyncio.run(_main())


############################################################
# 常驻管理器
############################################################

def test_run_links_forever_seeds_windows_before_first_dial(monkeypatch):
    """顺序硬约束：窗口播种必须先于任何拨号。

    链路一连上就会写 ONLINE，而 refresh_unavailable_window 在「可用且窗口未开」
    时是空操作——播种若跑在其后，就会开出一个无人结算的窗口（无界多算）。
    这条锁的是顺序本身，不是播种函数。
    """

    async def _main():
        order = []
        monkeypatch.setattr(link, "LINK_SYNC_INTERVAL", 0.01)
        monkeypatch.setattr(
            link, "seed_unavailable_windows_from_last_seen",
            lambda: order.append("seed") or {"seeded": []},
        )
        monkeypatch.setattr(link, "load_link_targets", lambda: {})
        real_sync = link.sync_links

        def _sync(tasks):
            order.append("sync")
            real_sync(tasks)

        monkeypatch.setattr(link, "sync_links", _sync)

        manager = asyncio.create_task(link.run_links_forever())
        for _ in range(100):
            await asyncio.sleep(0.01)
            if len(order) >= 2:
                break
        manager.cancel()
        with pytest.raises(asyncio.CancelledError):
            await manager

        assert order[0] == "seed", f"播种没有抢在拨号之前: {order}"
        assert order[1] == "sync"

    asyncio.run(_main())


def test_run_links_forever_continues_when_seeding_fails(monkeypatch):
    """播种失败不该阻断链路：兜底没做成只是回到修复前的行为。"""

    async def _main():
        synced = []
        monkeypatch.setattr(link, "LINK_SYNC_INTERVAL", 0.01)
        monkeypatch.setattr(
            link, "seed_unavailable_windows_from_last_seen",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr(link, "load_link_targets", lambda: {})
        monkeypatch.setattr(link, "sync_links", lambda tasks: synced.append(1))

        manager = asyncio.create_task(link.run_links_forever())
        for _ in range(100):
            await asyncio.sleep(0.01)
            if synced:
                break
        manager.cancel()
        with pytest.raises(asyncio.CancelledError):
            await manager

        assert synced, "播种抛错后链路没有继续启动"

    asyncio.run(_main())


def test_run_links_forever_syncs_until_cancelled(monkeypatch):
    async def _main():
        started = []
        monkeypatch.setattr(link, "LINK_SYNC_INTERVAL", 0.01)
        monkeypatch.setattr(link, "load_link_targets", lambda: {7: ("10.0.0.7", "uid-7")})
        monkeypatch.setattr(link, "run_machine_link", _recording_link(started))

        manager = asyncio.create_task(link.run_links_forever())
        for _ in range(100):
            await asyncio.sleep(0.01)
            if started:
                break
        assert started == [(7, "10.0.0.7", "uid-7")]

        manager.cancel()
        with pytest.raises(asyncio.CancelledError):
            await manager

    asyncio.run(_main())


############################################################
# 故障诊断
############################################################

def test_describe_link_error_points_at_pin_when_local_rejects_peer(monkeypatch, tmp_path):
    """本端拒绝对端证书（pin 失效）→ 提示要指出 pin 路径与重登记出路。"""
    exc = ssl.SSLCertVerificationError(1, "certificate verify failed: self-signed certificate")
    monkeypatch.setattr(link, "_pin_file", lambda host: tmp_path / f"{host}.pem")

    text = link._describe_link_error(exc, "10.0.0.7")

    assert "SSLCertVerificationError" in text
    assert str(tmp_path / "10.0.0.7.pem") in text
    assert "pin" in text


def test_describe_link_error_flags_peer_rejecting_our_client_cert():
    """对端在 TLS 层关门 → 提示要指向 Ctrl 证书与 Node 侧信任锚。

    这一类在 str(exc) 里只剩一句泛化短语，是与「本端拒绝对端」最容易混淆的反向故障。
    """
    exc = _NamedError("InvalidMessage", "did not receive a valid HTTP response")
    exc.__cause__ = EOFError("connection closed while reading HTTP status line")

    text = link._describe_link_error(exc, "10.0.0.7")

    assert "did not receive a valid HTTP response" in text
    assert "EOFError" in text  # 因果链必须带出来
    assert "客户端证书" in text


def test_describe_link_error_flags_403_as_uid_mismatch():
    exc = _NamedError("InvalidStatus", "server rejected WebSocket connection")
    exc.response = type("_Resp", (), {"status_code": 403})()

    text = link._describe_link_error(exc, "10.0.0.7")

    assert "403" in text
    assert "uid" in text


def test_describe_link_error_flags_refused_connection():
    text = link._describe_link_error(ConnectionRefusedError(111, "Connection refused"), "10.0.0.7")

    assert "ConnectionRefusedError" in text
    assert "NODE_PORT" in text


def test_describe_link_error_generic_falls_back_to_type_and_text():
    text = link._describe_link_error(ValueError("boom"), "10.0.0.7")

    assert text == "ValueError: boom"


def _NamedError(name, message):
    """构造一个类名为 *name* 的异常，用于命中按类型名分派的提示分支。"""
    return type(name, (Exception,), {})(message)


############################################################
# 单机链路生命周期
############################################################

def test_run_machine_link_marks_online_on_connect_offline_on_close(monkeypatch):
    import websockets

    statuses = []

    class _BrokenWebSocket:
        async def receive_text(self):
            raise RuntimeError("node closed")

    class _Connection:
        async def __aenter__(self):
            return _BrokenWebSocket()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(websockets, "connect", lambda url, ssl=None: _Connection())
    monkeypatch.setattr(link, "build_link_ssl_context", lambda machine_ip: object())
    monkeypatch.setattr(link, "Update_machine", lambda machine_id, **fields: statuses.append(fields["machine_status"]))

    async def _main():
        task = asyncio.create_task(link.run_machine_link(42, "10.0.0.7", "uid-7"))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if len(statuses) >= 2:
                break
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_main())

    # 拨号结果是第一手证据：连接成功即 ONLINE，断开即 OFFLINE，无二次探测
    assert statuses[:2] == [MachineStatus.ONLINE, MachineStatus.OFFLINE]


def test_run_machine_link_does_not_dial_without_pin(monkeypatch):
    import websockets

    dialled = []
    statuses = []
    monkeypatch.setattr(link, "LINK_BACKOFF_MAX", 0.01)
    monkeypatch.setattr(link, "build_link_ssl_context", lambda machine_ip: None)
    monkeypatch.setattr(link, "Update_machine", lambda machine_id, **fields: statuses.append(fields["machine_status"]))
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: dialled.append(a))

    async def _main():
        task = asyncio.create_task(link.run_machine_link(42, "10.0.0.7", "uid-7"))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if statuses:
                break
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_main())

    assert dialled == []  # 未接入（无 pin）→ 不发起任何连接
    assert statuses == [MachineStatus.OFFLINE]
