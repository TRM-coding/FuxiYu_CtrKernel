from ..repositories.machine_repo import *
from pydantic import BaseModel
from typing import Optional
from ..utils.heartbeat import send, start_machine_maintenance_transition_heartbeat
from ..repositories.containers_repo import update_container, list_containers as repo_list_containers
from ..repositories import machine_permission_repo, user_repo
from ..constant import ContainerStatus, MachineStatus
#######################################
#API Definition
class machine_bref_information(BaseModel):
    id: int  #没想到更好的解决办法。主要作为各种操作的映射。
    machine_name:str
    machine_ip:str
    machine_type:str
    machine_status:str

class machine_detail_information(BaseModel):
    machine_name:str
    machine_ip:str
    machine_type:str
    machine_status:str
    cpu_core_number:int
    gpu_number:int
    gpu_type: Optional[str] # 部分sql数据会出现此字段是NULL的情况，因此暂时用这个方法解决
    memory_size_gb:int
    max_swap_gb:int
    max_cpu_core_number:int
    max_gpu_number:int
    max_memory_gb:int
    disk_size_gb:int
    machine_description:str
    containers:list[int] #容器id
#######################################

#######################################
# 机器权限管理

def Add_machine_permission(machine_id: int, user_id: int) -> bool:
    machine = get_by_id(machine_id)
    if not machine:
        raise ValueError(machine_not_found)
    user = user_repo.get_by_id(user_id)
    if not user:
        raise ValueError(user_not_found)
    machine_permission_repo.add_permission(machine_id, user_id)
    return True


def Remove_machine_permission(machine_id: int, user_id: int) -> bool:
    return machine_permission_repo.remove_permission(machine_id, user_id)


def List_machine_permissions(machine_id: int) -> list[int]:
    return machine_permission_repo.list_user_ids_by_machine(machine_id)


#######################################
# 辅助方法

def _is_operator_user(user_id: int) -> bool:
    try:
        u = user_repo.get_by_id(user_id)
        perm = getattr(u, permission, None) if u else None
        return bool(perm and getattr(perm, value, str(perm)).lower() == operator)
    except Exception:
        return False

def is_machine_online_remote(machine_id: int, timeout: float = 2.0) -> bool:
    """
    Perform a single, lightweight communication check to the Node's `/machine_status` endpoint.
    Returns True if Node responds with success==1 and machine_status == 'online'.
    This function does NOT update DB state or perform additional logic; callers should handle
    persistence or other decisions.
    """
    try:
        m = get_by_id(machine_id)
    except Exception:
        m = None
    if not m:
        return False
    machine_ip = getattr(m, 'machine_ip', None)
    if not machine_ip:
        return False

    j = send(machine_ip, "/machine_status", {"config": {}}, timeout=timeout)
    if isinstance(j, dict) and j.get('success') in (1, True):
        ms = (j.get('machine_status') or '').lower()
        return ms == 'online'
    return False

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
                   max_swap_size:int,
                   disk_size:int,
                   max_memory_gb:int,
                   max_gpu_number:int,
                   max_cpu_core_number:int)->bool:
    # 防御性检查：限制字段长度，防止过长输入导致数据库异常
    if machine_name and len(machine_name) > 115:
        raise ValueError(f"machine_name too long (max 115): length={len(machine_name)}")
    if gpu_type and len(str(gpu_type)) > 115:
        raise ValueError(f"gpu_type too long (max 115): length={len(str(gpu_type))}")
    if machine_type and len(str(machine_type)) > 255:
        raise ValueError(f"machine_type too long (max 255): length={len(str(machine_type))}")

    # max_swap_size defensive check: must be non-negative integer and <= 8 (GB)
    if max_swap_size is not None:
        try:
            ss = int(max_swap_size)
        except Exception:
            e = ValueError(f"max_swap_size must be an integer: {max_swap_size}")
            setattr(e, 'error_reason', 'create_failed')
            raise e
        if ss < 0 or ss > 8:
            e = ValueError(f"swap_size out of range (0-8 GB): {ss}")
            setattr(e, 'error_reason', 'create_failed')
            raise e

    create_machine(
         machinename=machine_name,
         machine_ip=machine_ip,
         machine_type=machine_type,
         machine_description=machine_description,
         cpu_core_number=cpu_core_number,
         gpu_number=gpu_number,
         gpu_type=gpu_type,
         memory_size=memory_size,
         max_swap_size=max_swap_size,
         disk_size=disk_size,
         max_memory_gb=max_memory_gb,
         max_gpu_number=max_gpu_number,
         max_cpu_core_number=max_cpu_core_number
    )
    return True

#######################################


#######################################
# 删除集群中的一个（一组）机器
def Remove_machine(machine_id:list[int])->bool:
    for id in machine_id:
        delete_machine(id)
    return True
#######################################


#######################################
# 更新机器的信息
def Update_machine(machine_id: int, **fields) -> bool:
    machine = get_by_id(machine_id)
    if not machine:
        return False

    # validate swap_size when provided: must be integer and <= 8 GB
    if 'swap_size' in fields:
        ss_val = fields.get('swap_size')
        try:
            ss = int(ss_val) if ss_val is not None else None
        except Exception:
            e = ValueError(f"swap_size must be an integer: {ss_val}")
            setattr(e, 'error_reason', 'update_failed')
            raise e
        if ss is not None and (ss < 0 or ss > 8):
            e = ValueError(f"swap_size out of range (0-8 GB): {ss}")
            setattr(e, 'error_reason', 'update_failed')
            raise e

    requested_status = fields.get('machine_status', None)
    current_status = machine.machine_status.value if hasattr(machine.machine_status, 'value') else str(machine.machine_status)

    # ONLINE -> MAINTENANCE: Ctrl异步处理，保持当前状态并启动过渡心跳；
    # 其他状态变更则直接更新
    if str(current_status).lower() == MachineStatus.ONLINE.value and str(requested_status).lower() == MachineStatus.MAINTENANCE.value:
        passthrough_fields = dict(fields)
        passthrough_fields.pop('machine_status', None)
        if passthrough_fields:
            update_machine(machine_id, **passthrough_fields)
        start_machine_maintenance_transition_heartbeat(machine_id)
        return True

    update_machine(machine_id, **fields)
    return True    
#######################################


#######################################
# 根据机器ID获取机器的详细信息
def Get_detail_information(machine_id:int)->machine_detail_information|None:
    machine=get_by_id(machine_id)
    if not machine:
        return None

    return machine_detail_information(
        machine_name=machine.machine_name,
        machine_ip=machine.machine_ip,
        machine_type=machine.machine_type.value,
        machine_status=machine.machine_status.value,
        cpu_core_number=machine.cpu_core_number,
        gpu_number=machine.gpu_number,
        gpu_type=machine.gpu_type,
        memory_size_gb=machine.memory_size_gb,
        max_swap_gb=machine.max_swap_gb,
        max_cpu_core_number=machine.max_cpu_core_number,
        max_gpu_number=machine.max_gpu_number,
        max_memory_gb=machine.max_memory_gb,
        disk_size_gb=machine.disk_size_gb,
        machine_description=machine.machine_description,
        containers=[container.id for container in machine.containers]
    )
#######################################

#######################################
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
    # 1. 构建查询条件
    query_filters = {}
    if machine_name_prefix:
        # 按名称前缀过滤（关键：解决测试数据和原有数据混合的问题）
        machines_query = Machine.query.filter(Machine.machine_name.like(f"{machine_name_prefix}%"))
    else:
        machines_query = Machine.query
    
    # 2. 设置排序规则（关键：确保分页结果可预测）
    if sort_by == "id":
        if sort_order == "asc":
            machines_query = machines_query.order_by(Machine.id.asc())
        else:
            machines_query = machines_query.order_by(Machine.id.desc())
    elif sort_by == "machine_name":
        if sort_order == "asc":
            machines_query = machines_query.order_by(Machine.machine_name.asc())
        else:
            machines_query = machines_query.order_by(Machine.machine_name.desc())
    elif sort_by == "machine_ip":
        if sort_order == "asc":
            machines_query = machines_query.order_by(Machine.machine_ip.asc())
        else:
            machines_query = machines_query.order_by(Machine.machine_ip.desc())
    
        # 3. 权限过滤：普通用户仅能看到被授权机器
    if user_id and not _is_operator_user(user_id):
        allowed = set(machine_permission_repo.list_machine_ids_by_user(user_id))
        machines_query = machines_query.filter(Machine.id.in_(allowed)) if allowed else machines_query.filter(False)

    # 3. 执行分页查询
    # 先计算符合过滤条件的总数量（而非全量机器）
    total_count = machines_query.count()
    # 分页查询（offset从0开始）
    machines = machines_query.limit(page_size).offset(page_number * page_size).all()
    
    # 4. 组装返回结果
    res = []
    for machine in machines:
        # 最朴素的节点可达性检查：单次请求 /machine_status
        try:
            try:
                online = is_machine_online_remote(machine.id, timeout=2.0)
            except Exception:
                online = False

            try:
                current_status_val = machine.machine_status.value.lower() if hasattr(machine.machine_status, 'value') else str(machine.machine_status).lower()
            except Exception:
                current_status_val = str(getattr(machine, 'machine_status', '')).lower()

            def _mark_containers_offline(mach):
                try:
                    containers_on_machine = getattr(mach, 'containers', None) or repo_list_containers(limit=100, offset=0, machine_id=mach.id)
                    for c in containers_on_machine:
                        cid = getattr(c, 'id', None) or (c.get('container_id') if isinstance(c, dict) else None)
                        if cid:
                            try:
                                update_container(cid, container_status=ContainerStatus.OFFLINE)
                            except Exception:
                                pass
                except Exception:
                    pass

            if current_status_val == 'maintenance':
                if online:
                    try:
                        update_machine(machine.id, machine_status=MachineStatus.MAINTENANCE)
                    except Exception:
                        pass
                else:
                    try:
                        update_machine(machine.id, machine_status=MachineStatus.OFFLINE)
                    except Exception:
                        pass
                    _mark_containers_offline(machine)
            else:
                if online:
                    try:
                        update_machine(machine.id, machine_status=MachineStatus.ONLINE)
                    except Exception:
                        pass
                else:
                    try:
                        update_machine(machine.id, machine_status=MachineStatus.OFFLINE)
                    except Exception:
                        pass
                    _mark_containers_offline(machine)
        except Exception:
            # ignore and continue
            pass
        latest = get_by_id(machine.id) or machine
        info = machine_bref_information(
            id=latest.id,
            machine_name=latest.machine_name,
            machine_ip=latest.machine_ip,
            machine_type=latest.machine_type.value,
            machine_status=latest.machine_status.value
        )
        res.append(info)
    
    # 计算总页数（基于过滤后的数量）
    total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0
    
    return res, total_pages
#######################################

