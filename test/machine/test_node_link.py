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

    async def _run(machine_id, host, port, uid):
        record.append((machine_id, host, port, uid))
        await asyncio.sleep(3600)

    return _run


def _cancel_all(tasks):
    for entry in tasks.values():
        entry["task"].cancel()


############################################################
# URL 与 TLS 组装
############################################################

def test_link_url_composes_node_snapshot_endpoint():
    assert link.link_url("10.0.0.7", 5789, "uid-7") == "wss://10.0.0.7:5789/ws/ctrl?uid=uid-7"


def test_link_url_uses_given_port_exactly_once():
    """端口来自端点解析结果，地址里只出现一个端口段。

    曾经支持把端口写进 machine_ip（`host:port`）。那条隐式路径已废弃：地址是纯主机，
    端口走独立字段，三条出站路径共用同一个解析。若有人把端口又塞回地址，这里会拼出
    两个端口段——本用例就是那条回归线。
    """
    assert link.link_url("10.0.0.7", 6789, "uid-7") == "wss://10.0.0.7:6789/ws/ctrl?uid=uid-7"


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


def test_build_link_ssl_context_keys_pin_by_host(monkeypatch, tmp_path):
    """按主机取 pin——与操作通道 transport._resolve_tls 的取法一致。

    主机在端点解析时已剥掉端口，故这里按传入值取即可。pin 键与端口无关，
    所以换端口不会使既有 pin 失效（无需重新建立信任）。
    """
    seen = []
    pin = tmp_path / "10.0.0.7.pem"
    pin.write_bytes(b"pinned node certificate")
    monkeypatch.setattr(link, "_pin_file", lambda host: seen.append(host) or pin)
    monkeypatch.setattr(link, "_load_client_certificate", lambda: None)
    _recording_ssl_context(monkeypatch)

    assert link.build_link_ssl_context("10.0.0.7") is not None
    assert seen == ["10.0.0.7"]


############################################################
# 操作通道 TLS —— 与链路同口径（验链、不验名字）
############################################################

def _recording_pinned_context(monkeypatch, transport, captured):
    """记录 cafile 与开关的 SSLContext 替身，避免测试依赖真实证书字节。"""

    class _Context:
        check_hostname = True
        verify_mode = None

    def _create_default_context(cafile=None, **kwargs):
        captured["cafile"] = cafile
        return _Context()

    monkeypatch.setattr(transport.ssl, "create_default_context", _create_default_context)


def test_pinned_adapter_verifies_chain_but_not_hostname(monkeypatch, tmp_path):
    """动作通道对 pin 的口径必须与链路一致：验链、不验名字。

    公共 CA 模型下 hostname 校验是承重的（一个 CA 给很多名字签证书）；这里的信任锚
    只有一张自签证书，链通过即证明对端持有那把私钥——名字既不增加信息，又会在
    IP/端口变化时误杀，而端点可变正是本系统的常态。

    两个开关都要：ssl 模块一道，urllib3 v2 另有一道独立的 hostname 匹配。
    """
    from ...services.container_module.node_comms_modules import transport

    pin = tmp_path / "10.0.0.7.pem"
    pin.write_bytes(b"pinned node certificate")
    captured = {}
    _recording_pinned_context(monkeypatch, transport, captured)

    kw = transport._PinnedNodeAdapter(str(pin)).poolmanager.connection_pool_kw

    assert captured["cafile"] == str(pin), "链必须锚定在 pin 上"
    assert kw["ssl_context"].check_hostname is False
    assert kw["ssl_context"].verify_mode == ssl.CERT_REQUIRED
    assert kw["assert_hostname"] is False, "urllib3 v2 的独立匹配也必须关掉"


def test_pinned_adapter_keeps_requests_from_injecting_public_cas(monkeypatch, tmp_path):
    """pin 必须是唯一信任锚：requests 的 cert_verify 不得把 certifi 灌进连接的信任锚。

    requests 默认在 verify 为真时把 ca_certs 写成 certifi 公共 CA 包，urllib3 随后
    （ssl_wrap_socket）把它 load 进本适配器装好 pin 的 context——信任锚于是变成
    「pin ∪ 122 张公共 CA」。而本适配器关了 hostname 校验，公共 CA 那条路毫无名字约束：
    任何一张公共 CA 签发的证书都能冒充该 Node，pin 就不再是唯一信任锚了。
    """
    from ...services.container_module.node_comms_modules import transport

    pin = tmp_path / "10.0.0.7.pem"
    pin.write_bytes(b"pinned node certificate")
    _recording_pinned_context(monkeypatch, transport, {})

    class _Conn:
        cert_reqs = None
        ca_certs = None
        ca_cert_dir = None

    conn = _Conn()
    transport._PinnedNodeAdapter(str(pin)).cert_verify(conn, "https://10.0.0.7/api/x", True, None)

    assert conn.ca_certs is None, "pin 之外不得再挂公共 CA 信任锚"
    assert conn.ca_cert_dir is None
    assert conn.cert_reqs is None, "cert_reqs 由请求级 pool_kwargs 决定，不在这里覆写"


def test_post_node_json_uses_pinned_adapter_only_when_pin_present(monkeypatch, tmp_path):
    """有 pin 走自定义适配器；无 pin（TOFU 过渡态）保持原生 requests 行为。"""
    from ...services.container_module.node_comms_modules import transport

    pin = tmp_path / "10.0.0.7.pem"
    pin.write_bytes(b"pinned node certificate")
    _recording_pinned_context(monkeypatch, transport, {})
    mounted, plain = [], []

    class _Session:
        def mount(self, prefix, adapter):
            mounted.append((prefix, type(adapter).__name__))

        def post(self, url, **kwargs):
            return "via-session"

        def close(self):
            pass

    monkeypatch.setattr(transport.requests, "Session", _Session)
    monkeypatch.setattr(transport.requests, "post", lambda url, **kw: plain.append(url) or "via-plain")

    assert transport._post_node_json("https://10.0.0.7/api/x", {}, 1.0, None, str(pin)) == "via-session"
    assert mounted == [("https://", "_PinnedNodeAdapter")]

    assert transport._post_node_json("https://10.0.0.7/api/x", {}, 1.0, None, False) == "via-plain"
    assert plain == ["https://10.0.0.7/api/x"], "无 pin 时不该走适配器"
    assert len(mounted) == 1


def test_post_node_json_never_uses_environment_proxy(monkeypatch, tmp_path):
    """两条分支都必须显式绕开环境代理——节点是局域网端点，代理一接管 pin 就形同虚设。

    代理生效时 requests 走 ProxyManager 而非适配器的 poolmanager：钉在 poolmanager 上的
    ssl_context/assert_hostname 全被绕过，requests 又按 verify=True 把 ca_certs 兜底成
    certifi，于是对端自签证书被拿公共 CA 校验（报 `self-signed certificate`，而证书与 pin
    其实一字不差）。scheme 键必须显式置 None：**空字典挡不住**（requests 用 setdefault 合并）。
    """
    from ...services.container_module.node_comms_modules import transport

    pin = tmp_path / "10.0.0.7.pem"
    pin.write_bytes(b"pinned node certificate")
    _recording_pinned_context(monkeypatch, transport, {})
    seen = {}

    class _Session:
        def mount(self, prefix, adapter):
            pass

        def post(self, url, **kwargs):
            seen["pinned"] = kwargs
            return "via-session"

        def close(self):
            pass

    monkeypatch.setattr(transport.requests, "Session", _Session)
    monkeypatch.setattr(
        transport.requests, "post", lambda url, **kw: seen.setdefault("plain", kw) or "via-plain",
    )

    transport._post_node_json("https://10.0.0.7/api/x", {}, 1.0, None, str(pin))
    transport._post_node_json("https://10.0.0.7/api/x", {}, 1.0, None, False)

    direct = {"http": None, "https": None}
    assert seen["pinned"]["proxies"] == direct, "带 pin 的分支也必须直连"
    assert seen["plain"]["proxies"] == direct, "TOFU 分支同样不许走环境代理"


def test_runtime_buffer_push_never_uses_environment_proxy(monkeypatch):
    """WSS 子进程 → API 主进程的回环推送同样必须直连。

    它打的是 127.0.0.1，而 requests 在没有 no_proxy 时并不 bypass 回环——代理把 CONNECT 到
    私网/回环的请求直接重置，运行态帧就全丢了（主进程的运行态缓存只由这一跳喂，没有第二条路）。
    """
    from ...services.container_module.node_comms_modules import runtime_push

    captured = {}

    class _Response:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(runtime_push, "_read_internal_token", lambda: "t")
    monkeypatch.setattr(
        runtime_push.requests, "post",
        lambda url, **kw: captured.update(kw, url=url) or _Response(),
    )

    assert runtime_push._post_runtime_buffer("machines", {"machine_id": 7, "snapshot": {}}) is True
    assert captured["proxies"] == {"http": None, "https": None}
    assert captured["url"].startswith("https://127.0.0.1:") or captured["url"].startswith("http://127.0.0.1:")


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
    assert targets[online.id] == (online.machine_ip, 5789, "uid-online")
    assert targets[offline.id] == (offline.machine_ip, 5789, "uid-offline")


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
        monkeypatch.setattr(link, "load_link_targets", lambda: {7: ("10.0.0.7", 5789, "uid-7")})
        monkeypatch.setattr(link, "run_machine_link", _recording_link(started))
        tasks = {}

        link.sync_links(tasks)
        await asyncio.sleep(0.01)

        assert started == [(7, "10.0.0.7", 5789, "uid-7")]
        _cancel_all(tasks)
        await asyncio.gather(*(e["task"] for e in tasks.values()), return_exceptions=True)

    asyncio.run(_main())


def test_sync_links_keeps_live_links_untouched(monkeypatch):
    """已存在且存活的链路绝不重连——重连会把 5s 一帧的数据通道打成筛子。"""

    async def _main():
        started = []
        monkeypatch.setattr(link, "load_link_targets", lambda: {7: ("10.0.0.7", 5789, "uid-7")})
        monkeypatch.setattr(link, "run_machine_link", _recording_link(started))
        tasks = {}

        link.sync_links(tasks)
        await asyncio.sleep(0.01)
        first = tasks[7]["task"]
        link.sync_links(tasks)

        assert tasks[7]["task"] is first
        assert len(started) == 1
        _cancel_all(tasks)
        await asyncio.gather(*(e["task"] for e in tasks.values()), return_exceptions=True)

    asyncio.run(_main())


def test_sync_links_restarts_link_when_port_changes(monkeypatch):
    """端点变了必须重拨——否则活着的任务会一直拨旧端口，机器恒 OFFLINE 直到进程重启。

    这条在改动前是坏的：对齐只按 machine_id 比对，改地址/端口/uid 都不会生效。
    """

    async def _main():
        started = []
        targets = {7: ("10.0.0.7", 5789, "uid-7")}
        monkeypatch.setattr(link, "load_link_targets", lambda: dict(targets))
        monkeypatch.setattr(link, "run_machine_link", _recording_link(started))
        tasks = {}

        link.sync_links(tasks)
        await asyncio.sleep(0.01)
        first = tasks[7]["task"]

        targets[7] = ("10.0.0.7", 6789, "uid-7")  # 只换端口
        link.sync_links(tasks)
        await asyncio.sleep(0.01)

        assert tasks[7]["task"] is not first, "端点变了应当重建链路"
        assert started == [(7, "10.0.0.7", 5789, "uid-7"), (7, "10.0.0.7", 6789, "uid-7")]
        _cancel_all(tasks)
        await asyncio.gather(*(e["task"] for e in tasks.values()), return_exceptions=True)

    asyncio.run(_main())


def test_sync_links_restarts_link_when_host_changes(monkeypatch):
    """改地址同样触发重拨（不改动前是坏的，本次的回归重点）。"""

    async def _main():
        started = []
        targets = {7: ("10.0.0.7", 5789, "uid-7")}
        monkeypatch.setattr(link, "load_link_targets", lambda: dict(targets))
        monkeypatch.setattr(link, "run_machine_link", _recording_link(started))
        tasks = {}

        link.sync_links(tasks)
        await asyncio.sleep(0.01)

        targets[7] = ("10.0.0.8", 5789, "uid-7")
        link.sync_links(tasks)
        await asyncio.sleep(0.01)

        assert started[-1] == (7, "10.0.0.8", 5789, "uid-7")
        _cancel_all(tasks)
        await asyncio.gather(*(e["task"] for e in tasks.values()), return_exceptions=True)

    asyncio.run(_main())


def test_sync_links_restarts_link_when_uid_changes(monkeypatch):
    """uid 也是端点三元组的一员：换了身份牌就得按新身份重拨。"""

    async def _main():
        started = []
        targets = {7: ("10.0.0.7", 5789, "uid-old")}
        monkeypatch.setattr(link, "load_link_targets", lambda: dict(targets))
        monkeypatch.setattr(link, "run_machine_link", _recording_link(started))
        tasks = {}

        link.sync_links(tasks)
        await asyncio.sleep(0.01)

        targets[7] = ("10.0.0.7", 5789, "uid-new")
        link.sync_links(tasks)
        await asyncio.sleep(0.01)

        assert started[-1] == (7, "10.0.0.7", 5789, "uid-new")
        _cancel_all(tasks)
        await asyncio.gather(*(e["task"] for e in tasks.values()), return_exceptions=True)

    asyncio.run(_main())


def test_sync_links_cancels_link_for_removed_machine(monkeypatch):
    async def _main():
        targets = {7: ("10.0.0.7", 5789, "uid-7")}
        monkeypatch.setattr(link, "load_link_targets", lambda: dict(targets))
        monkeypatch.setattr(link, "run_machine_link", _recording_link([]))
        tasks = {}

        link.sync_links(tasks)
        await asyncio.sleep(0.01)
        removed = tasks[7]["task"]

        targets.clear()
        link.sync_links(tasks)

        assert tasks == {}
        await asyncio.sleep(0.01)
        assert removed.cancelled()

    asyncio.run(_main())


def test_sync_links_restarts_dead_link(monkeypatch):
    async def _main():
        started = []
        monkeypatch.setattr(link, "load_link_targets", lambda: {7: ("10.0.0.7", 5789, "uid-7")})

        async def _dies(machine_id, host, port, uid):
            started.append(machine_id)

        monkeypatch.setattr(link, "run_machine_link", _dies)
        tasks = {}

        link.sync_links(tasks)
        await asyncio.gather(*(e["task"] for e in tasks.values()), return_exceptions=True)  # 链路自行结束
        assert tasks[7]["task"].done()

        link.sync_links(tasks)
        await asyncio.sleep(0.01)

        assert len(started) == 2
        _cancel_all(tasks)
        await asyncio.gather(*(e["task"] for e in tasks.values()), return_exceptions=True)

    asyncio.run(_main())


############################################################
# 不拨的机器 → 置 OFFLINE（「我不拨你」本身就是结论）
############################################################

def test_undialable_machine_without_uid_is_marked_offline(db_session, monkeypatch):
    """缺 uid 的机器永远不会被拨，状态无人写 → 必须显式置 OFFLINE，不能留假 ONLINE。"""
    machine = create_machine(machine_name="no_uid", machine_status=MachineStatus.ONLINE)
    marked = []
    monkeypatch.setattr(link, "_mark_machine_status",
                        lambda mid, st: marked.append((mid, st)))

    link.reconcile_unmanaged_machines(link.load_link_targets())

    assert marked == [(machine.id, MachineStatus.OFFLINE)]


def test_undialable_machine_without_ip_is_marked_offline(db_session, monkeypatch):
    """缺 host 同样进不了清单——配置不完整的两种都算。"""
    # 注意 create_machine 的 `machine_ip or 默认` 会把空串替换掉，所以清空要直接改字段
    machine = create_machine(machine_name="no_ip", machine_status=MachineStatus.ONLINE)
    with session_scope() as session:
        row = machine_repo.get_by_id(machine.id, session=session)
        row.machine_ip = ""
        row.node_uid = "uid-x"
    marked = []
    monkeypatch.setattr(link, "_mark_machine_status",
                        lambda mid, st: marked.append((mid, st)))

    link.reconcile_unmanaged_machines(link.load_link_targets())

    assert (machine.id, MachineStatus.OFFLINE) in marked


def test_already_offline_undialable_machine_is_not_rewritten(db_session, monkeypatch):
    """已经是 OFFLINE 就跳过——只写一次，不制造重复审计。"""
    create_machine(machine_name="already_off", machine_status=MachineStatus.OFFLINE)
    marked = []
    monkeypatch.setattr(link, "_mark_machine_status",
                        lambda mid, st: marked.append((mid, st)))

    link.reconcile_unmanaged_machines(link.load_link_targets())

    assert marked == []


def test_dialable_machine_is_left_alone(db_session, monkeypatch):
    """清单内的机器交给拨号结果去写状态，这里不许插手。"""
    machine = create_machine(machine_name="dialable", machine_status=MachineStatus.ONLINE)
    with session_scope() as session:
        machine_repo.update_machine(machine.id, node_uid="uid-d", session=session)
    marked = []
    monkeypatch.setattr(link, "_mark_machine_status",
                        lambda mid, st: marked.append((mid, st)))

    link.reconcile_unmanaged_machines(link.load_link_targets())

    assert marked == []


def test_reconcile_opens_window_for_never_seen_machine(db_session, monkeypatch):
    """顺带收益：置 OFFLINE 会走 refresh_unavailable_window → 给从未被采集过的
    机器（last_seen_at 与窗口都为 NULL）补开窗口，倒计时不再空转。"""
    from ...services import machine_tasks
    from ...models.machine import Machine

    machine = create_machine(machine_name="never_seen", machine_status=MachineStatus.ONLINE)
    assert db_session.get(Machine, machine.id).unavailable_since is None

    link.reconcile_unmanaged_machines(link.load_link_targets())

    db_session.expire_all()
    refreshed = db_session.get(Machine, machine.id)
    assert refreshed.machine_status == MachineStatus.OFFLINE
    assert refreshed.unavailable_since is not None, "置 OFFLINE 应顺带开窗"


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
        monkeypatch.setattr(link, "load_link_targets", lambda: {7: ("10.0.0.7", 5789, "uid-7")})
        monkeypatch.setattr(link, "run_machine_link", _recording_link(started))

        manager = asyncio.create_task(link.run_links_forever())
        for _ in range(100):
            await asyncio.sleep(0.01)
            if started:
                break
        assert started == [(7, "10.0.0.7", 5789, "uid-7")]

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

    def _fake_connect(url, ssl=None, proxy=None):
        # 链路必须直连：环境里的 http_proxy/https_proxy 不该介入（websockets ≥15 默认 proxy=True）
        assert proxy is None, f"link must dial directly, got proxy={proxy!r}"
        return _Connection()

    monkeypatch.setattr(websockets, "connect", _fake_connect)
    monkeypatch.setattr(link, "build_link_ssl_context", lambda host: object())
    monkeypatch.setattr(link, "Update_machine", lambda machine_id, **fields: statuses.append(fields["machine_status"]))

    async def _main():
        task = asyncio.create_task(link.run_machine_link(42, "10.0.0.7", 5789, "uid-7"))
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
    monkeypatch.setattr(link, "build_link_ssl_context", lambda host: None)
    monkeypatch.setattr(link, "Update_machine", lambda machine_id, **fields: statuses.append(fields["machine_status"]))
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: dialled.append(a))

    async def _main():
        task = asyncio.create_task(link.run_machine_link(42, "10.0.0.7", 5789, "uid-7"))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if statuses:
                break
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_main())

    assert dialled == []  # 未接入（无 pin）→ 不发起任何连接
    assert statuses == [MachineStatus.OFFLINE]


############################################################
# 动作通道 TLS 失败诊断（把 "self-signed certificate" 变成可操作的提示）
############################################################

def test_describe_cert_mismatch_reports_both_fingerprints(monkeypatch):
    """对端换了证书 → 并排给出两组指纹，并指向「修复连接」。"""
    from ...services.container_module.node_comms_modules import transport

    monkeypatch.setattr(transport, "_peer_cert_fingerprint", lambda url, timeout=5.0: "aa" * 32)
    monkeypatch.setattr(transport, "_pin_cert_fingerprint", lambda verify: "bb" * 32)

    text = transport.describe_cert_mismatch("https://10.0.0.7:5789/api/x", "/tmp/pin.pem")

    assert "对端证书已变" in text
    assert "aaaa" in text and "bbbb" in text
    assert "修复连接" in text


def test_describe_cert_mismatch_says_do_not_renew_when_identical(monkeypatch):
    """指纹一致 → 证书没变，别去按修复连接（否则是在治错病）。"""
    from ...services.container_module.node_comms_modules import transport

    monkeypatch.setattr(transport, "_peer_cert_fingerprint", lambda url, timeout=5.0: "cc" * 32)
    monkeypatch.setattr(transport, "_pin_cert_fingerprint", lambda verify: "cc" * 32)

    text = transport.describe_cert_mismatch("https://10.0.0.7:5789/api/x", "/tmp/pin.pem")

    assert "一致" in text
    assert "不要按" in text


def test_describe_cert_mismatch_handles_unreachable_peer(monkeypatch):
    from ...services.container_module.node_comms_modules import transport

    monkeypatch.setattr(transport, "_peer_cert_fingerprint", lambda url, timeout=5.0: None)
    monkeypatch.setattr(transport, "_pin_cert_fingerprint", lambda verify: "dd" * 32)

    assert "取不到对端证书指纹" in transport.describe_cert_mismatch("https://10.0.0.7/api/x", "/tmp/pin.pem")


def test_split_netloc_handles_port_and_default():
    from ...services.container_module.node_comms_modules.transport import _split_netloc

    assert _split_netloc("https://10.0.0.7:5789/api/x") == ("10.0.0.7", 5789)
    assert _split_netloc("https://10.0.0.7/api/x") == ("10.0.0.7", 443)


def test_send_appends_diagnosis_on_cert_failure(monkeypatch):
    """send 的错误文案里要带上诊断——外层 NodeServiceError 直接透传它。

    异常类从门户已引入的 requests 取，本文件不引入该模块：安全契约禁止 test_*.py
    出现它的 import 语句（那正是「测试自己发真实请求」的入口）。
    """
    from ...services.container_module import node_comms

    def _boom(url, payload, timeout, cert, verify):
        raise node_comms.requests.exceptions.SSLError(
            "HTTPSConnectionPool: Max retries exceeded (Caused by SSLError("
            "SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] "
            "certificate verify failed: self-signed certificate')))"
        )

    monkeypatch.setattr(node_comms, "_post_node_json", _boom)
    monkeypatch.setattr(node_comms, "describe_cert_mismatch", lambda url, verify: "（诊断：对端证书已变）")

    result = node_comms.send("https://10.0.0.7:5789/api/create_container", {})

    assert "CERTIFICATE_VERIFY_FAILED" in result["error"]
    assert "（诊断：对端证书已变）" in result["error"]


def test_send_does_not_append_diagnosis_for_other_transport_errors(monkeypatch):
    """只有链校验失败才附诊断；连不上之类的失败不该被这段抢戏。"""
    from ...services.container_module import node_comms

    def _refused(url, payload, timeout, cert, verify):
        raise node_comms.requests.exceptions.ConnectionError("Connection refused")

    called = []
    monkeypatch.setattr(node_comms, "_post_node_json", _refused)
    monkeypatch.setattr(node_comms, "describe_cert_mismatch", lambda url, verify: called.append(1))

    result = node_comms.send("https://10.0.0.7:5789/api/x", {})

    assert result["error"] == "Connection refused"
    assert called == []
