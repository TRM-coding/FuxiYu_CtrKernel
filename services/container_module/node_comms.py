import json
import logging
import os
import secrets
import time
import base64
import datetime
import ssl
from pathlib import Path
import requests
import traceback

from ...config import CommsConfig
from ...constant import ContainerStatus
from ...repositories import machine_repo, containers_repo
from ...repositories.container_ssh_login_repo import upsert_last_ssh_login_time
from ..machine_tasks import is_machine_online_remote
from ...utils.CheckKeys import signature, encryption
from ...utils.parallel import parallel_node_calls
from .exceptions import NodeServiceError
from .utils import _parse_last_ssh_time

logger = logging.getLogger(__name__)


####################################################

def get_full_url(machine_ip:str, endpoint:str)->str:
    """Node URL 组装（TLS 方案：https；Node uvicorn 已挂 ssl）。"""
    return f"https://{machine_ip}{CommsConfig.NODE_URL_MIDDLE}{endpoint}"

####################################################
#发送指令到集群实体机

# ── TLS pin 管理（TOFU 方案） ─────────────────────────
# Node 自签证书 pin 文件：首连时 Ctrl 从 TLS 层取对端证书导出为 PEM，
# 存 pinned_certs/{machine_ip}.pem，之后 send 以 verify=该文件做证书 pin。
PINNED_CERTS_DIR = os.getenv("CTRL_PINNED_CERTS_DIR", str(Path(__file__).resolve().parents[2] / "pinned_certs"))


def _pin_file(machine_ip: str) -> Path:
    return Path(PINNED_CERTS_DIR) / f"{machine_ip}.pem"


def _resolve_tls(machine_ip: str, cert=None, verify=None):
    """解析 send 的 TLS 参数。

    - cert 默认 Ctrl 客户端证书（cert_utils 已生成时）
    - verify 默认对端 pin 文件；未接入（未 pin）时降级 verify=False（TOFU 过渡，警告）
    """
    if cert is None:
        from ...utils.cert_utils import ctrl_certificate_paths
        paths = ctrl_certificate_paths()
        if paths.cert_file.exists() and paths.key_file.exists():
            cert = (str(paths.cert_file), str(paths.key_file))
    if verify is None:
        pin = _pin_file(machine_ip)
        if pin.exists():
            verify = str(pin)
        else:
            logger.warning("send to %s: no pinned cert (machine not enrolled yet); TLS verify disabled", machine_ip)
            verify = False
    return cert, verify


def send(ciphertext:bytes,signature:bytes,mechine_ip:str, timeout:float=5.0, *, cert=None, verify=None)->dict:
    """
    发送 POST 并返回解析后的响应（优先 JSON），出现错误时返回包含 error 字段的 dict。

    TLS：https + Ctrl 客户端证书（cert）+ 对端证书 pin（verify），
    显式传入 cert/verify 可覆盖默认（TOFU 首连时 verify=False）。
    """
    cert, verify = _resolve_tls(mechine_ip, cert=cert, verify=verify)
    try:
        resp = requests.post(mechine_ip, json={
            "message": base64.b64encode(ciphertext).decode('utf-8'),
            "signature": base64.b64encode(signature).decode('utf-8')
        }, timeout=timeout, cert=cert, verify=verify)

        # 尝试解析为 JSON（即使是 4xx/5xx，也优先解析 body 中的 JSON，以保留 Node 返回的 error_reason）
        try:
            j = resp.json()
            if isinstance(j, dict):
                j.setdefault('status_code', resp.status_code)
            return j
        except ValueError:
            return {"status_code": resp.status_code, "text": resp.text}

    except requests.RequestException as e:
        # 网络/超时/连接等错误
        logger.error("Request error: %s", e)
        return {"error": str(e)}


def _ensure_machine_online_for_operation(machine_id: int, operation: str = ''):
    """
    这里检查机器在线状态的主要目的是为了在执行诸如创建/删除/修改容器等操作之前，先验证目标机器是否在线，以避免不必要的远程调用和更快地反馈给用户。虽然最终的远程调用也会有类似的检查，但这个预检查可以节省资源并提供更即时的错误响应。
    """
    try:
        m = machine_repo.get_by_id(machine_id)
    except Exception:
        m = None
    if not m:
        raise NodeServiceError(f"MACHINE {operation} failed: machine {machine_id} not found", reason="machine_not_found")
    try:
        machine_status = m.machine_status.value.lower() if hasattr(m.machine_status, 'value') else str(m.machine_status).lower()
    except Exception:
        machine_status = str(getattr(m, 'machine_status', '')).lower()
    if machine_status == 'maintenance':
        raise NodeServiceError(f"MACHINE {operation} aborted: machine is maintenance", reason="machine_maintenance")
    ok = is_machine_online_remote(machine_id)
    if not ok:
        raise NodeServiceError(f"MACHINE {operation} aborted: remote node not reachable or not online", reason="machine_offline")


#返回一页容器的概要信息
def _node_probe_container(container, machine_ip: str, _app=None) -> dict | None:
    """封装单次 NodeKernel /container_status 查询。

    等同于原 for 循环内 ``get_container_status(machine_ip, container.name)``，
    抽取为独立函数以适配 ``parallel_node_calls``。

    *_app* 可选传入 Flask app 实例，用于线程池内推送 app context。
    """
    try:
        if _app is not None:
            with _app.app_context():
                return get_container_status(machine_ip, container.name)
        return get_container_status(machine_ip, container.name)
    except Exception:
        return None


####

def get_container_status(machine_ip: str, container_name: str, timeout: float = 5.0) -> dict:
    """
    这个方法主要是为了在服务端调用 Node 的 /container_status API 来验证容器状态的。但是这个方法不被heartbeat使用。
    """
    url = get_full_url(machine_ip, "/container_status")
    payload = json.dumps({"config": {"container_name": container_name}})
    sig = signature(payload)
    enc = encryption(payload)

    last_exc = None
    for attempt in range(2):
        try:
            res = send(enc, sig, url, timeout=timeout)
            # send 不抛网络异常（以 {"error": ...} 返回），按原语义对网络级失败重试
            if isinstance(res, dict) and res.get('error') and res.get('status_code') != 404:
                last_exc = res.get('error')
                logger.warning("get_container_status request error (attempt %s): %s", attempt + 1, last_exc)
                # short backoff before retrying
                if attempt == 0:
                    time.sleep(0.5)
                continue
            # 保留原 404 语义（下游以 status_code == 404 判断容器不存在）
            if isinstance(res, dict) and res.get('status_code') == 404:
                res.setdefault('error', 'not found')
            return res
        except Exception as e:
            last_exc = e
            logger.warning("get_container_status request error (attempt %s): %s", attempt + 1, e)
            # short backoff before retrying
            if attempt == 0:
                time.sleep(0.5)
            continue

    # both attempts failed due to network/request errors
    return {"error": str(last_exc) if last_exc is not None else "unknown error"}


####################################################
# ══════════════ TOFU 接入（register_machine）═══════════════════
# 流程（fuxi平台继续开发.md「Node 通信层 · 决策」）：
#   管理员填 IP/name（信任锚）→ Ctrl HTTPS 首连 → TLS 层取对端证书指纹（唯一来源，
#   Node 不回传指纹）→ 生成高熵 UID → /issue_uid 下发 → 导出对端证书为 pin 文件 → 落库双凭据。
# Node 侧端点：/api/node_identity/enrollment_profile（GET）、/api/node_identity/issue_uid（POST）。
# 这两个端点是明文 JSON（无信封），身份由 TLS 承担；操作指令通道（send）仍走信封。

def _fetch_peer_cert(machine_ip: str, timeout: float = 5.0) -> tuple[str, bytes]:
    """TLS 层握手取对端 Node 证书 → (SHA-256 指纹, DER)。

    这是指纹的唯一来源（TOFU pin 依据）：不验证对端（首连信任锚 = 人工填 IP），
    仅取证书本身。DER 后续导出为 pin 文件。
    """
    host, _, port_str = machine_ip.partition(":")
    port = int(port_str) if port_str else CommsConfig.NODE_PORT
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with ctx.wrap_socket(ssl.create_connection((host, port), timeout=timeout), server_hostname=host) as sock:
        der = sock.getpeercert(binary_form=True)
    if not der:
        raise NodeServiceError(f"peer cert not available for {machine_ip}", reason="peer_cert_unavailable")
    from ...utils.cert_utils import der_cert_sha256_fingerprint
    return der_cert_sha256_fingerprint(der), der


def register_machine(machine_id: int, timeout: float = 8.0) -> dict:
    """TOFU 接入一台机器：首连 → TLS 层取指纹 → 颁发 UID → 下发 → pin → 落库。

    返回 {"success": True, "uid": str, "certificate_fingerprint": str}；
    失败抛 NodeServiceError（reason 区分阶段）。
    """
    from ...utils.cert_utils import ensure_ctrl_certificates, ctrl_certificate_paths, der_cert_to_pem

    machine = None
    try:
        machine = machine_repo.get_by_id(machine_id)
    except Exception:
        machine = None
    if not machine:
        raise NodeServiceError(f"register_machine failed: machine {machine_id} not found", reason="machine_not_found")
    machine_ip = getattr(machine, 'machine_ip', None)
    if not machine_ip:
        raise NodeServiceError(f"register_machine failed: machine {machine_id} has no ip", reason="machine_no_ip")

    # Ctrl 证书先就绪（mTLS 客户端证书；Node 侧校验调用者用）
    try:
        ensure_ctrl_certificates()
        paths = ctrl_certificate_paths()
        client_cert = (str(paths.cert_file), str(paths.key_file))
    except Exception as e:
        logger.warning("ctrl cert not ready during register_machine: %s", e)
        client_cert = None

    # 1. TLS 层取对端证书指纹（唯一来源，Node 不回传）
    try:
        fingerprint, cert_der = _fetch_peer_cert(machine_ip, timeout=timeout)
    except Exception as e:
        raise NodeServiceError(f"register_machine failed: cannot reach {machine_ip} over TLS: {e}",
                               reason="machine_unreachable") from e

    # 2. 首连登记资料（只读身份状态，不返回指纹）
    try:
        profile_url = get_full_url(machine_ip, "/node_identity/enrollment_profile")
        profile_resp = requests.get(profile_url, timeout=timeout, verify=False, cert=client_cert)
        profile = profile_resp.json()
    except Exception as e:
        raise NodeServiceError(f"register_machine failed: enrollment_profile error from {machine_ip}: {e}",
                               reason="enrollment_failed") from e
    if not isinstance(profile, dict):
        raise NodeServiceError(f"register_machine failed: bad enrollment_profile from {machine_ip}",
                               reason="enrollment_failed")

    # 3. 生成高熵 UID 并下发
    uid = secrets.token_urlsafe(24)
    try:
        issue_url = get_full_url(machine_ip, "/node_identity/issue_uid")
        issue_resp = requests.post(issue_url, json={"uid": uid}, timeout=timeout, verify=False, cert=client_cert)
        issue = issue_resp.json()
    except Exception as e:
        raise NodeServiceError(f"register_machine failed: issue_uid error from {machine_ip}: {e}",
                               reason="issue_uid_failed") from e
    if not (isinstance(issue, dict) and issue.get("success") == 1):
        raise NodeServiceError(f"register_machine failed: issue_uid rejected by {machine_ip}: {issue}",
                               reason="issue_uid_rejected")

    # 4. 导出对端证书为 pin 文件（后续 send 以 verify=该文件做证书 pin）
    try:
        _pin_file(machine_ip).parent.mkdir(parents=True, exist_ok=True)
        _pin_file(machine_ip).write_bytes(der_cert_to_pem(cert_der))
    except Exception as e:
        logger.warning("register_machine: failed to persist pin file for %s: %s", machine_ip, e)

    # 5. 落库双凭据
    try:
        machine_repo.update_machine(
            machine_id,
            node_uid=uid,
            node_cert_fingerprint=fingerprint,
            cert_pinned_at=datetime.datetime.utcnow(),
        )
    except Exception as e:
        raise NodeServiceError(f"register_machine failed: persist credentials for machine {machine_id}: {e}",
                               reason="persist_failed") from e

    logger.info("machine %s (%s) enrolled: uid=%s fingerprint=%s",
                machine_id, machine_ip, uid, fingerprint)
    return {"success": True, "uid": uid, "certificate_fingerprint": fingerprint}


####################################################
# ══════════════ WSS 快照解析层 ═══════════════════
# 传输无关：HTTP 回退探测与 WSS 推送走同一份解析函数。
# Node 推送形状（wss.py build_snapshot_batch）：
#   {"type": "snapshot_batch", "node_uid", "certificate_fingerprint",
#    "payload": [{"type": "snapshot", "topic": "container_status"|"last_ssh"|"disk_usage", "payload": ...}]}
#   container_status: {name: {"source", "status", "error_reason"?, "cache_updated_at"?}}
#   last_ssh:         {name: {"last_ssh_connect_time", "updated_at"}}
#   disk_usage:       {"machine_disk": {...}, "containers": {name: {"overlay_rw_bytes", "bind_mount_bytes", "bind_mount_path", "total_bytes"}}}

# Node 应用状态字符串 → Ctrl ContainerStatus 枚举；unknown/不可映射 → 跳过（保持 DB 旧值）
_NODE_STATUS_TO_CTRL = {
    "online": ContainerStatus.ONLINE,
    "offline": ContainerStatus.OFFLINE,
    "creating": ContainerStatus.CREATING,
    "starting": ContainerStatus.STARTING,
    "stopping": ContainerStatus.STOPPING,
    "paused": ContainerStatus.PAUSED,
    "failed": ContainerStatus.FAILED,
}


def _container_by_name(name: str):
    """快照按 name 归位到 DB 容器；未登记（Node 有、Ctrl 无）→ None，由 delete 事件语义处理。"""
    try:
        return containers_repo.get_by_container_name(name)
    except Exception:
        return None


def apply_container_status_snapshot(data: dict) -> dict:
    """解析 container_status 快照 → 落库容器状态。返回 {"updated", "skipped"}。"""
    updated = skipped = 0
    if not isinstance(data, dict):
        return {"updated": updated, "skipped": skipped}
    for name, entry in data.items():
        try:
            ctrl_status = _NODE_STATUS_TO_CTRL.get(str((entry or {}).get("status", "")))
            if ctrl_status is None:
                skipped += 1
                continue
            container = _container_by_name(name)
            if container is None:
                skipped += 1
                continue
            containers_repo.update_container(container.id, commit=False,
                                             container_status=ctrl_status)
            updated += 1
        except Exception as e:
            logger.warning("apply status snapshot failed for %s: %s", name, e)
            skipped += 1
    if updated:
        try:
            from ...extensions import db
            db.session.commit()
        except Exception as e:
            logger.warning("commit status snapshot failed: %s", e)
    return {"updated": updated, "skipped": skipped}


def apply_last_ssh_snapshot(data: dict) -> dict:
    """解析 last_ssh 快照 → 落库。空值不覆写（保护初始创建时间，与现 getter 语义一致）。"""
    updated = skipped = 0
    if not isinstance(data, dict):
        return {"updated": updated, "skipped": skipped}
    for name, entry in data.items():
        try:
            last_time = (entry or {}).get("last_ssh_connect_time")
            if not last_time:
                skipped += 1
                continue
            container = _container_by_name(name)
            if container is None:
                skipped += 1
                continue
            parsed = _parse_last_ssh_time(str(last_time))
            if parsed is not None:
                last_time = parsed.strftime('%Y-%m-%dT%H:%M:%S')
            upsert_last_ssh_login_time(
                machine_id=container.machine_id,
                container_id=container.id,
                last_ssh_login_time=last_time,
            )
            updated += 1
        except Exception as e:
            logger.warning("apply last_ssh snapshot failed for %s: %s", name, e)
            skipped += 1
    return {"updated": updated, "skipped": skipped}


def apply_disk_usage_snapshot(data: dict) -> dict:
    """解析 disk_usage 快照 → 落库 disk_* 字段（阈值评估/告警归 disk_check 调度，本层只存值）。"""
    updated = skipped = 0
    if not isinstance(data, dict):
        return {"updated": updated, "skipped": skipped}
    containers = data.get("containers") or {}
    for name, usage in containers.items():
        try:
            if not isinstance(usage, dict):
                skipped += 1
                continue
            container = _container_by_name(name)
            if container is None:
                skipped += 1
                continue
            containers_repo.update_container(
                container.id,
                commit=False,
                disk_overlay_rw_bytes=usage.get("overlay_rw_bytes"),
                disk_bind_mount_bytes=usage.get("bind_mount_bytes"),
                disk_total_bytes=usage.get("total_bytes"),
                bind_mount_path=usage.get("bind_mount_path"),
                disk_checked_at=datetime.datetime.utcnow(),
            )
            updated += 1
        except Exception as e:
            logger.warning("apply disk snapshot failed for %s: %s", name, e)
            skipped += 1
    if updated:
        try:
            from ...extensions import db
            db.session.commit()
        except Exception as e:
            logger.warning("commit disk snapshot failed: %s", e)
    return {"updated": updated, "skipped": skipped}


def apply_snapshot_batch(batch: dict) -> dict:
    """解析 snapshot_batch 帧 → 按 topic 分发到三个 apply_*。返回按 topic 的统计。

    HTTP 回退轮询与 WSS 推送共用本函数（传输无关）。
    """
    result = {}
    if not isinstance(batch, dict):
        return result
    frames = batch.get("payload") or []
    for frame in frames:
        if not isinstance(frame, dict) or frame.get("type") != "snapshot":
            continue
        topic = frame.get("topic")
        data = frame.get("payload")
        if topic == "container_status":
            result[topic] = apply_container_status_snapshot(data)
        elif topic == "last_ssh":
            result[topic] = apply_last_ssh_snapshot(data)
        elif topic == "disk_usage":
            result[topic] = apply_disk_usage_snapshot(data)
        else:
            logger.warning("apply_snapshot_batch: unknown topic %r", topic)
    return result


# ══════════════ WSS 断线回退 · 连通性探测 ═══════════════════
# 文档约定：WSS 断开 → HTTP 回退只做连通性探测（container_status），
# 连续 attempts 次网络不达判宿主机离线；数据靠 WSS 重连后的全量快照补齐，不靠 HTTP 捞。
CONNECTIVITY_PROBE_ATTEMPTS = 2


def probe_machine_connectivity(machine_id: int, attempts: int = CONNECTIVITY_PROBE_ATTEMPTS) -> bool:
    """WSS 断线回退：HTTP 探测宿主机连通性（只看通不通，不看内容）。

    - 有容器 → 打任一容器的 /container_status；任何响应（含 404）都算通，仅网络级失败算不达
    - 无容器 → 退化打 /machine_status（等价 is_machine_online_remote 语义）
    - 连续 attempts 次网络不达 → False（判宿主机离线，容器派生 offline 由展示层完成）
    """
    try:
        machine = machine_repo.get_by_id(machine_id)
    except Exception:
        machine = None
    if not machine:
        return False
    machine_ip = getattr(machine, 'machine_ip', None)
    if not machine_ip:
        return False

    probe_name = None
    try:
        probe_containers = containers_repo.list_containers(
            limit=1, offset=0, machine_id=machine_id)
        if probe_containers:
            probe_name = getattr(probe_containers[0], 'name', None)
    except Exception:
        pass

    fails = 0
    for _ in range(max(1, attempts)):
        try:
            if probe_name is not None:
                res = get_container_status(machine_ip, probe_name, timeout=2.0)
                # 任何响应（含 404：容器不存在但机器在）都算连通；仅网络级 error 算不达
                if isinstance(res, dict) and not res.get('error'):
                    return True
            else:
                if is_machine_online_remote(machine_id, timeout=2.0):
                    return True
            fails += 1
        except Exception:
            fails += 1
    logger.warning("probe_machine_connectivity: machine %s unreachable after %s attempts", machine_id, attempts)
    return False


# ══════════════ WSS 接收层（FastAPI 形态） ═══════════════════
# 挂载要求（Ctrl ASGI/FastAPI 落地时）：
#   1. ssl context：certfile/keyfile = Ctrl 证书（ensure_ctrl_certificates），
#      verify_mode=REQUIRED + ca_certs=rebuild_pinned_chain()（见下）——
#      TLS 层校验 Node 必须持有已 pin 的自签证书私钥（传输层凭证，双凭据之一）
#   2. 注册 @app.websocket("/ws/node") 指向本函数
#   3. 断线 → 由挂载方调用 probe_machine_connectivity 回退探测（连续两次不达判宿主机离线）
# 应用层 session：落库需 Flask app context（apply_* 用 db.session），挂载方包一层 ctx。

def rebuild_pinned_chain() -> Path | None:
    """重建 pin chain 文件：pinned_certs/*.pem 拼接为一个 bundle。

    Node 证书自签（不走 Ctrl CA），自身即信任锚——把已 pin 的 Node 证书
    直接作为 ca_certs 喂给 WSS 服务端 ssl context，握手时只有持有对应
    私钥的 Node 能通过（等价证书指纹校验，且无 CA 需求）。
    返回 bundle 路径；无任何 pin 文件时返回 None（此时不应开启 REQUIRED）。
    """
    pins_dir = Path(PINNED_CERTS_DIR)
    if not pins_dir.exists():
        return None
    pem_files = sorted(pins_dir.glob("*.pem"))
    if not pem_files:
        return None
    bundle = pins_dir / "_chain_bundle.pem"
    try:
        contents = [p.read_bytes() for p in pem_files if p.name != "_chain_bundle.pem"]
        bundle.write_bytes(b"\n".join(contents))
    except Exception as e:
        logger.warning("rebuild_pinned_chain failed: %s", e)
        return None
    return bundle


async def handle_node_ws(websocket) -> None:
    """Node → Ctrl `/ws/node` WebSocket 接收处理器。

    身份校验（双凭据）：
    1. TLS 层：挂载方 ssl context（REQUIRED + ca_certs=rebuild_pinned_chain()）——
       Node 必须持有已 pin 证书私钥才能完成握手（传输层凭证）
    2. 应用层：?uid= 查询参数 → machine_repo.get_by_uid 归位（应用层标识）
    帧分发：snapshot_batch → apply_snapshot_batch（缓冲批处理落库）。
    event / delete 帧：后续按 WSS 协议硬项扩展（容器消失感知、运行事件）。
    """
    from urllib.parse import parse_qs

    scope = getattr(websocket, "scope", {}) or {}
    query = parse_qs(scope.get("query_string", b"").decode("utf-8", errors="ignore"))
    uid = (query.get("uid") or [None])[0]

    if not uid:
        await websocket.close(code=4401)  # 无 UID：应用层凭证缺失
        return

    try:
        machine = machine_repo.get_by_uid(uid)
    except Exception as e:
        logger.warning("handle_node_ws: get_by_uid failed: %s", e)
        machine = None

    if machine is None:
        logger.warning("handle_node_ws: rejected connection with unknown uid %r", uid)
        await websocket.close(code=4403)  # UID 未归位：拒绝
        return

    machine_ip = getattr(machine, 'machine_ip', '?')
    logger.info("node WSS connected: uid=%s machine=%s ip=%s", uid, machine.id, machine_ip)

    try:
        await websocket.accept()
    except Exception as e:
        logger.warning("handle_node_ws: accept failed for uid=%s: %s", uid, e)
        return

    try:
        while True:
            frame = json.loads(await websocket.receive_text())
            if not isinstance(frame, dict):
                logger.warning("handle_node_ws: non-dict frame from %s", uid)
                continue
            if frame.get("type") == "snapshot_batch":
                # 落库需 Flask app context——挂载方（ASGI 桥接）负责包 ctx
                apply_snapshot_batch(frame)
            elif frame.get("type") in ("event", "delete"):
                logger.info("handle_node_ws: frame type %r not yet handled (uid=%s)", frame.get("type"), uid)
            else:
                logger.warning("handle_node_ws: unknown frame type %r (uid=%s)", frame.get("type"), uid)
    except Exception as e:
        logger.info("handle_node_ws: connection closed for uid=%s: %s", uid, e)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


