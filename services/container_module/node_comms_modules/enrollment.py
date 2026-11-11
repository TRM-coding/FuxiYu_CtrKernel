from __future__ import annotations

import datetime
import logging
import os
import ssl
import warnings

import requests
from urllib3.exceptions import InsecureRequestWarning

from ....extensions import session_scope
from ....repositories import machine_repo
from ..exceptions import NodeServiceError
from .endpoint import bare_host
from .transport import _pin_file
from ....constant import MachineTypes
from ....utils.cert_utils import ensure_ctrl_certificates, ctrl_certificate_paths, der_cert_to_pem

logger = logging.getLogger(__name__)
DEFAULT_RESOURCE_RATIO = float(os.getenv("CTRL_DEFAULT_RESOURCE_RATIO", "0.5"))

def _fetch_peer_cert(host: str, port: int, timeout: float = 5.0) -> tuple[str, bytes]:
    """TLS 层握手取对端 Node 证书 → (SHA-256 指纹, DER)。

    这是指纹的唯一来源（TOFU pin 依据）：不验证对端（首连信任锚 = 人工填 IP），
    仅取证书本身。DER 后续导出为 pin 文件。

    端点由调用方解析后传入（`endpoint.machine_endpoint` / `endpoint.resolve_port`），
    本函数不再自行从地址里拆端口——那样会与另外两条出站路径各写各的。
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with ctx.wrap_socket(ssl.create_connection((host, port), timeout=timeout), server_hostname=host) as sock:
        der = sock.getpeercert(binary_form=True)
    if not der:
        raise NodeServiceError(f"peer cert not available for {host}:{port}", reason="peer_cert_unavailable")
    from ....utils.cert_utils import der_cert_sha256_fingerprint
    return der_cert_sha256_fingerprint(der), der


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
        "gpu_type": (gpus[0].get("name", "") if gpus else ""),
    }
    return limits


def _validate_trust_anchor(machine_name: str, machine_ip: str) -> None:
    if not machine_name or not machine_ip:
        raise NodeServiceError(
            "register_machine failed: machine_name and machine_ip are required", reason="invalid_trust_anchor",
        )
    # 主机地址是纯 IPv4，端口走独立字段。拒绝 `host:port` 是为了堵住旧的隐式写法——
    # 那条路在 HTTPS 动作通道上会拼出畸形地址、且 pin 键会写成 <host>:<port>.pem。
    if ":" in str(machine_ip):
        raise NodeServiceError(
            f"register_machine failed: machine_ip must be a bare address without a port, got {machine_ip!r}; "
            "pass the port separately",
            reason="invalid_machine_ip",
        )


def _validate_node_port(port) -> int | None:
    """端口入参校验：None / 空串合法（表示回落全局默认），否则须是 1–65535 的整数。

    走 float 再验整性，而不是直接 int()：后者会把 1.5 静默截断成 1，让一个显然是
    客户端 bug 的入参变成一台指错端口的机器。bool 单独挡掉（它是 int 的子类，
    `port: true` 会悄悄变成 1）。
    """

    if port is None or port == "":
        return None
    if isinstance(port, bool):
        raise NodeServiceError(
            f"register_machine failed: port must be an integer, got {port!r}", reason="invalid_node_port",
        )
    try:
        number = float(port)
    except (TypeError, ValueError):
        raise NodeServiceError(
            f"register_machine failed: port must be an integer, got {port!r}", reason="invalid_node_port",
        )
    if not number.is_integer():
        raise NodeServiceError(
            f"register_machine failed: port must be an integer, got {port!r}", reason="invalid_node_port",
        )
    value = int(number)
    if not 1 <= value <= 65535:
        raise NodeServiceError(
            f"register_machine failed: port out of range (1-65535): {value}", reason="invalid_node_port",
        )
    return value


def _get_enrollment_client_cert():
    try:
        ensure_ctrl_certificates()
        paths = ctrl_certificate_paths()
        return str(paths.cert_file), str(paths.key_file)
    except Exception as exc:
        logger.warning("ctrl cert not ready during register_machine: %s", exc)
        return None


def _fetch_enrollment_profile(url: str, machine_ip: str, client_cert, timeout: float, context: str = "register_machine") -> dict:
    """取对端 enrollment_profile 全量响应；由调用方决定取用哪些字段。

    注册只关心 hardware，重钉还要读 identity_initialized（判断是否需重发 uid），
    所以这里返回全量，不再把「取硬件快照」的裁剪混进请求本身。
    """

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            response = requests.get(url, timeout=timeout, verify=False, cert=client_cert)
        profile = response.json()
    except Exception as exc:
        raise NodeServiceError(
            f"{context} failed: enrollment_profile error from {machine_ip}: {exc}",
            reason="enrollment_failed",
        ) from exc
    if not isinstance(profile, dict):
        raise NodeServiceError(
            f"{context} failed: bad enrollment_profile from {machine_ip}", reason="enrollment_failed",
        )
    return profile


def _request_enrollment_profile(url: str, machine_ip: str, client_cert, timeout: float) -> dict:
    """注册路径的视图：只取硬件快照。"""

    profile = _fetch_enrollment_profile(url, machine_ip, client_cert, timeout)
    return profile.get("hardware") if isinstance(profile.get("hardware"), dict) else {}


def _issue_node_uid(url: str, machine_ip: str, uid: str, client_cert, timeout: float) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            response = requests.post(url, json={"uid": uid}, timeout=timeout, verify=False, cert=client_cert)
        issue = response.json()
    except Exception as exc:
        raise NodeServiceError(
            f"register_machine failed: issue_uid error from {machine_ip}: {exc}", reason="issue_uid_failed",
        ) from exc
    if not (isinstance(issue, dict) and issue.get("success") == 1):
        raise NodeServiceError(
            f"register_machine failed: issue_uid rejected by {machine_ip}: {issue}", reason="issue_uid_rejected",
        )


def _persist_peer_pin(machine_ip: str, cert_der: bytes) -> None:
    """装订对端证书 pin。

    文件名只取**裸主机**——读取侧（链路的 `build_link_ssl_context`、HTTPS 通道的
    `_resolve_tls`）都按裸 host 定位。两侧不一致时链路会拒绝拨号，而 HTTPS 会
    静默降级成 verify=False。取裸 host 也让 pin 与端口解耦：换端口不必重新装订。
    """

    host = bare_host(machine_ip)
    try:
        pin = _pin_file(host)
        pin.parent.mkdir(parents=True, exist_ok=True)
        pin.write_bytes(der_cert_to_pem(cert_der))
    except Exception as exc:
        logger.warning("register_machine: failed to persist pin file for %s: %s", host, exc)


def _persist_enrolled_machine(
    machine_name, machine_ip, machine_description, limits, uid, fingerprint, port=None,
) -> int:
    machine_type = MachineTypes.GPU if limits["gpu_number"] > 0 else MachineTypes.CPU
    try:
        with session_scope() as session:
            machine = machine_repo.create_machine(
                machinename=machine_name, machine_ip=machine_ip, machine_type=machine_type,
                machine_description=machine_description or f"enrolled via TOFU register ({machine_ip})",
                cpu_core_number=limits["cpu_core_number"], gpu_number=limits["gpu_number"],
                gpu_type=limits["gpu_type"], memory_size=limits["memory_size_gb"],
                max_shared_gb=2, disk_size=limits["disk_size_gb"],
                max_disk_size_gb=limits["disk_size_gb"], max_cpu_core_number=limits["max_cpu_core_number"],
                max_memory_gb=limits["max_memory_gb"], session=session,
            )
            machine_repo.update_machine(
                machine.id, node_uid=uid, node_cert_fingerprint=fingerprint,
                cert_pinned_at=datetime.datetime.utcnow(), session=session,
            )
            if port is not None:
                # 只在显式给了端口时写入：留空表示「回落全局默认」，不把当时的
                # 默认值固化进记录，否则日后调整全局默认对这台机器会静默失效。
                machine_repo.update_machine(machine.id, port=port, session=session)
            return machine.id
    except Exception as exc:
        raise NodeServiceError(
            f"register_machine failed: create/persist machine record: {exc}", reason="persist_failed",
        ) from exc
