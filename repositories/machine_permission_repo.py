from typing import Sequence
from ..extensions import db
from ..models.machine_permission import MachinePermission
from ..models.user import User


def add_permission(machine_id: int, user_id: int, *, commit: bool = True) -> MachinePermission:
    record = MachinePermission.query.filter_by(machine_id=machine_id, user_id=user_id).first()
    if record:
        return record
    record = MachinePermission(machine_id=machine_id, user_id=user_id)
    db.session.add(record)
    if commit:
        db.session.commit()
    return record


def remove_permission(machine_id: int, user_id: int, *, commit: bool = True) -> bool:
    record = MachinePermission.query.filter_by(machine_id=machine_id, user_id=user_id).first()
    if not record:
        return False
    db.session.delete(record)
    if commit:
        db.session.commit()
    return True


def list_user_ids_by_machine(machine_id: int) -> list[int]:
    rows = MachinePermission.query.filter_by(machine_id=machine_id).all()
    return [r.user_id for r in rows]


def list_users_by_machine(machine_id: int) -> Sequence[User]:
    return (
        User.query.join(MachinePermission, MachinePermission.user_id == User.id)
        .filter(MachinePermission.machine_id == machine_id)
        .order_by(User.id.asc())
        .all()
    )


def list_machine_ids_by_user(user_id: int) -> list[int]:
    rows = MachinePermission.query.filter_by(user_id=user_id).all()
    return [r.machine_id for r in rows]
