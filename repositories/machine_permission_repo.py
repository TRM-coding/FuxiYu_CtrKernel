"""机器权限仓储。"""
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.machine_permission import MachinePermission
from ..models.user import User


def add_permission(machine_id: int, user_id: int, *, session: Session) -> MachinePermission:
    stmt = select(MachinePermission).where(
        MachinePermission.machine_id == machine_id,
        MachinePermission.user_id == user_id,
    )
    record = session.scalars(stmt).first()
    if record:
        return record
    record = MachinePermission(machine_id=machine_id, user_id=user_id)
    session.add(record)
    session.flush()
    return record


def remove_permission(machine_id: int, user_id: int, *, session: Session) -> bool:
    stmt = select(MachinePermission).where(
        MachinePermission.machine_id == machine_id,
        MachinePermission.user_id == user_id,
    )
    record = session.scalars(stmt).first()
    if not record:
        return False
    session.delete(record)
    session.flush()
    return True


def list_user_ids_by_machine(machine_id: int, *, session: Session) -> list[int]:
    rows = session.scalars(
        select(MachinePermission.user_id).where(MachinePermission.machine_id == machine_id)
    ).all()
    return [int(row) for row in rows]


def list_users_by_machine(machine_id: int, *, session: Session) -> Sequence[User]:
    stmt = (
        select(User)
        .join(MachinePermission, MachinePermission.user_id == User.id)
        .where(MachinePermission.machine_id == machine_id)
        .order_by(User.id.asc())
    )
    return list(session.scalars(stmt).all())


def list_machine_ids_by_user(user_id: int, *, session: Session) -> list[int]:
    rows = session.scalars(
        select(MachinePermission.machine_id).where(MachinePermission.user_id == user_id)
    ).all()
    return [int(row) for row in rows]
