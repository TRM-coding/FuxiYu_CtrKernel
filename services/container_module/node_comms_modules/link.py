from __future__ import annotations

import asyncio
import logging
import os
import ssl

from ....config import CommsConfig
from ....constant import MachineStatus
from ....extensions import session_scope
from ....repositories import machine_repo
from ...machine_tasks import Update_machine
from .transport import _pin_file

logger = logging.getLogger(__name__)

# Ctrl 拨入 Node 的快照端点；与操作通道共用 Node 的同一个 HTTPS 监听。
LINK_PATH = "/ws/ctrl"
# 对齐周期：machines 表 → 运行中链路集合的差集收敛节奏。
LINK_SYNC_INTERVAL = float(os.getenv("CTRL_LINK_SYNC_INTERVAL", "5"))
# 重连退避：首次间隔与上限（上限即「离线机器定期检查」的周期）。
LINK_BACKOFF_INITIAL = float(os.getenv("CTRL_LINK_BACKOFF_INITIAL", "1"))
LINK_BACKOFF_MAX = float(os.getenv("CTRL_LINK_BACKOFF_MAX", "30"))
# 分页读机器表的页大小。
_MACHINE_PAGE_SIZE = 200


############################################################
# 目标解析（machines 表 → 链路目标集合）
############################################################

def _split_host_port(machine_ip: str) -> tuple[str, int]:
    """拆出裸主机与端口；未显式带端口时用 NODE_PORT。"""

    host, _, port_str = machine_ip.partition(":")
    return host, int(port_str) if port_str else CommsConfig.NODE_PORT


def _load_machine_rows() -> list:
    """分页读全量机器行（含 OFFLINE）；读失败按空集合处理，下一轮对齐重试。"""

    rows: list = []
    offset = 0
    try:
        while True:
            with session_scope(commit=False) as session:
                page = list(machine_repo.list_machines(limit=_MACHINE_PAGE_SIZE, offset=offset, session=session))
            rows.extend(page)
            if len(page) < _MACHINE_PAGE_SIZE:
                return rows
            offset += _MACHINE_PAGE_SIZE
    except Exception as exc:
        logger.warning("link sync: load machines failed: %s", exc)
        return rows


def load_link_targets() -> dict[int, tuple[str, str]]:
    """返回 {machine_id: (machine_ip, uid)}——machines 表即链路清单。

    表里有行就拨（含 OFFLINE 的机器，这就是离线发现）；未完成注册（无 uid）
    的机器读不到身份牌，跳过。
    """

    targets: dict[int, tuple[str, str]] = {}
    for machine in _load_machine_rows():
        machine_ip = getattr(machine, "machine_ip", None)
        uid = getattr(machine, "node_uid", None)
        if machine_ip and uid:
            targets[machine.id] = (machine_ip, uid)
        elif machine_ip:
            logger.debug("link sync: machine %s has no uid yet; skipped", machine.id)
    return targets


############################################################
# 传输参数（URL 与 TLS）
############################################################

def link_url(machine_ip: str, uid: str) -> str:
    """Ctrl 拨 Node 的 WSS 地址。"""

    host, port = _split_host_port(machine_ip)
    return f"wss://{host}:{port}{LINK_PATH}?uid={uid}"


def _load_client_certificate() -> tuple[str, str] | None:
    """Ctrl 自身的客户端证书（HTTPS 操作通道与链路共用同一张）。"""

    try:
        from ....utils.cert_utils import ctrl_certificate_paths, ensure_ctrl_certificates

        ensure_ctrl_certificates()
        paths = ctrl_certificate_paths()
        if paths.cert_file.exists() and paths.key_file.exists():
            return str(paths.cert_file), str(paths.key_file)
    except Exception as exc:
        logger.warning("link: Ctrl client certificate unavailable: %s", exc)
    return None


def build_link_ssl_context(machine_ip: str) -> ssl.SSLContext | None:
    """构造链路 TLS 上下文；该机器尚无 pin 时返回 None（不拨）。

    信任锚取该机器专属 pin 文件——注册时从该 IP 抓到的那张证书本身，TOFU 已把
    身份钉死，故关闭 hostname 校验：Node 自签证书默认 SAN 不含业务 IP，开启会
    让跨机链路必然失败，而链校验已足够。
    """

    host, _ = _split_host_port(machine_ip)
    pin = _pin_file(host)
    if not pin.exists():
        logger.warning("link to %s: no pinned cert (machine not enrolled); not dialing", host)
        return None
    try:
        context = ssl.create_default_context(cafile=str(pin))
    except Exception as exc:
        logger.warning("link to %s: build ssl context failed: %s", host, exc)
        return None
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    client_cert = _load_client_certificate()
    if client_cert:
        try:
            context.load_cert_chain(certfile=client_cert[0], keyfile=client_cert[1])
        except Exception as exc:
            logger.warning("link to %s: load Ctrl client cert failed: %s", host, exc)
    return context


############################################################
# 单机链路（拨号 → 收帧 → 断开退避重连）
############################################################

def _mark_machine_status(machine_id: int, status: MachineStatus) -> None:
    try:
        Update_machine(machine_id, machine_status=status)
    except Exception as exc:
        logger.warning("link: update machine %s status to %s failed: %s", machine_id, status.value, exc)


############################################################
# 故障诊断（把泛化异常翻译成可操作的一句话）
############################################################

def _link_error_hint(exc: BaseException, machine_ip: str) -> str:
    """按异常类型给出「该去查什么」。

    链路失败最难受的一点是两类完全相反的原因会压成同一句话：
    本端拒了对端证书（pin 失效）与对端拒了本端证书（Node 侧 mTLS），
    在 websockets/ssl 的 str(exc) 里都看不出来。这里分类点破。
    """

    host, _ = _split_host_port(machine_ip)

    if isinstance(exc, ssl.SSLCertVerificationError):
        return (
            f"本端拒绝对端证书：Node 当前证书与 {_pin_file(host)} 不一致"
            "（Node 可能重新生成过自签证书，例如主机名变化导致 SAN 校验失败）"
            "→ 需重新登记该机器或更新 pin"
        )

    name = type(exc).__name__
    if name == "InvalidMessage" and "valid HTTP response" in str(exc):
        return (
            "对端未返回合法 HTTP 响应：多半是 Node 在 TLS 层拒绝了本端客户端证书"
            "→ 检查 Ctrl 证书是否可加载（certs/ctrl.pem/ctrl-key.pem），"
            "以及 Node 侧 NODE_CTRL_CA_FILE 是否指向当前这套 Ctrl CA"
        )
    if name == "InvalidStatus":
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 403:
            return "对端拒绝握手（403）：uid 与 Node 本机身份牌不一致 → 检查 machines.node_uid 与 Node 的 .node_identity.json"
        return f"对端拒绝握手（HTTP {status}）→ 检查 Node 是否已注册 {LINK_PATH} 路由"
    if name == "InvalidURI":
        return "对端地址不合法 → 检查 machines.machine_ip"
    if isinstance(exc, (ConnectionRefusedError, TimeoutError, asyncio.TimeoutError)):
        return "连不上（拒绝/超时）→ 检查 Node 是否在跑、NODE_PORT 与机器 IP 是否正确"
    if isinstance(exc, ssl.SSLError):
        return "TLS 层失败 → 检查双方证书与信任锚"
    return ""


def _describe_link_error(exc: BaseException, machine_ip: str) -> str:
    """异常类型 + 因果链 + 排查提示。

    只打 str(exc) 会丢掉全部上下文（如 websockets 的 InvalidMessage 只剩一句
    "did not receive a valid HTTP response"），所以把 __cause__/__context__ 链一并带上。
    """

    chain: list[str] = []
    current: BaseException | None = exc
    while current is not None and len(chain) < 4:
        chain.append(f"{type(current).__name__}: {current}")
        if current in (current.__cause__, current.__context__):
            break
        current = current.__cause__ or current.__context__
    detail = " <- ".join(chain)
    hint = _link_error_hint(exc, machine_ip)
    return f"{detail} | {hint}" if hint else detail



async def run_machine_link(machine_id: int, machine_ip: str, uid: str) -> None:
    """单机链路循环；每台机器独立退避，互不影响。

    连接成功即判 ONLINE、断开即判 OFFLINE——拨号结果是第一手证据，不再二次探测。
    """

    from .websocket import _consume_link

    try:
        import websockets
    except ImportError:  # pragma: no cover
        logger.error("websockets package is not installed; node links are disabled")
        return

    backoff = LINK_BACKOFF_INITIAL
    while True:
        try:
            context = build_link_ssl_context(machine_ip)
            if context is None:
                _mark_machine_status(machine_id, MachineStatus.OFFLINE)
                await asyncio.sleep(LINK_BACKOFF_MAX)
                continue
            async with websockets.connect(link_url(machine_ip, uid), ssl=context) as websocket:
                logger.info("node link established: machine=%s ip=%s", machine_id, machine_ip)
                _mark_machine_status(machine_id, MachineStatus.ONLINE)
                backoff = LINK_BACKOFF_INITIAL
                await _consume_link(websocket, uid, machine_id)
                logger.info("node link closed: machine=%s ip=%s", machine_id, machine_ip)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "node link error: machine=%s url=%s: %s",
                machine_id,
                link_url(machine_ip, uid),
                _describe_link_error(exc, machine_ip),
            )
        _mark_machine_status(machine_id, MachineStatus.OFFLINE)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, LINK_BACKOFF_MAX)


############################################################
# 集合对齐（运行中链路 ↔ machines 表）
############################################################

def sync_links(tasks: dict[int, asyncio.Task]) -> None:
    """把运行中的链路集合对齐到 machines 表全量。

    只对差集动作：新增起链路、消失或已死的停链路；已存在且存活的**绝不重连**
    ——重连会把 5s 一帧的数据通道打成筛子。
    """

    targets = load_link_targets()
    for machine_id in list(tasks):
        task = tasks[machine_id]
        if machine_id not in targets or task.done():
            tasks.pop(machine_id).cancel()
    for machine_id, (machine_ip, uid) in targets.items():
        if machine_id not in tasks:
            tasks[machine_id] = asyncio.create_task(run_machine_link(machine_id, machine_ip, uid))


async def run_links_forever() -> None:
    """常驻：维持全量链路，并周期性对齐集合。"""

    tasks: dict[int, asyncio.Task] = {}
    logger.info("node link manager started: sync_interval=%ss", LINK_SYNC_INTERVAL)
    try:
        while True:
            sync_links(tasks)
            await asyncio.sleep(LINK_SYNC_INTERVAL)
    except asyncio.CancelledError:
        logger.info("node link manager stopping: %s live link(s)", len(tasks))
        raise
    finally:
        for task in tasks.values():
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks.values(), return_exceptions=True)
