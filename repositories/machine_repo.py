from ..extensions import db
from ..models.machine import Machine
from typing import Sequence
from ..models.machine import MachineTypes
from ..models.machine import MachineStatus
from ..models.containers import Container as model_Container

def get_by_id(machine_id:int):
    return Machine.query.get(machine_id)

def get_id_by_ip(machine_ip:str):
    machine = Machine.query.filter_by(machine_ip=machine_ip).first()
    return machine.id if machine else None

def get_machine_ip_by_id(machine_id:int)->str:
    machine = get_by_id(machine_id)
    if not machine:
        raise ValueError(f"Machine with ID {machine_id} not found.")
    return machine.machine_ip

def get_the_first_free_port(machine_id:int)->int:
    # 查询该机器上所有容器已使用的端口
    used_ports = set(
        port for (port,) in db.session.query(model_Container.port)
        .filter(model_Container.machine_id == machine_id, model_Container.port.isnot(None))
        .all()
    )
    
    # 定义端口范围 (1024-49151)
    PORT_START = 1024
    PORT_END = 49151
    
    # 查找第一个可用端口
    for port in range(PORT_START, PORT_END + 1):
        if port not in used_ports:
            return port
    
    # 如果所有端口都被占用，抛出异常
    raise RuntimeError(f"No free ports available on machine {machine_id}")

def get_by_name(machine_name:str):
    return Machine.query.filter_by(machine_name=machine_name).first()

def list_machines(limit: int = 50, offset: int = 0) -> Sequence[Machine]:
	return Machine.query.order_by(Machine.id).offset(offset).limit(limit).all()

def count_machines() -> int: # 增加的额外方法 只辅助用于计算总数
    """Return total number of machines in DB."""
    return Machine.query.count()

def create_machine(machinename:str,
                   machine_ip:str,
                   machine_type:MachineTypes,
                   machine_description:str,
                   cpu_core_number:int,
                   gpu_number:int,
                   gpu_type:str,
                   memory_size:int,
                   disk_size:int)->bool:
    machine=Machine(
         machine_name=machinename,
         machine_ip=machine_ip,
         machine_type=machine_type,
         machine_description=machine_description,
         cpu_core_number=cpu_core_number,
         gpu_number=gpu_number,
         gpu_type=gpu_type,
         memory_size_gb=memory_size,
         disk_size_gb=disk_size
    )
    db.session.add(machine)
    db.session.commit()
    return True

def delete_machine(machine_id:int)->bool:
    machine=get_by_id(machine_id)
    if not machine:
         return False
    db.session.delete(machine)
    db.session.commit()
    return True

def update_machine(machine_id: int, *, commit: bool = True, **fields) -> bool:
    """
    部分更新用户字段。
    使用示例:
        update_user(1, email="new@x.com", graduation_year=2026)
        update_user(1, username="alice2", commit=False)  # 由调用方稍后统一提交
    """
    machine = get_by_id(machine_id)
    if not machine:
        return None

    allowed = {"machine_name", "machine_ip", "machine_type", "machine_status", "cpu_core_number",
               "memory_size_gb", "gpu_number", "gpu_type", "disk_size_gb", "machine_description"}
    dirty = False
    for k, v in fields.items():
        if k not in allowed:
            continue  # 忽略非法字段（也可选择抛异常）
        if v is None:
            continue  # 这里选择忽略 None；若需要可允许置空再改逻辑
        current = getattr(machine, k, None)
        if current != v:
            setattr(machine, k, v)
            dirty = True

    if dirty:
       db.session.commit()
    return True