from ..config import AppConfig
from ..extensions import session_scope

import threading
import time

from ..repositories.machine_repo import *
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import func, select
from ..utils.parallel import parallel_node_calls
from ..repositories import machine_permission_repo, user_repo
from .operation_log_tasks import write_operation_log as write_op_log
from ..constant import MachineStatus, OperationType
from ..models.machine import Machine
MACHINE_DISPLAY_MAINTENANCE = "maintenance"
#######################################
#API Definition
class machine_bref_information(BaseModel):
    id: int  #没想到更好的解决办法。主要作为各种操作的映射。
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
    gpu_type: Optional[str] # 部分sql数据会出现此字段是NULL的情况，因此暂时用这个方法解决
    memory_size_gb:int
    max_shared_gb:int
    max_cpu_core_number:int
    max_gpu_number:int
    max_memory_gb:int
    disk_size_gb:int
    machine_description:str
    containers:list[int] #容器id
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

def _is_operator_user(user_id: int) -> bool:
    try:
        with session_scope(commit=False) as session:
            u = user_repo.get_by_id(user_id, session=session)
        perm = getattr(u, 'permission', None) if u else None
        return bool(perm and getattr(perm, 'value', str(perm)).lower() == 'operator')
    except Exception:
        return False


def _machine_status_value(machine) -> str:
    """返回机器真实连接状态轴：online/offline。"""
    status = getattr(machine, "machine_status", None)
    return status.value if hasattr(status, "value") else str(status)


def _display_machine_status(machine) -> str:
    """返回对外展示状态：维护开关优先，真实连接状态仍保留在 DB。"""
    if bool(getattr(machine, "is_maintenance", False)):
        return MACHINE_DISPLAY_MAINTENANCE
    return _machine_status_value(machine)


def is_machine_in_maintenance(machine_id: int) -> bool:
    """供操作准入和容器派生展示态复用的维护开关判断。"""
    try:
        with session_scope(commit=False) as session:
            machine = get_by_id(machine_id, session=session)
    except Exception:
        machine = None
    return bool(machine and getattr(machine, "is_maintenance", False))

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

    # 延迟 import：node_comms 顶层依赖本模块（is_machine_online_remote），顶层互引会循环
    from ..services.container_module.node_comms import get_full_url, send
    try:
        j = send(get_full_url(machine_ip, "/machine_status"), {"config": {}}, timeout=timeout)
    except Exception:
        return False
    if isinstance(j, dict) and j.get('success') in (1, True):
        ms = (j.get('machine_status') or '').lower()
        return ms == 'online'
    return False


# ── 机器可达性统一入口（TTL 缓存） ──────────────────────────
# 所有需要"机器现在通不通"的地方都走这里（容器展示态派生、操作前置检查等）。
# 唯一做 HTTP 探测的地方；WSS 落地后此入口改读连接状态，调用方无感。
_reach_cache: dict[int, tuple[float, bool]] = {}
_reach_cache_lock = threading.Lock()
REACH_CACHE_TTL_SEC = 20.0


def _peek_machine_reachable(machine_id: int) -> bool | None:
    """缓存未过期返回结果，否则 None。"""
    now = time.time()
    with _reach_cache_lock:
        hit = _reach_cache.get(machine_id)
    if hit and (now - hit[0]) < REACH_CACHE_TTL_SEC:
        return hit[1]
    return None


def _set_machine_reachable(machine_id: int, ok: bool) -> None:
    with _reach_cache_lock:
        _reach_cache[machine_id] = (time.time(), bool(ok))


def get_machine_reachable(machine_id: int, timeout: float = 2.0) -> bool:
    """机器可达性统一入口：命中 TTL 缓存零 HTTP，未命中探测一次并写缓存。"""
    cached = _peek_machine_reachable(machine_id)
    if cached is not None:
        return cached
    ok = is_machine_online_remote(machine_id, timeout=timeout)
    _set_machine_reachable(machine_id, ok)
    return ok

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
def Remove_machine(machine_id:list[int], operator_user_id: int | None = None)->bool:
    for id in machine_id:
        machine = None
        try:
            with session_scope() as session:
                machine = get_by_id(id, session=session)
                ok = delete_machine(id, session=session)
            err = None if ok else "delete_failed"
        except Exception as e:
            ok = False
            err = getattr(e, 'reason', None) or str(e)
        write_op_log(success=bool(ok), operator_user_id=operator_user_id, operation=OperationType.REMOVE_MACHINE, target_type="machine", target_id=id,
                     detail={
                         "name": getattr(machine, 'machine_name', None),
                         "ip": getattr(machine, 'machine_ip', None),
                     },
                     error_reason=err)
    return True
#######################################


#######################################
# 更新机器的信息
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

    # 维护态为纯开关（维护不触发停容器，状态机落地后由 set_maintenance 承载）；
    # machine_status 变更直接更新，不再启动过渡心跳。

    # 字段名翻译: 前端 disk_size → 模型 disk_size_gb
    if 'disk_size' in fields:
        fields['disk_size_gb'] = fields.pop('disk_size')
    if str(fields.get('machine_status', '')).lower() == MACHINE_DISPLAY_MAINTENANCE:
        raise ValueError("machine_status no longer accepts maintenance; use is_maintenance")
    if 'is_maintenance' in fields:
        fields['is_maintenance'] = bool(fields['is_maintenance'])

    # 记录前值：repo 已原子化，update 前从 machine 对象取旧值即可
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
    """设置机器维护开关；真实在线/离线状态仍由连接状态机维护。"""

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
# 根据机器ID获取机器的详细信息
def Get_detail_information(machine_id:int)->machine_detail_information|None:
    with session_scope(commit=False) as session:
        machine = get_by_id(machine_id, session=session)
        if not machine:
            return None
        container_ids = [container.id for container in machine.containers]
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
            memory_size_gb=machine.memory_size_gb,
            max_shared_gb=machine.max_shared_gb,
            max_cpu_core_number=machine.max_cpu_core_number,
            max_gpu_number=machine.max_gpu_number,
            max_memory_gb=machine.max_memory_gb,
            disk_size_gb=machine.disk_size_gb,
            machine_description=machine.machine_description,
            containers=container_ids,
        )
#######################################

#######################################
def _node_probe_machine(machine_id: int, _app=None) -> bool:
    """封装单次 NodeKernel /machine_status 可达性检查。

    等同于原 for 循环内的 ``is_machine_online_remote(machine_id, timeout=2.0)``，
    抽取为独立函数以适配 ``parallel_node_calls``。

    *_app* 参数保留兼容旧调用，不再使用。
    """
    try:
        return is_machine_online_remote(machine_id, timeout=2.0)
    except Exception:
        return False


# 获取一批机器的概要信息
def List_all_machine_bref_information(
    page_number: int, 
    page_size: int,
    machine_name_prefix: str = None,  # 新增：按机器名称前缀过滤
    sort_by: str = "id",              # 新增：排序字段
    sort_order: str = "asc",          # 新增：排序方向（asc/desc）
    user_id: int | None = None
) -> tuple[list[machine_bref_information], int]:
    """
    获取机器概要信息列表，支持分页、过滤和排序
    
    Args:
        page_number: 页码（从0开始）
        page_size: 每页条数
        machine_name_prefix: 机器名称前缀（用于过滤，如 "test_machine_"）
        sort_by: 排序字段（默认 "id"，支持 "machine_name"、"machine_ip" 等）
        sort_order: 排序方向（"asc" 升序，"desc" 降序）
    
    Returns:
        tuple: (机器概要信息列表, 总页数)
    """
    with session_scope(commit=False) as session:
        stmt = select(Machine)
        if machine_name_prefix:
            stmt = stmt.where(Machine.machine_name.like(f"{machine_name_prefix}%"))

        if user_id and not _is_operator_user(user_id):
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
    
    # 4. 并发可达性检查（Phase A），然后逐条同步状态（Phase B）
    res = []

    # --- Phase A: 并发探活 ---
    use_parallel = getattr(AppConfig, "NODE_PARALLEL_ENABLED_MACHINES", True)
    _app = None
    _probe_results: dict[int, bool] = {}
    if machines:
        if use_parallel:
            # 缓存新鲜则零探测，否则并发探活
            _callables = [
                lambda mid=m.id, a=_app: (
                    _peek_machine_reachable(mid)
                    if _peek_machine_reachable(mid) is not None
                    else _node_probe_machine(mid)
                )
                for m in machines
            ]
            _raw = parallel_node_calls(_callables, timeout_per_call=3.0)
            for m, r in zip(machines, _raw):
                _probe_results[m.id] = r if isinstance(r, bool) else False
        else:
            for m in machines:
                cached = _peek_machine_reachable(m.id)
                _probe_results[m.id] = cached if cached is not None else _node_probe_machine(m.id)
    # 写透可达性缓存：容器 getter 的派生展示态读它
    for m in machines:
        _set_machine_reachable(m.id, bool(_probe_results.get(m.id, False)))

    # --- Phase B: 逐条同步（串行，避免 DB session 竞争） ---
    for machine in machines:
        online = _probe_results.get(machine.id, False)

        try:
            if online:
                try:
                    with session_scope() as session:
                        update_machine(machine.id, machine_status=MachineStatus.ONLINE, session=session)
                except Exception:
                    pass
            else:
                try:
                    with session_scope() as session:
                        update_machine(machine.id, machine_status=MachineStatus.OFFLINE, session=session)
                except Exception:
                    pass
        except Exception:
            pass
        with session_scope(commit=False) as session:
            latest = get_by_id(machine.id, session=session) or machine
        info = machine_bref_information(
            id=latest.id,
            machine_name=latest.machine_name,
            machine_ip=latest.machine_ip,
            machine_type=latest.machine_type.value,
            machine_status=_machine_status_value(latest),
            is_maintenance=bool(getattr(latest, "is_maintenance", False)),
            display_status=_display_machine_status(latest),
        )
        res.append(info)
    
    # 计算总页数（基于过滤后的数量）
    total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0
    
    return res, total_pages
#######################################
