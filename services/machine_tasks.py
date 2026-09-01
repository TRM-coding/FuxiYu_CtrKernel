from ..extensions import session_scope

from .rbac_service import _has_entity_direct, _has_resource_manage_direct
from ..repositories.machine_repo import *
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import String, cast, func, or_, select
from ..repositories import containers_repo, machine_permission_repo, user_repo
from .operation_log_tasks import write_operation_log as write_op_log
from ..constant import MachineStatus, OperationType
from ..models.machine import Machine
MACHINE_DISPLAY_MAINTENANCE = "maintenance"
MACHINE_DISPLAY_COLLECT_ERROR = "collect_error"
#######################################
#API Definition
class machine_bref_information(BaseModel):
    id: int
    machine_name:str
    machine_ip:str
    machine_type:str
    machine_status:str
    is_maintenance: bool = False
    display_status: str | None = None

class machine_detail_information(BaseModel):
    machine_name:str
    machine_ip:str
    machine_type:str
    machine_status:str
    is_maintenance: bool = False
    display_status: str | None = None
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

def Add_machine_permission(machine_id: int, user_id: int, operator_user_id: int | None = None) -> bool:
    try:
        with session_scope() as session:
            machine = get_by_id(machine_id, session=session)
            if not machine:
                raise ValueError('machine_not_found')
            user = user_repo.get_by_id(user_id, session=session)
            if not user:
                raise ValueError('user_not_found')
            machine_permission_repo.add_permission(machine_id, user_id, session=session)
    except Exception as e:
        write_op_log(success=False, operator_user_id=operator_user_id, operation=OperationType.ADD_MACHINE_PERMISSION, target_type="machine",
                     target_id=machine_id, detail={"user_id": user_id},
                     error_reason=getattr(e, 'reason', None) or str(e))
        raise
    write_op_log(success=True, operator_user_id=operator_user_id, operation=OperationType.ADD_MACHINE_PERMISSION, target_type="machine",
                 target_id=machine_id, detail={"user_id": user_id, "username": user.username})
    return True


def Remove_machine_permission(machine_id: int, user_id: int, operator_user_id: int | None = None) -> bool:
    with session_scope() as session:
        result = machine_permission_repo.remove_permission(machine_id, user_id, session=session)
    write_op_log(success=bool(result), operator_user_id=operator_user_id, operation=OperationType.REMOVE_MACHINE_PERMISSION, target_type="machine",
                 target_id=machine_id, detail={"user_id": user_id},
                 error_reason=None if result else "remove_permission_failed")
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


def _display_machine_status(machine) -> str:
    """返回对外展示状态；维护开关优先，采集异常次之（仅在线时），真实连接状态保留在 DB。"""
    if bool(getattr(machine, "is_maintenance", False)):
        return MACHINE_DISPLAY_MAINTENANCE
    status = _machine_status_value(machine)
    if status == MachineStatus.ONLINE.value and getattr(machine, "collect_error_at", None):
        return MACHINE_DISPLAY_COLLECT_ERROR
    return status


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

def is_machine_online_remote(machine_id: int, timeout: float = 2.0) -> bool:
    """
    Perform a single, lightweight communication check to the Node's `/machine_status` endpoint.
    Returns True if Node responds with success==1 and machine_status == 'online'.
    This function does NOT update DB state or perform additional logic; callers should handle
    persistence or other decisions.
    """
    try:
        with session_scope(commit=False) as session:
            m = get_by_id(machine_id, session=session)
    except Exception:
        m = None
    if not m:
        return False
    machine_ip = getattr(m, 'machine_ip', None)
    if not machine_ip:
        return False

    try:
        from ..services.container_module import node_comms
        j = node_comms.send(
            node_comms.get_full_url(machine_ip, "/machine_status"),
            {"config": {}},
            timeout=timeout,
        )
    except Exception:
        return False
    if isinstance(j, dict) and j.get('success') in (1, True):
        ms = (j.get('machine_status') or '').lower()
        return ms == 'online'
    return False


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
# 添加一个新的机器到集群
def Add_machine(machine_name:str,
                   machine_ip:str,
                   machine_type:MachineTypes,
                   machine_description:str,
                   cpu_core_number:int,
                   gpu_number:int,
                   gpu_type:str,
                   memory_size:int,
                   max_shared_gb:int,
                   disk_size:int,
                   max_memory_gb:int,
                   max_gpu_number:int,
                   max_cpu_core_number:int,
                   operator_user_id: int | None = None)->bool:
    # 防御性检查：限制字段长度，防止过长输入导致数据库异常
    if machine_name and len(machine_name) > 115:
        raise ValueError(f"machine_name too long (max 115): length={len(machine_name)}")
    if gpu_type and len(str(gpu_type)) > 115:
        raise ValueError(f"gpu_type too long (max 115): length={len(str(gpu_type))}")
    if machine_type and len(str(machine_type)) > 255:
        raise ValueError(f"machine_type too long (max 255): length={len(str(machine_type))}")

    # max_shared_gb defensive check: must be non-negative integer and <= 8 (GB)
    if max_shared_gb is not None:
        try:
            ss = int(max_shared_gb)
        except Exception:
            e = ValueError(f"max_shared_gb must be an integer: {max_shared_gb}")
            setattr(e, 'error_reason', 'create_failed')
            raise e
        if ss <= 0:
            e = ValueError(f"shared size out of range (0-8 GB): {ss}")
            setattr(e, 'error_reason', 'create_failed')
            raise e

        # ensure machine max_shared does not exceed machine max_memory
        try:
            mm = int(max_memory_gb) if max_memory_gb is not None else None
        except Exception:
            e = ValueError(f"max_memory_gb must be an integer: {max_memory_gb}")
            setattr(e, 'error_reason', 'create_failed')
            raise e
        if mm is not None and ss > mm:
            e = ValueError(f"max_shared_gb ({ss}) cannot be greater than max_memory_gb ({mm})")
            setattr(e, 'error_reason', 'create_failed')
            raise e

    try:
        with session_scope() as session:
            machine = create_machine(
                machinename=machine_name,
                machine_ip=machine_ip,
                machine_type=machine_type,
                machine_description=machine_description,
                cpu_core_number=cpu_core_number,
                gpu_number=gpu_number,
                gpu_type=gpu_type,
                memory_size=memory_size,
                max_shared_gb=max_shared_gb,
                disk_size=disk_size,
                max_memory_gb=max_memory_gb,
                max_gpu_number=max_gpu_number,
                max_cpu_core_number=max_cpu_core_number,
                max_disk_size_gb=disk_size,
                session=session,
            )
    except Exception as e:
        write_op_log(success=False, operator_user_id=operator_user_id, operation=OperationType.ADD_MACHINE, target_type="machine", target_id=0,
                     detail={"name": machine_name, "ip": machine_ip},
                     error_reason=getattr(e, 'error_reason', None) or str(e))
        raise
    write_op_log(success=True, operator_user_id=operator_user_id, operation=OperationType.ADD_MACHINE, target_type="machine", target_id=machine.id,
                 detail={"name": machine_name, "ip": machine_ip})
    return True

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
        write_op_log(success=bool(ok), operator_user_id=operator_user_id, operation=OperationType.REMOVE_MACHINE, target_type="machine", target_id=id,
                     detail={
                         "name": getattr(machine, 'machine_name', None),
                         "ip": getattr(machine, 'machine_ip', None),
                     },
                     error_reason=err)
    return {"removed": removed, "blocked": blocked}
#######################################


#######################################
# 更新机器信息
def Update_machine(machine_id: int, operator_user_id: int | None = None, **fields) -> bool:
    with session_scope(commit=False) as session:
        machine = get_by_id(machine_id, session=session)
    if not machine:
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
        from .container_module.node_comms import _fetch_peer_cert, _pin_file, request_wss_restart

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
        # 同一证书换 IP → 导出新 pin + 重建 WSS pin bundle（Node→Ctrl WSS 校验链）
        try:
            pin_path = _pin_file(new_ip)
            pin_path.parent.mkdir(parents=True, exist_ok=True)
            pin_path.write_bytes(der_cert_to_pem(cert_der))
            request_wss_restart("pin_bundle_changed")
        except Exception as e:  # pragma: no cover
            print(f"[machine-ip-change] pin export failed for {new_ip}: {e}")
        fields['machine_ip'] = new_ip
    if str(fields.get('machine_status', '')).lower() == MACHINE_DISPLAY_MAINTENANCE:
        raise ValueError("machine_status no longer accepts maintenance; use is_maintenance")
    if 'is_maintenance' in fields:
        fields['is_maintenance'] = bool(fields['is_maintenance'])

    before = {k: str(getattr(machine, k, None)) for k in fields.keys()}
    try:
        with session_scope() as session:
            update_machine(machine_id, session=session, **fields)
    except Exception as e:
        write_op_log(success=False, operator_user_id=operator_user_id, operation=OperationType.UPDATE_MACHINE, target_type="machine", target_id=machine_id,
                     detail={"before": before, "after": {k: str(v) for k, v in fields.items()}},
                     error_reason=getattr(e, 'error_reason', None) or str(e))
        raise
    write_op_log(success=True, operator_user_id=operator_user_id, operation=OperationType.UPDATE_MACHINE, target_type="machine", target_id=machine_id,
                 detail={"before": before, "after": {k: str(v) for k, v in fields.items()}})
    return True


def Set_maintenance(machine_id: int, is_maintenance: bool, operator_user_id: int | None = None) -> bool:
    """设置机器维护开关；真实在线/离线状态仍由连接状态维护。"""

    with session_scope(commit=False) as session:
        machine = get_by_id(machine_id, session=session)
        if not machine:
            return False
        before = {"is_maintenance": bool(getattr(machine, "is_maintenance", False))}

    after = {"is_maintenance": bool(is_maintenance)}
    try:
        with session_scope() as session:
            ok = set_maintenance(machine_id, bool(is_maintenance), session=session)
    except Exception as e:
        write_op_log(
            success=False,
            operator_user_id=operator_user_id,
            operation=OperationType.UPDATE_MACHINE,
            target_type="machine",
            target_id=machine_id,
            detail={"before": before, "after": after, "field": "is_maintenance"},
            error_reason=getattr(e, "error_reason", None) or str(e),
        )
        raise

    write_op_log(
        success=bool(ok),
        operator_user_id=operator_user_id,
        operation=OperationType.UPDATE_MACHINE,
        target_type="machine",
        target_id=machine_id,
        detail={"before": before, "after": after, "field": "is_maintenance"},
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
            display_status=_display_machine_status(machine),
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
    
    res = []
    for machine in machines:
        info = machine_bref_information(
            id=machine.id,
            machine_name=machine.machine_name,
            machine_ip=machine.machine_ip,
            machine_type=machine.machine_type.value,
            machine_status=_machine_status_value(machine),
            is_maintenance=bool(getattr(machine, "is_maintenance", False)),
            display_status=_display_machine_status(machine),
        )
        res.append(info)
    
    total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0
    
    return res, total_pages
#######################################
