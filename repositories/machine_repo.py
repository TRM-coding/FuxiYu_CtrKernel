from ..extensions import db
from ..models.machine import Machine
from typing import Sequence
from ..models.machine import MachineTypes
from ..models.machine import MachineStatus

def get_by_id(machine_id:int):
    return Machine.query.get(machine_id)

def get_by_name(machine_name:str):
    return Machine.query.filter_by(machine_name==machine_name).first()

def list_machines(limit: int = 50, offset: int = 0) -> Sequence[Machine]:
	return Machine.query.order_by(Machine.id).offset(offset).limit(limit).all()

def create_machine(machinename:str,machineip:str,machine_type:MachineTypes)->Machine:
    machine=Machine(
         machinename=machinename,
         machineip=machineip,
         machine_type=machine_type,
    )
    db.session.add(machine)
    db.session.commit()
    return machine

def delete_machine(machine_id:int)->bool:
    machine=get_by_id(machine_id)
    if not machine:
         return False
    db.session.delete(machine)
    db.session.commit()

def update_machine(machine_id: int, *, commit: bool = True, **fields) -> Machine | None:
    """
    部分更新用户字段。
    使用示例:
        update_user(1, email="new@x.com", graduation_year=2026)
        update_user(1, username="alice2", commit=False)  # 由调用方稍后统一提交
    """
    machine = get_by_id(machine_id)
    if not machine:
        return None

    allowed = {"machine_name", "machine_ip", "machine_type", "machine_status"}
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
    return machine