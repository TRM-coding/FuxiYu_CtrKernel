import logging
import secrets

from ..extensions import session_scope
from datetime import datetime

from .rbac_service import _has_entity_direct, _has_resource_manage_direct
from ..repositories.machine_repo import *
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import String, cast, func, or_, select
from ..repositories import containers_repo, machine_permission_repo, user_repo
from .operation_log_tasks import log_failure, log_result, log_success
from ..constant import MachineStatus, OperationType
from ..models.machine import Machine
from .container_module.exceptions import NodeServiceError
from .container_module.node_comms_modules.enrollment import (
    _default_resource_limits,
    _fetch_enrollment_profile,
    _fetch_peer_cert,
    _validate_trust_anchor,
    _get_enrollment_client_cert,
    _request_enrollment_profile,
    _issue_node_uid,
    _persist_peer_pin,
    _persist_enrolled_machine,
)

logger = logging.getLogger(__name__)

#######################################
#API Definition
class machine_bref_information(BaseModel):
    id: int
    machine_name:str
    machine_ip:str
    machine_type:str
    machine_status:str
    is_maintenance: bool = False
    runtime_snapshot: dict | None = None

class machine_detail_information(BaseModel):
    machine_name:str
    machine_ip:str
    machine_type:str
    machine_status:str
    is_maintenance: bool = False
    cpu_core_number:int
    gpu_number:int
    gpu_type: Optional[str]
    gpu_list: Optional[list] = None
    gpu_allow_list: Optional[list] = None
    memory_size_gb:int
    max_shared_gb:int
    max_cpu_core_number:int
    max_gpu_number:int
    max_memory_gb:int
    max_disk_size_gb: Optional[int] = None
    disk_size_gb:int
    machine_description:str
    containers:list[int] # 容器 id
    runtime_snapshot: dict | None = None
#######################################

#######################################
# 机器权限管理

def _machine_log_detail(machine=None, *, machine_name=None, machine_ip=None, **extra) -> dict:
    name = machine_name if machine_name is not None else getattr(machine, "machine_name", None)
    ip = machine_ip if machine_ip is not None else getattr(machine, "machine_ip", None)
    detail = {
        "name": name,
        "machine_name": name,
        "ip": ip,
    }
    detail.update(extra)
    return detail


def Add_machine_permission(machine_id: int, user_id: int, operator_user_id: int | None = None) -> bool:
    machine = None
    user = None
    machine_name = None
    machine_ip = None
    try:
        with session_scope() as session:
            machine = get_by_id(machine_id, session=session)
            if not machine:
                raise ValueError('machine_not_found')
            machine_name = machine.machine_name
            machine_ip = machine.machine_ip
            user = user_repo.get_by_id(user_id, session=session)
            if not user:
                raise ValueError('user_not_found')
            machine_permission_repo.add_permission(machine_id, user_id, session=session)
    except Exception as e:
        log_failure(operator_user_id=operator_user_id, operation=OperationType.ADD_MACHINE_PERMISSION, target_type="machine",
                     target_id=machine_id,
                     detail=_machine_log_detail(
                         machine_name=machine_name,
                         machine_ip=machine_ip,
                         user_id=user_id,
                         username=getattr(user, "username", None),
                     ),
                     error_reason=getattr(e, 'reason', None) or str(e))
        raise
    log_success(operator_user_id=operator_user_id, operation=OperationType.ADD_MACHINE_PERMISSION, target_type="machine",
                 target_id=machine_id,
                 detail=_machine_log_detail(
                     machine_name=machine_name,
                     machine_ip=machine_ip,
                     user_id=user_id,
                     username=user.username,
                 ))
    return True


def Remove_machine_permission(machine_id: int, user_id: int, operator_user_id: int | None = None) -> bool:
    machine = None
    user = None
    machine_name = None
    machine_ip = None
    try:
        with session_scope() as session:
            machine = get_by_id(machine_id, session=session)
            machine_name = getattr(machine, "machine_name", None)
            machine_ip = getattr(machine, "machine_ip", None)
            user = user_repo.get_by_id(user_id, session=session)
            result = machine_permission_repo.remove_permission(machine_id, user_id, session=session)
    except Exception as exc:
        log_failure(operator_user_id=operator_user_id,
            operation=OperationType.REMOVE_MACHINE_PERMISSION,
            target_type="machine",
            target_id=machine_id,
            detail=_machine_log_detail(
                machine_name=machine_name,
                machine_ip=machine_ip,
                user_id=user_id,
                username=getattr(user, "username", None),
            ),
            error_reason=getattr(exc, "error_reason", None) or str(exc),
        )
        raise
    log_result(
        success=bool(result),
        operator_user_id=operator_user_id,
        operation=OperationType.REMOVE_MACHINE_PERMISSION,
        target_type="machine",
        target_id=machine_id,
        detail=_machine_log_detail(
            machine_name=machine_name,
            machine_ip=machine_ip,
            user_id=user_id,
            username=getattr(user, "username", None),
        ),
        error_reason=None if result else "remove_permission_failed",
    )
    return result


def List_machine_permissions(machine_id: int) -> list[int]:
    with session_scope(commit=False) as session:
        return machine_permission_repo.list_user_ids_by_machine(machine_id, session=session)


#######################################
# 辅助方法


def _machine_status_value(machine) -> str:
    """返回机器真实连接状态：online/offline。"""
    status = getattr(machine, "machine_status", None)
    return status.value if hasattr(status, "value") else str(status)


def refresh_unavailable_window(machine_id: int, *, session) -> None:
    """按机器当前可用状态刷新不可用窗口（须在状态已更新的同一 session 事务内调用）。

    窗口语义（清理顺延的公共地基）：不可用 = machine_status != ONLINE 或 is_maintenance。
    - 进入不可用且 unavailable_since 为空 → 置位 now（窗口起点取最早）
    - 恢复可用（窗口关闭）→ 把整段故障时长批量加到该机器全部 ssh deferral_seconds，
      再清空 unavailable_since——到期清理计时随之顺延（宕机/维护期不算用户责任）
    只应在 machine_status / is_maintenance 变化时调用；其它字段更新不触发，
    否则会把"早已离线"的机器误标成刚进窗。
    """
    machine = get_by_id(machine_id, session=session)
    if machine is None:
        return
    available = (
        _machine_status_value(machine) == MachineStatus.ONLINE.value
        and not getattr(machine, "is_maintenance", False)
    )
    since = getattr(machine, "unavailable_since", None)
    if not available:
        if since is None:
            machine.unavailable_since = datetime.utcnow()
            session.flush()
    else:
        if since is not None:
            delta = int((datetime.utcnow() - since).total_seconds())
            if delta > 0:
                from ..repositories import container_ssh_login_repo
                container_ssh_login_repo.add_deferral_seconds(machine_id, delta, session=session)
            machine.unavailable_since = None
            session.flush()


def is_machine_in_maintenance(machine_id: int) -> bool:
    """判断机器是否处于维护模式。"""
    try:
        with session_scope(commit=False) as session:
            machine = get_by_id(machine_id, session=session)
    except Exception:
        machine = None
    return bool(machine and getattr(machine, "is_maintenance", False))


def is_machine_collect_error(machine_id: int) -> bool:
    """判断机器是否处于采集异常（Node 无法采集容器状态，docker 卡死）——机器轴条件（契约 C1）。

    标志由 collect_error 帧置位、正常快照清除；容器 DB 状态保持最后已知值，展示派生 status_unknown。
    """
    try:
        with session_scope(commit=False) as session:
            machine = get_by_id(machine_id, session=session)
    except Exception:
        machine = None
    return bool(machine and getattr(machine, "collect_error_at", None))



def get_machine_reachable(machine_id: int, timeout: float = 2.0) -> bool:
    """读取机器连接状态。

    参数 timeout 保留兼容旧调用；本函数不再发起 HTTP 探活，避免列表/展示查询
    反向驱动 machine_status。
    """
    try:
        with session_scope(commit=False) as session:
            machine = get_by_id(machine_id, session=session)
    except Exception:
        machine = None
    return _machine_status_value(machine) == MachineStatus.ONLINE.value if machine else False

#######################################
#######################################
# 注册机器（TOFU 接入并建档）
def Register_machine(
    machine_name: str, machine_ip: str, machine_description: str = "", timeout: float = 8.0,
) -> dict:
    """Enroll a Node from the administrator's trust anchor, then persist its record.

    建档即完成接入：机器行落库后，链路进程的下一轮集合对齐会自行拨通它，
    注册流程不再需要任何重载动作。
    """
    from .container_module.node_comms import get_full_url

    _validate_trust_anchor(machine_name, machine_ip)
    client_cert = _get_enrollment_client_cert()
    try:
        fingerprint, cert_der = _fetch_peer_cert(machine_ip, timeout=timeout)
    except Exception as exc:
        raise NodeServiceError(
            f"register_machine failed: cannot reach {machine_ip} over TLS: {exc}", reason="machine_unreachable",
        ) from exc
    hardware = _request_enrollment_profile(
        get_full_url(machine_ip, "/node_identity/enrollment_profile"), machine_ip, client_cert, timeout,
    )
    uid = secrets.token_urlsafe(24)
    _issue_node_uid(get_full_url(machine_ip, "/node_identity/issue_uid"), machine_ip, uid, client_cert, timeout)
    _persist_peer_pin(machine_ip, cert_der)
    machine_id = _persist_enrolled_machine(
        machine_name, machine_ip, machine_description, _default_resource_limits(hardware), uid, fingerprint,
    )
    logger.info(
        "machine %s (%s) enrolled: id=%s uid=%s fingerprint=%s hardware=%s",
        machine_name, machine_ip, machine_id, uid, fingerprint, hardware,
    )
    return {
        "success": True, "uid": uid, "certificate_fingerprint": fingerprint,
        "machine_id": machine_id, "hardware": hardware,
    }

#######################################
#######################################
# 重新钉信任锚（对已登记机器的连接修复）
def Renew_machine_trust(machine_id: int, operator_user_id: int | None = None, timeout: float = 8.0) -> dict:
    """重新建立与已登记机器的连接信任 —— 只 UPDATE，不增删机器行。

    适用场景：Node 重新生成过自签证书（例如主机名变化触发 SAN 校验失败，
    ensure_self_signed_certificate 会静默重生成），本地 pin 随之作废、链路报
    SSLCertVerificationError；而机器本身、容器与 uid 都没有变，坏的只是
    「连接能力」。此时重新注册走不通（machine_ip/machine_name 唯一约束），
    删行也被容器守卫挡住 —— 本函数就是那条缺失的出路。

    语义边界：
    - register 是 INSERT（建档），本函数是 UPDATE（换信任锚），二者不重叠；
      本函数不写 machine_name / machine_ip，因此不可能触发唯一约束
    - 「随时可按」的前提是先取证后落地：抓不到对端证书即整体失败返回，
      pin 与全部凭证字段保持原值（绝不在没拿到新证据时就毁掉旧信任）
    - uid 只在必要时动：对端丢了身份牌才重发；库里本无 uid 才对端自报一个
      （Ctrl 在那行上没有主张，不算覆盖）；两者都有则保持不动，只把不一致
      报出来由人判断
    """
    from .container_module.node_comms import get_full_url

    with session_scope(commit=False) as session:
        machine = get_by_id(machine_id, session=session)
        if machine is None:
            log_failure(
                operator_user_id=operator_user_id,
                operation=OperationType.RENEW_MACHINE_TRUST,
                target_type="machine",
                target_id=machine_id,
                detail={"machine_id": machine_id},
                error_reason="machine_not_found",
            )
            raise NodeServiceError(
                f"renew_machine_trust failed: machine {machine_id} not found", reason="machine_not_found",
            )
        machine_name = machine.machine_name
        machine_ip = machine.machine_ip
        previous_fingerprint = machine.node_cert_fingerprint
        previous_uid = machine.node_uid

    detail = _machine_log_detail(machine_name=machine_name, machine_ip=machine_ip)
    if not machine_ip:
        log_failure(
            operator_user_id=operator_user_id, operation=OperationType.RENEW_MACHINE_TRUST,
            target_type="machine", target_id=machine_id, detail=detail, error_reason="invalid_machine_ip",
        )
        raise NodeServiceError(
            f"renew_machine_trust failed: machine {machine_id} has no machine_ip", reason="invalid_machine_ip",
        )

    def _fail(reason: str, message: str) -> None:
        log_failure(
            operator_user_id=operator_user_id, operation=OperationType.RENEW_MACHINE_TRUST,
            target_type="machine", target_id=machine_id, detail=detail, error_reason=reason,
        )
        raise NodeServiceError(message, reason=reason)

    # ── 阶段一：取齐全部对端证据。任何一步失败都在改动本地状态之前退出 ──
    client_cert = _get_enrollment_client_cert()
    try:
        fingerprint, cert_der = _fetch_peer_cert(machine_ip, timeout=timeout)
    except Exception as exc:
        _fail("machine_unreachable", f"renew_machine_trust failed: cannot reach {machine_ip} over TLS: {exc}")

    try:
        profile = _fetch_enrollment_profile(
            get_full_url(machine_ip, "/node_identity/enrollment_profile"),
            machine_ip, client_cert, timeout, context="renew_machine_trust",
        )
    except Exception as exc:
        _fail("enrollment_failed", f"renew_machine_trust failed: {exc}")

    identity_initialized = bool(profile.get("identity_initialized"))
    reported_uid = profile.get("uid")

    # uid 先下发、后落库：反过来的顺序若本地写成功而下发失败，DB 与 Node 会永久
    # 错位（Node 仍持旧牌 → identity_initialized 为真 → 再按也不会重发）。
    new_uid = previous_uid
    uid_reissued = False
    uid_adopted = False
    if not identity_initialized:
        new_uid = secrets.token_urlsafe(24)
        try:
            _issue_node_uid(
                get_full_url(machine_ip, "/node_identity/issue_uid"),
                machine_ip, new_uid, client_cert, timeout,
            )
        except Exception as exc:
            _fail("issue_uid_failed", f"renew_machine_trust failed: cannot issue uid to {machine_ip}: {exc}")
        uid_reissued = True
    elif not previous_uid and reported_uid:
        new_uid = reported_uid
        uid_adopted = True

    # ── 阶段二：到这里才动本地状态 ──
    _persist_peer_pin(machine_ip, cert_der)
    try:
        with session_scope() as session:
            update_machine(
                machine_id,
                node_cert_fingerprint=fingerprint,
                cert_pinned_at=datetime.utcnow(),
                node_uid=new_uid,
                session=session,
            )
    except Exception as exc:
        _fail("persist_failed", f"renew_machine_trust failed: persist machine {machine_id}: {exc}")

    uid_mismatch = bool(previous_uid and reported_uid and previous_uid != reported_uid)
    if uid_mismatch:
        logger.warning(
            "renew_machine_trust: machine %s uid mismatch (db=%s node=%s); kept db value",
            machine_id, previous_uid, reported_uid,
        )

    log_success(
        operator_user_id=operator_user_id, operation=OperationType.RENEW_MACHINE_TRUST,
        target_type="machine", target_id=machine_id,
        detail={
            **detail,
            "trigger": "manual_renew",
            "fingerprint_before": previous_fingerprint,
            "fingerprint_after": fingerprint,
            "uid_reissued": uid_reissued,
            "uid_adopted": uid_adopted,
            "uid_mismatch": uid_mismatch,
        },
    )
    logger.info(
        "machine %s (%s) trust renewed: uid_reissued=%s uid_adopted=%s uid_mismatch=%s fingerprint=%s",
        machine_name, machine_ip, uid_reissued, uid_adopted, uid_mismatch, fingerprint,
    )
    return {
        "success": True,
        "machine_id": machine_id,
        "machine_name": machine_name,
        "machine_ip": machine_ip,
        "certificate_fingerprint": fingerprint,
        "previous_certificate_fingerprint": previous_fingerprint,
        "uid": new_uid,
        "uid_reissued": uid_reissued,
        "uid_adopted": uid_adopted,
        "uid_mismatch": uid_mismatch,
    }

#######################################


#######################################
# 删除集群中的一个（一组）机器
def Remove_machine(machine_id:list[int], operator_user_id: int | None = None)->dict:
    """删除一组机器记录。

    2026-09 决策：机器上仍有容器 → 拒绝删除该台并提示先手动清理（不自动级联删
    物理容器——删除不可被机器记录删除捎带触发）。返回 {"removed": [id], "blocked": [...]}。
    """
    removed: list[int] = []
    blocked: list[dict] = []
    for id in machine_id:
        machine = None
        ok = False
        err = None
        try:
            with session_scope() as session:
                machine = get_by_id(id, session=session)
                if machine is None:
                    err = "not_found"
                else:
                    count = containers_repo.count_containers(machine_id=id, session=session)
                    if count > 0:
                        blocked.append({"machine_id": id, "name": machine.machine_name, "container_count": count})
                        err = "machine_has_containers"
                    else:
                        ok = delete_machine(id, session=session)
                        err = None if ok else "delete_failed"
        except Exception as e:
            ok = False
            err = getattr(e, 'reason', None) or str(e)
        if ok:
            removed.append(id)
        log_result(success=bool(ok), operator_user_id=operator_user_id, operation=OperationType.REMOVE_MACHINE, target_type="machine", target_id=id,
                     detail=_machine_log_detail(machine),
                     error_reason=err)
    return {"removed": removed, "blocked": blocked}
#######################################


#######################################
# 更新机器信息
def Update_machine(machine_id: int, operator_user_id: int | None = None, **fields) -> bool:
    with session_scope(commit=False) as session:
        machine = get_by_id(machine_id, session=session)
    if not machine:
        log_failure(operator_user_id=operator_user_id,
            operation=OperationType.UPDATE_MACHINE,
            target_type="machine",
            target_id=machine_id,
            detail=_machine_log_detail(machine),
            error_reason="machine_not_found",
        )
        return False

    # validate shared_size when provided: must be integer and <= 8 GB
    if 'shared_size' in fields or 'shared_gb' in fields or 'max_shared_gb' in fields:
        # prefer explicit max_shared_gb field when present
        ss_val = None
        if 'max_shared_gb' in fields:
            ss_val = fields.get('max_shared_gb')
        else:
            ss_val = fields.get('shared_size') if 'shared_size' in fields else fields.get('shared_gb')
        try:
            ss = int(ss_val) if ss_val is not None else None
        except Exception:
            e = ValueError(f"shared_size must be an integer: {ss_val}")
            setattr(e, 'error_reason', 'update_failed')
            raise e
        if ss is not None and (ss < 0 or ss > 8):
            e = ValueError(f"shared_size out of range (0-8 GB): {ss}")
            setattr(e, 'error_reason', 'update_failed')
            raise e

        # if max_shared_gb provided, ensure it does not exceed updated or current max_memory_gb
        if 'max_shared_gb' in fields:
            try:
                target_max_mem = None
                if 'max_memory_gb' in fields:
                    target_max_mem = int(fields.get('max_memory_gb')) if fields.get('max_memory_gb') is not None else None
                else:
                    target_max_mem = int(getattr(machine, 'max_memory_gb', None)) if getattr(machine, 'max_memory_gb', None) is not None else None
            except Exception:
                e = ValueError(f"max_memory_gb must be an integer when validating max_shared_gb")
                setattr(e, 'error_reason', 'update_failed')
                raise e
            if target_max_mem is not None and ss is not None and ss > target_max_mem:
                e = ValueError(f"max_shared_gb ({ss}) cannot be greater than max_memory_gb ({target_max_mem})")
                setattr(e, 'error_reason', 'update_failed')
                raise e

    # 维护态为纯开关；machine_status 直接表达真实连接状态。
    # 字段名翻译：前端 disk_size -> 模型 disk_size_gb。
    if 'disk_size' in fields:
        fields['disk_size_gb'] = fields.pop('disk_size')

    # IP 变更自愈（2026-09）：新 IP 首连 + 证书指纹比对——同一证书换 IP → 自动导出新 pin；
    # 指纹不匹配（证书也换了）→ 拒绝，防机器记录被劫持到攻击者机器。
    new_ip = str(fields.get('machine_ip') or '').strip() if fields.get('machine_ip') is not None else None
    if new_ip and new_ip != getattr(machine, 'machine_ip', None):
        from ..utils.cert_utils import der_cert_to_pem
        from .container_module.node_comms import _fetch_peer_cert, _pin_file

        try:
            fingerprint, cert_der = _fetch_peer_cert(new_ip)
        except Exception as e:
            err = ValueError(f"machine_ip change failed: cannot reach {new_ip} over TLS: {e}")
            setattr(err, 'error_reason', 'ip_change_unreachable')
            raise err
        expected = getattr(machine, 'node_cert_fingerprint', None)
        if not expected or fingerprint != expected:
            err = ValueError(f"machine_ip change refused: {new_ip} presents a different certificate (re-register instead)")
            setattr(err, 'error_reason', 'ip_change_fingerprint_mismatch')
            raise err
        # 同一证书换 IP → 导出新 pin（Ctrl→Node 链路按 IP 取信任锚）；
        # 链路进程下一轮集合对齐会按新 IP 重拨，无需重载任何服务端上下文。
        try:
            pin_path = _pin_file(new_ip)
            pin_path.parent.mkdir(parents=True, exist_ok=True)
            pin_path.write_bytes(der_cert_to_pem(cert_der))
        except Exception as e:  # pragma: no cover
            print(f"[machine-ip-change] pin export failed for {new_ip}: {e}")
        fields['machine_ip'] = new_ip
    if str(fields.get('machine_status', '')).lower() == "maintenance":
        raise ValueError("machine_status no longer accepts maintenance; use is_maintenance")
    if 'is_maintenance' in fields:
        fields['is_maintenance'] = bool(fields['is_maintenance'])

    before = {k: str(getattr(machine, k, None)) for k in fields.keys()}
    # 状态类字段变化 → 同一事务内刷新不可用窗口（离线/维护进窗，恢复出窗顺延清理计时）
    state_changed = ("machine_status" in fields) or ("is_maintenance" in fields)
    try:
        with session_scope() as session:
            update_machine(machine_id, session=session, **fields)
            if state_changed:
                refresh_unavailable_window(machine_id, session=session)
    except Exception as e:
        log_failure(operator_user_id=operator_user_id, operation=OperationType.UPDATE_MACHINE, target_type="machine", target_id=machine_id,
                     detail=_machine_log_detail(machine, before=before, after={k: str(v) for k, v in fields.items()}),
                     error_reason=getattr(e, 'error_reason', None) or str(e))
        raise
    log_success(operator_user_id=operator_user_id, operation=OperationType.UPDATE_MACHINE, target_type="machine", target_id=machine_id,
                 detail=_machine_log_detail(machine, before=before, after={k: str(v) for k, v in fields.items()}))
    return True


def Set_maintenance(machine_id: int, is_maintenance: bool, operator_user_id: int | None = None) -> bool:
    """设置机器维护开关；真实在线/离线状态仍由连接状态维护。"""

    with session_scope(commit=False) as session:
        machine = get_by_id(machine_id, session=session)
        if not machine:
            log_failure(operator_user_id=operator_user_id,
                operation=OperationType.UPDATE_MACHINE,
                target_type="machine",
                target_id=machine_id,
                detail=_machine_log_detail(machine, field="is_maintenance"),
                error_reason="machine_not_found",
            )
            return False
        before = {"is_maintenance": bool(getattr(machine, "is_maintenance", False))}

    after = {"is_maintenance": bool(is_maintenance)}
    try:
        with session_scope() as session:
            ok = set_maintenance(machine_id, bool(is_maintenance), session=session)
            # 维护开关变化 = 可用性变化：同一事务内刷新不可用窗口（开维护进窗 / 关维护出窗顺延）
            if ok:
                refresh_unavailable_window(machine_id, session=session)
    except Exception as e:
        log_failure(operator_user_id=operator_user_id,
            operation=OperationType.UPDATE_MACHINE,
            target_type="machine",
            target_id=machine_id,
            detail=_machine_log_detail(machine, before=before, after=after, field="is_maintenance"),
            error_reason=getattr(e, "error_reason", None) or str(e),
        )
        raise

    log_result(
        success=bool(ok),
        operator_user_id=operator_user_id,
        operation=OperationType.UPDATE_MACHINE,
        target_type="machine",
        target_id=machine_id,
        detail=_machine_log_detail(machine, before=before, after=after, field="is_maintenance"),
        error_reason=None if ok else "machine_not_found",
    )
    return bool(ok)


#######################################


#######################################
# 根据机器 ID 获取机器详情
def Get_detail_information(machine_id:int)->machine_detail_information|None:
    with session_scope(commit=False) as session:
        machine = get_by_id(machine_id, session=session)
        if not machine:
            return None
        container_ids = [container.id for container in machine.containers]
        from .container_module.node_comms import get_cached_machine_runtime_snapshot
        return machine_detail_information(
            machine_name=machine.machine_name,
            machine_ip=machine.machine_ip,
            machine_type=machine.machine_type.value,
            machine_status=_machine_status_value(machine),
            is_maintenance=bool(getattr(machine, "is_maintenance", False)),
            cpu_core_number=machine.cpu_core_number,
            gpu_number=machine.gpu_number,
            gpu_type=machine.gpu_type,
            gpu_list=machine.gpu_list,
            gpu_allow_list=machine.gpu_allow_list,
            memory_size_gb=machine.memory_size_gb,
            max_shared_gb=machine.max_shared_gb,
            max_cpu_core_number=machine.max_cpu_core_number,
            max_gpu_number=machine.max_gpu_number,
            max_memory_gb=machine.max_memory_gb,
            max_disk_size_gb=machine.max_disk_size_gb,
            disk_size_gb=machine.disk_size_gb,
            machine_description=machine.machine_description,
            containers=container_ids,
            runtime_snapshot=get_cached_machine_runtime_snapshot(machine.id),
        )
#######################################

# 获取一批机器的概要信息
def List_all_machine_bref_information(
    page_number: int,
    page_size: int,
    machine_name_prefix: str = None,
    sort_by: str = "id",
    sort_order: str = "asc",
    user_id: int | None = None,
    machine_search: str | None = None,
) -> tuple[list[machine_bref_information], int]:
    with session_scope(commit=False) as session:
        stmt = select(Machine)
        if machine_name_prefix:
            stmt = stmt.where(Machine.machine_name.like(f"{machine_name_prefix}%"))
        if machine_search:
            keyword = f"%{machine_search.strip()}%"
            stmt = stmt.where(
                or_(
                    Machine.machine_name.ilike(keyword),
                    Machine.machine_ip.ilike(keyword),
                    cast(Machine.id, String).ilike(keyword),
                )
            )
        # 资源级集合过滤：无通配（bypass_resource / machine:manage）的用户只看有访问权的机器
        if user_id and not _has_resource_manage_direct(user_id, "machine") and not _has_entity_direct(user_id, "bypass_resource"):
            allowed = set(machine_permission_repo.list_machine_ids_by_user(user_id, session=session))
            stmt = stmt.where(Machine.id.in_(allowed)) if allowed else stmt.where(False)

        sort_column = {
            "id": Machine.id,
            "machine_name": Machine.machine_name,
            "machine_ip": Machine.machine_ip,
        }.get(sort_by, Machine.id)
        stmt = stmt.order_by(sort_column.desc() if sort_order == "desc" else sort_column.asc())

        total_count = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        machines = list(
            session.scalars(
                stmt.limit(page_size).offset(page_number * page_size)
            ).all()
        )
    
    from .container_module.node_comms import get_cached_machine_runtime_snapshot

    res = []
    for machine in machines:
        info = machine_bref_information(
            id=machine.id,
            machine_name=machine.machine_name,
            machine_ip=machine.machine_ip,
            machine_type=machine.machine_type.value,
            machine_status=_machine_status_value(machine),
            is_maintenance=bool(getattr(machine, "is_maintenance", False)),
            runtime_snapshot=get_cached_machine_runtime_snapshot(machine.id),
        )
        res.append(info)
    
    total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0
    
    return res, total_pages
#######################################
