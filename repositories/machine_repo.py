"""机器仓储。

repo 只接收显式 session，负责查询/写入/flush；事务提交由 service/tasks 的
session_scope 统一决定。
"""
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.containers import Container as model_Container
from ..models.machine import Machine, MachineStatus, MachineTypes


def get_by_id(machine_id: int, *, session: Session) -> Machine | None:
    return session.get(Machine, int(machine_id))


def get_id_by_ip(machine_ip: str, *, session: Session) -> int | None:
    machine = session.scalars(select(Machine).where(Machine.machine_ip == machine_ip)).first()
    return machine.id if machine else None


def get_by_uid(uid: str, *, session: Session) -> Machine | None:
    """按 Ctrl 颁发的 UID 查询机器，供 WSS 身份归位使用。"""
    return session.scalars(select(Machine).where(Machine.node_uid == uid)).first()


def get_machine_ip_by_id(machine_id: int, *, session: Session) -> str:
    machine = get_by_id(machine_id, session=session)
    if not machine:
        raise ValueError(f"Machine with ID {machine_id} not found.")
    return machine.machine_ip


def get_the_first_free_port(machine_id: int, *, session: Session) -> int:
    used_ports = set(
        session.scalars(
            select(model_Container.port).where(
                model_Container.machine_id == machine_id,
                model_Container.port.isnot(None),
            )
        ).all()
    )
    for port in range(1024, 49152):
        if port not in used_ports:
            return port
    raise RuntimeError(f"No free ports available on machine {machine_id}")


def get_by_name(machine_name: str, *, session: Session) -> Machine | None:
    return session.scalars(select(Machine).where(Machine.machine_name == machine_name)).first()


def list_machines(limit: int = 50, offset: int = 0, *, session: Session) -> Sequence[Machine]:
    stmt = select(Machine).order_by(Machine.id).offset(offset).limit(limit)
    return list(session.scalars(stmt).all())


def list_machines_by_status(status: MachineStatus, *, session: Session) -> Sequence[Machine]:
    """按真实连接状态列出机器（Ctrl 启动探活用；数据通路对账契约 C3）。"""
    stmt = select(Machine).where(Machine.machine_status == status).order_by(Machine.id)
    return list(session.scalars(stmt).all())


def count_machines(*, session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(Machine)) or 0)


def create_machine(
    *,
    machinename: str,
    machine_ip: str,
    machine_type: MachineTypes,
    machine_description: str,
    cpu_core_number: int,
    gpu_number: int,
    gpu_type: str,
    memory_size: int,
    max_shared_gb: int,
    disk_size: int,
    max_cpu_core_number: int,
    max_gpu_number: int,
    max_memory_gb: int,
    max_disk_size_gb: int | None = None,
    session: Session,
) -> Machine:
    machine = Machine(
        machine_name=machinename,
        machine_ip=machine_ip,
        machine_type=machine_type,
        machine_description=machine_description,
        cpu_core_number=cpu_core_number,
        gpu_number=gpu_number,
        gpu_type=gpu_type,
        memory_size_gb=memory_size,
        max_shared_gb=max_shared_gb,
        max_cpu_core_number=max_cpu_core_number,
        max_gpu_number=max_gpu_number,
        max_memory_gb=max_memory_gb,
        max_disk_size_gb=max_disk_size_gb,
        disk_size_gb=disk_size,
    )
    session.add(machine)
    session.flush()
    return machine


def delete_machine(machine_id: int, *, session: Session) -> bool:
    machine = get_by_id(machine_id, session=session)
    if not machine:
        return False
    session.delete(machine)
    session.flush()
    return True


def update_machine(machine_id: int, *, session: Session, **fields) -> bool:
    machine = get_by_id(machine_id, session=session)
    if not machine:
        return False

    allowed = {
        "machine_name",
        "machine_ip",
        "machine_type",
        "machine_status",
        "is_maintenance",
        "collect_error_at",
        "cpu_core_number",
        "memory_size_gb",
        "gpu_number",
        "gpu_type",
        "gpu_list",
        "gpu_allow_list",
        "disk_size_gb",
        "machine_description",
        "shared_size_gb",
        "max_shared_gb",
        "max_memory_gb",
        "max_gpu_number",
        "max_cpu_core_number",
        "max_disk_size_gb",
        "node_uid",
        "node_cert_fingerprint",
        "cert_pinned_at",
    }
    dirty = False
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if getattr(machine, key, None) != value:
            setattr(machine, key, value)
            dirty = True

    if dirty:
        session.flush()
    return True


def set_maintenance(machine_id: int, enabled: bool, *, session: Session) -> bool:
    """设置机器维护开关，不写入 machine_status。"""
    machine = get_by_id(machine_id, session=session)
    if not machine:
        return False
    if bool(getattr(machine, "is_maintenance", False)) != bool(enabled):
        machine.is_maintenance = bool(enabled)
        session.flush()
    return True


def get_max_cpu_core_number(machine_id: int, *, session: Session) -> int:
    value = session.scalar(select(Machine.max_cpu_core_number).where(Machine.id == machine_id))
    return int(value) if value is not None else 0


def get_max_gpu_number(machine_id: int, *, session: Session) -> int:
    value = session.scalar(select(Machine.max_gpu_number).where(Machine.id == machine_id))
    return int(value) if value is not None else 0


def get_max_memory_gb(machine_id: int, *, session: Session) -> int:
    value = session.scalar(select(Machine.max_memory_gb).where(Machine.id == machine_id))
    return int(value) if value is not None else 0


def get_max_shared_gb(machine_id: int, *, session: Session) -> int:
    value = session.scalar(select(Machine.max_shared_gb).where(Machine.id == machine_id))
    return int(value) if value is not None else 0
