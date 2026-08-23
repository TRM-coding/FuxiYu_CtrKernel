import asyncio
import json
import logging
import os
import secrets
import time
import base64
import datetime
import ssl
import warnings
from pathlib import Path
import requests
import traceback
from urllib3.exceptions import InsecureRequestWarning

from ...config import CommsConfig
from ...constant import ContainerStatus, MachineStatus
from ...extensions import session_scope
from ...repositories import machine_repo, containers_repo
from ...repositories.container_ssh_login_repo import upsert_last_ssh_login_time
from ..machine_tasks import Update_machine, is_machine_in_maintenance, is_machine_online_remote
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
WSS_RELOAD_MARKER = os.getenv(
    "CTRL_WSS_RELOAD_MARKER",
    str(Path(PINNED_CERTS_DIR) / "_wss_reload_requested"),
)


def _pin_file(machine_ip: str) -> Path:
    return Path(PINNED_CERTS_DIR) / f"{machine_ip}.pem"


def wss_reload_marker() -> Path:
    """返回 Ctrl WSS 接收器自重启 marker 文件路径。"""

    return Path(WSS_RELOAD_MARKER)


def request_wss_restart(reason: str = "pin_bundle_changed") -> dict:
    """重建 WSS pin bundle，并通知旁挂 WSS 接收器自动重启。

    WSS 服务端的 SSLContext 不会自动重新读取 ca_certs 文件；注册新 Node 后必须
    让 run_wss.py 重新创建 SSLContext。这里通过 marker 文件做轻量跨进程通知。
    """

    chain = rebuild_pinned_chain()
    marker = wss_reload_marker()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "reason": reason,
                "requested_at": datetime.datetime.utcnow().isoformat(),
                "pin_bundle": str(chain) if chain else None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "wss_reload_required": True,
        "wss_restart_requested": True,
        "pin_bundle": str(chain) if chain else None,
        "reload_marker": str(marker),
    }


def _resolve_tls(url: str, cert=None, verify=None):
    """解析 send 的 TLS 参数。

    - cert 默认 Ctrl 客户端证书（cert_utils 已生成时）
    - verify 默认对端 pin 文件（按 URL 的 host 定位）；未接入（未 pin）时降级
      verify=False（TOFU 过渡，警告）
    """
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if cert is None:
        from ...utils.cert_utils import ctrl_certificate_paths
        paths = ctrl_certificate_paths()
        if paths.cert_file.exists() and paths.key_file.exists():
            cert = (str(paths.cert_file), str(paths.key_file))
    if verify is None:
        pin = _pin_file(host)
        if pin.exists():
            verify = str(pin)
        else:
            logger.warning("send to %s: no pinned cert (machine not enrolled yet); TLS verify disabled", host)
            verify = False
    return cert, verify


def send(url: str, payload: dict, timeout: float = 5.0, *, cert=None, verify=None) -> dict:
    """
    HTTPS POST 明文 JSON payload 到 Node，返回解析后的响应（优先 JSON）。

    TLS 承载身份（check_keys 信封已退役）：https + Ctrl 客户端证书（cert）+
    对端证书 pin（verify）；显式传入 cert/verify 可覆盖默认（TOFU 首连时 verify=False）。
    """
    cert, verify = _resolve_tls(url, cert=cert, verify=verify)
    try:
        resp = requests.post(url, json=payload, timeout=timeout, cert=cert, verify=verify)

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
    """操作准入只读 Ctrl 侧状态机，不在普通操作前额外探活。"""
    try:
        with session_scope(commit=False) as session:
            m = machine_repo.get_by_id(machine_id, session=session)
    except Exception:
        m = None
    if not m:
        raise NodeServiceError(f"MACHINE {operation} failed: machine {machine_id} not found", reason="machine_not_found")
    if bool(getattr(m, "is_maintenance", False)) or is_machine_in_maintenance(machine_id):
        raise NodeServiceError(f"MACHINE {operation} aborted: machine is maintenance", reason="machine_maintenance")
    status = getattr(m, "machine_status", None)
    status_value = status.value if hasattr(status, "value") else str(status or "")
    if status_value != MachineStatus.ONLINE.value:
        raise NodeServiceError(f"MACHINE {operation} aborted: remote node not reachable or not online", reason="machine_offline")


#返回一页容器的概要信息
def _node_probe_container(container, machine_ip: str, _app=None) -> dict | None:
    """封装单次 NodeKernel /container_status 查询。

    等同于原 for 循环内 ``get_container_status(machine_ip, container.name)``，
    抽取为独立函数以适配 ``parallel_node_calls``。

    *_app* 保留兼容旧调用签名，不再使用。
    """
    try:
        return get_container_status(machine_ip, container.name)
    except Exception:
        return None


####

def get_container_status(machine_ip: str, container_name: str, timeout: float = 5.0) -> dict:
    """
    这个方法主要是为了在服务端调用 Node 的 /container_status API 来验证容器状态的。但是这个方法不被heartbeat使用。
    """
    url = get_full_url(machine_ip, "/container_status")
    payload = {"config": {"container_name": container_name}}

    last_exc = None
    for attempt in range(2):
        try:
            res = send(url, payload, timeout=timeout)
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


# 默认资源分配比例（占 Node 上报硬件的比例）：管理员随后用 update_machine 调整
DEFAULT_RESOURCE_RATIO = float(os.getenv("CTRL_DEFAULT_RESOURCE_RATIO", "0.5"))


def _default_resource_limits(hardware: dict) -> dict:
    """按默认比例策略从 Node 上报硬件生成资源分配限制（建档用）。

    真实硬件（cpu/memory/disk/gpu）取 Node 上报值；max_* 分配限制按比例折算，
    管理员通过 update_machine 调整。hardware 为 None/空时返回空 dict。
    """
    hw = hardware or {}
    cpu_cores = int((hw.get("cpu") or {}).get("cores") or 0)
    mem_gb = int((hw.get("memory") or {}).get("total_gb") or 0)
    disk_gb = int((hw.get("disk") or {}).get("total_gb") or 0)
    gpus = hw.get("gpu") or []
    ratio = DEFAULT_RESOURCE_RATIO
    limits = {
        "cpu_core_number": cpu_cores,
        "max_cpu_core_number": max(1, int(cpu_cores * ratio)),
        "memory_size_gb": mem_gb,
        "max_memory_gb": max(1, int(mem_gb * ratio)),
        "disk_size_gb": disk_gb,
        "gpu_number": len(gpus),
        "max_gpu_number": len(gpus),
        "gpu_type": (gpus[0].get("name", "") if gpus else ""),
    }
    return limits


def register_machine(
    machine_name: str,
    machine_ip: str,
    machine_description: str = "",
    timeout: float = 8.0,
) -> dict:
    """TOFU 建档一体接入（机器建档主入口）：信任锚（name/ip）→ TLS 首连 → 指纹 →
    硬件上报 → UID 下发 → 建档（默认分配比例）→ 落库双凭据。

    入参是管理员手填的最小信任锚；机器记录由本流程创建（add_machine 不再必须）。
    返回 {"success": True, "uid", "certificate_fingerprint", "machine_id", "hardware"}；
    失败抛 NodeServiceError（reason 区分阶段）。
    """
    from ...constant import MachineTypes
    from ...utils.cert_utils import ensure_ctrl_certificates, ctrl_certificate_paths, der_cert_to_pem

    if not machine_name or not machine_ip:
        raise NodeServiceError("register_machine failed: machine_name and machine_ip are required",
                               reason="invalid_trust_anchor")

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

    # 2. 首连登记资料（身份状态 + 静态硬件，不返回指纹）
    try:
        profile_url = get_full_url(machine_ip, "/node_identity/enrollment_profile")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            profile_resp = requests.get(profile_url, timeout=timeout, verify=False, cert=client_cert)
        profile = profile_resp.json()
    except Exception as e:
        raise NodeServiceError(f"register_machine failed: enrollment_profile error from {machine_ip}: {e}",
                               reason="enrollment_failed") from e
    if not isinstance(profile, dict):
        raise NodeServiceError(f"register_machine failed: bad enrollment_profile from {machine_ip}",
                               reason="enrollment_failed")
    hardware = profile.get("hardware") if isinstance(profile.get("hardware"), dict) else {}

    # 3. 生成高熵 UID 并下发
    uid = secrets.token_urlsafe(24)
    try:
        issue_url = get_full_url(machine_ip, "/node_identity/issue_uid")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
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

    # 5. 建档（硬件 + 默认分配策略）
    limits = _default_resource_limits(hardware)
    machine_type = MachineTypes.GPU if limits["gpu_number"] > 0 else MachineTypes.CPU
    try:
        with session_scope() as session:
            machine = machine_repo.create_machine(
                machinename=machine_name,
                machine_ip=machine_ip,
                machine_type=machine_type,
                machine_description=machine_description or f"enrolled via TOFU register ({machine_ip})",
                cpu_core_number=limits["cpu_core_number"],
                gpu_number=limits["gpu_number"],
                gpu_type=limits["gpu_type"],
                memory_size=limits["memory_size_gb"],
                max_shared_gb=2,
                disk_size=limits["disk_size_gb"],
                max_cpu_core_number=limits["max_cpu_core_number"],
                max_gpu_number=limits["max_gpu_number"],
                max_memory_gb=limits["max_memory_gb"],
                session=session,
            )
            machine_repo.update_machine(
                machine.id,
                node_uid=uid,
                node_cert_fingerprint=fingerprint,
                cert_pinned_at=datetime.datetime.utcnow(),
                session=session,
            )
    except Exception as e:
        raise NodeServiceError(f"register_machine failed: create/persist machine record: {e}",
                               reason="persist_failed") from e

    try:
        wss_reload = request_wss_restart(reason=f"node_enrolled:{machine.id}")
    except Exception as e:
        logger.warning("register_machine: failed to request WSS restart for %s: %s", machine_ip, e)
        wss_reload = {
            "wss_reload_required": True,
            "wss_restart_requested": False,
            "wss_restart_error": str(e),
        }

    logger.info("machine %s (%s) enrolled: id=%s uid=%s fingerprint=%s hardware=%s",
                machine_name, machine_ip, machine.id, uid, fingerprint, hardware)
    return {
        "success": True,
        "uid": uid,
        "certificate_fingerprint": fingerprint,
        "machine_id": machine.id,
        "hardware": hardware,
        **wss_reload,
    }


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
    "restarting": ContainerStatus.RESTARTING,
    "stopping": ContainerStatus.STOPPING,
    "paused": ContainerStatus.PAUSED,
    "failed": ContainerStatus.FAILED,
}


def _container_by_name(name: str):
    """快照按 name 归位到 DB 容器；未登记（Node 有、Ctrl 无）→ None，由 delete 事件语义处理。"""
    try:
        with session_scope(commit=False) as session:
            return containers_repo.get_by_container_name(name, session=session)
    except Exception:
        return None


def apply_container_status_snapshot(data: dict, machine_id: int | None = None) -> dict:
    """解析 container_status 快照 → 落库容器状态/清理消失容器。

    Ctrl DB 是容器事实清单；Node 快照只用于更新已登记容器。Node 未上报但
    Ctrl DB 里属于该 machine 的容器，视为 Node 侧已消失，复用删除清理流程。
    """
    updated = skipped = vanished = 0
    if not isinstance(data, dict):
        return {"updated": updated, "skipped": skipped, "vanished": vanished}

    missing_names: list[str] = []
    try:
        with session_scope() as session:
            containers_by_name = {}
            if machine_id is not None:
                containers = containers_repo.list_containers(
                    limit=1000000,
                    offset=0,
                    machine_id=machine_id,
                    session=session,
                )
                containers_by_name = {container.name: container for container in containers}

                snapshot_names = set(data.keys())
                missing_names = sorted(set(containers_by_name) - snapshot_names)
            for name, entry in data.items():
                ctrl_status = _NODE_STATUS_TO_CTRL.get(str((entry or {}).get("status", "")))
                if ctrl_status is None:
                    skipped += 1
                    continue
                if machine_id is not None:
                    container = containers_by_name.get(name)
                else:
                    container = containers_repo.get_by_container_name(name, session=session)
                if container is None:
                    skipped += 1
                    continue
                containers_repo.update_container(
                    container.id,
                    container_status=ctrl_status,
                    session=session,
                )
                updated += 1
    except Exception as e:
        logger.warning("apply status snapshot failed: %s", e)
        skipped += 1

    for name in missing_names:
        _handle_container_deleted(name)
        vanished += 1

    logger.info(
        "apply_container_status_snapshot: machine=%s updated=%s skipped=%s vanished=%s snapshot=%s",
        machine_id,
        updated,
        skipped,
        vanished,
        len(data),
    )
    return {"updated": updated, "skipped": skipped, "vanished": vanished}


def apply_last_ssh_snapshot(data: dict) -> dict:
    """解析 last_ssh 快照 → 落库。空值不覆写（保护初始创建时间，与现 getter 语义一致）。"""
    updated = skipped = 0
    if not isinstance(data, dict):
        return {"updated": updated, "skipped": skipped}
    try:
        with session_scope() as session:
            for name, entry in data.items():
                last_time = (entry or {}).get("last_ssh_connect_time")
                if not last_time:
                    skipped += 1
                    continue
                container = containers_repo.get_by_container_name(name, session=session)
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
                    session=session,
                )
                updated += 1
    except Exception as e:
        logger.warning("apply last_ssh snapshot failed: %s", e)
        skipped += 1
    return {"updated": updated, "skipped": skipped}


def apply_disk_usage_snapshot(data: dict) -> dict:
    """解析 disk_usage 快照 → 落库 disk_* 字段（阈值评估/告警归 disk_check 调度，本层只存值）。"""
    updated = skipped = 0
    if not isinstance(data, dict):
        return {"updated": updated, "skipped": skipped}
    containers = data.get("containers") or {}
    try:
        with session_scope() as session:
            for name, usage in containers.items():
                if not isinstance(usage, dict):
                    skipped += 1
                    continue
                container = containers_repo.get_by_container_name(name, session=session)
                if container is None:
                    skipped += 1
                    continue
                containers_repo.update_container(
                    container.id,
                    disk_overlay_rw_bytes=usage.get("overlay_rw_bytes"),
                    disk_bind_mount_bytes=usage.get("bind_mount_bytes"),
                    disk_total_bytes=usage.get("total_bytes"),
                    bind_mount_path=usage.get("bind_mount_path"),
                    disk_checked_at=datetime.datetime.utcnow(),
                    session=session,
                )
                updated += 1
    except Exception as e:
        logger.warning("apply disk snapshot failed: %s", e)
        skipped += 1
    return {"updated": updated, "skipped": skipped}


def apply_sys_snapshot(data: dict, machine_id: int | None = None) -> dict:
    """解析 sys_snapshot 帧：静态硬件漂移检测 + 动态指标记录。

    *machine_id* 由调用方从帧的 node_uid 归位（apply_snapshot_batch 提供）。
    - 静态（cpu.cores/memory.total_gb/disk.total_gb/gpu）：
      比对 machines 表建档硬件，不一致 → warning（漂移检测，凭据之外的硬件变动感知）
    - 动态（cpu.usage_percent/memory.used_gb/disk.used_gb）：
      记录日志（管理面板展示/告警评估的落库待后续）
    返回 {"checked", "drifted"}。
    """
    checked = drifted = 0
    if not isinstance(data, dict) or machine_id is None:
        return {"checked": checked, "drifted": drifted}

    machine = None
    try:
        with session_scope(commit=False) as session:
            machine = machine_repo.get_by_id(machine_id, session=session)
    except Exception:
        machine = None
    if machine is None:
        logger.debug("apply_sys_snapshot: machine %s not found (deleted?)", machine_id)
        return {"checked": checked, "drifted": drifted}

    checked += 1
    cpu = (data.get("cpu") or {}).get("cores")
    mem = (data.get("memory") or {}).get("total_gb")
    disk = (data.get("disk") or {}).get("total_gb")
    gpus = data.get("gpu") or []

    drift = {}
    if cpu is not None and int(cpu) != (machine.cpu_core_number or 0):
        drift["cpu_core_number"] = f"{machine.cpu_core_number} -> {int(cpu)}"
    if mem is not None and int(mem) != (machine.memory_size_gb or 0):
        drift["memory_size_gb"] = f"{machine.memory_size_gb} -> {int(mem)}"
    if disk is not None and int(disk) != (machine.disk_size_gb or 0):
        drift["disk_size_gb"] = f"{machine.disk_size_gb} -> {int(disk)}"
    if len(gpus) != (machine.gpu_number or 0):
        drift["gpu_number"] = f"{machine.gpu_number} -> {len(gpus)}"

    if drift:
        drifted += 1
        logger.warning("apply_sys_snapshot: HARDWARE DRIFT on machine %s (%s): %s",
                       machine.id, data.get("hostname"), drift)

    logger.info("apply_sys_snapshot: machine %s (%s) cpu=%s%% mem=%s%% disk=%s%%",
                machine.id, data.get("hostname"),
                (data.get("cpu") or {}).get("usage_percent"),
                (data.get("memory") or {}).get("usage_percent"),
                (data.get("disk") or {}).get("percent"))
    return {"checked": checked, "drifted": drifted}


def apply_snapshot_batch(batch: dict) -> dict:
    """解析 snapshot_batch 帧 → 按 topic 分发到各 apply_*。返回按 topic 的统计。

    HTTP 回退轮询与 WSS 推送共用本函数（传输无关）。
    """
    result = {}
    if not isinstance(batch, dict):
        return result

    # sys_snapshot 归位上下文：帧带 node_uid（WSS 协议）；未归位（uid 不在 machine 表）→ None
    machine_id = None
    node_uid = batch.get("node_uid")
    if node_uid:
        try:
            with session_scope(commit=False) as session:
                machine = machine_repo.get_by_uid(node_uid, session=session)
            machine_id = machine.id if machine else None
        except Exception:
            machine_id = None

    frames = batch.get("payload") or []
    for frame in frames:
        if not isinstance(frame, dict) or frame.get("type") != "snapshot":
            continue
        topic = frame.get("topic")
        data = frame.get("payload")
        if topic == "container_status":
            result[topic] = apply_container_status_snapshot(data, machine_id)
        elif topic == "last_ssh":
            result[topic] = apply_last_ssh_snapshot(data)
        elif topic == "disk_usage":
            result[topic] = apply_disk_usage_snapshot(data)
        elif topic == "sys_snapshot":
            result[topic] = apply_sys_snapshot(data, machine_id)
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
        with session_scope(commit=False) as session:
            machine = machine_repo.get_by_id(machine_id, session=session)
    except Exception:
        machine = None
    if not machine:
        return False
    machine_ip = getattr(machine, 'machine_ip', None)
    if not machine_ip:
        return False

    probe_name = None
    try:
        with session_scope(commit=False) as session:
            probe_containers = containers_repo.list_containers(
                limit=1,
                offset=0,
                machine_id=machine_id,
                session=session,
            )
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
# 应用层落库按统一 session_scope 范式处理，不再依赖 app_context。

def _handle_container_deleted(container_name: str) -> None:
    """Node 推 delete 帧：容器在 Node 侧消失 → 抹 Ctrl DB 记录（绑定 + 容器行）。

    关联表（usercontainer/container_ssh_login/freeze/long_term）均 ondelete=CASCADE，
    删容器行即级联清理。外部删除是异常路径，记录 warning。
    """
    try:
        from ...repositories.usercontainer_repo import remove_binding
        with session_scope() as session:
            container = containers_repo.get_by_container_name(container_name, session=session)
            if container is None:
                logger.debug("handle_node_ws delete: container %r already gone (skip)", container_name)
                return
            container_id, machine_id = container.id, container.machine_id
            remove_binding(0, container_id, all=True, session=session)
            containers_repo.delete_container(container_id, session=session)
        logger.warning("handle_node_ws delete: container %r (id=%s) removed from DB (vanished on node)",
                       container_name, container_id)
        # 审计：外部消失是删除的另一条路径（trigger=node_vanished），与 api/cleanup 一致入 op-log
        try:
            from ...services.operation_log_tasks import write_operation_log as write_op_log
            from ...constant import OperationType
            write_op_log(success=True,
                         operator_user_id=None,
                         operation=OperationType.DELETE_CONTAINER,
                         target_type="container",
                         target_id=container_id,
                         detail={"name": container_name, "machine_id": machine_id,
                                 "trigger": "node_vanished"})
        except Exception as le:
            logger.warning("handle_node_ws delete: op-log failed for %r: %s", container_name, le)
    except Exception as e:
        logger.warning("handle_node_ws delete: failed to remove container %r: %s", container_name, e)


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
        with session_scope(commit=False) as session:
            machine = machine_repo.get_by_uid(uid, session=session)
    except Exception as e:
        logger.warning("handle_node_ws: get_by_uid failed: %s", e)
        machine = None

    if machine is None:
        logger.warning("handle_node_ws: rejected connection with unknown uid %r", uid)
        await websocket.close(code=4403)  # UID 未归位：拒绝
        return

    machine_ip = getattr(machine, 'machine_ip', '?')
    machine_id = machine.id
    logger.info("node WSS connected: uid=%s machine=%s ip=%s", uid, machine.id, machine_ip)

    try:
        await websocket.accept()
    except Exception as e:
        Update_machine(machine_id, machine_status=MachineStatus.OFFLINE)
        logger.warning("handle_node_ws: accept failed for uid=%s: %s", uid, e)
        return

    Update_machine(machine_id, machine_status=MachineStatus.ONLINE)
    close_reason = None
    reachable_after_close = None

    try:
        while True:
            frame = json.loads(await websocket.receive_text())
            if not isinstance(frame, dict):
                logger.warning("handle_node_ws: non-dict frame from %s", uid)
                continue
            if frame.get("type") == "snapshot_batch":
                apply_snapshot_batch(frame)
            elif frame.get("type") == "delete":
                # 容器在 Node 侧消失（外部删除/对账清理）→ 抹 Ctrl DB 记录。
                # 这是 Ctrl 现有 404 语义（删 DB 记录）的唯一替代品（文档 WSS 协议硬项）。
                container_name = frame.get("container_name")
                if container_name:
                    _handle_container_deleted(container_name)
            elif frame.get("type") == "event":
                # 运行事件（event_log 素材）：记录日志；container_events 表随 WSS 推送落地时规划
                logger.info("handle_node_ws: container event uid=%s name=%s type=%s exit_code=%s",
                            uid, frame.get("container_name"), frame.get("event_type"),
                            frame.get("exit_code"))
            else:
                logger.warning("handle_node_ws: unknown frame type %r (uid=%s)", frame.get("type"), uid)
    except Exception as e:
        close_reason = e
        logger.info("handle_node_ws: retrying... | uid=%s: %s", uid, e)
        # probe 是同步 HTTP（最多 attempts 次），丢到线程池避免阻塞 WSS 事件循环
        reachable_after_close = await asyncio.to_thread(probe_machine_connectivity, machine_id)
    finally:
        if reachable_after_close is False:
            Update_machine(machine_id, machine_status=MachineStatus.OFFLINE)

        logger.info("handle_node_ws: connection closed for uid=%s: %s", uid, close_reason)
        try:
            await websocket.close()
        except Exception:
            pass
