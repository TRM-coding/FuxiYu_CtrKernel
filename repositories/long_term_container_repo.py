from typing import Sequence

from ..extensions import db
from ..config import AppConfig
from ..constant import ROLE
from ..models.long_term_container import LongTermContainer
from ..models.usercontainer import UserContainer


def is_long_term(container_id: int) -> bool:
    return LongTermContainer.query.get(int(container_id)) is not None


def list_long_term_container_ids(container_ids: Sequence[int]) -> set[int]:
    ids = [int(cid) for cid in container_ids if cid is not None]
    if not ids:
        return set()
    rows = (
        db.session.query(LongTermContainer.container_id)
        .filter(LongTermContainer.container_id.in_(ids))
        .all()
    )
    return {int(row.container_id) for row in rows}


def count_by_user(user_id: int) -> int:
    return (
        db.session.query(LongTermContainer.container_id)
        .join(UserContainer, UserContainer.container_id == LongTermContainer.container_id)
        .filter(UserContainer.user_id == int(user_id))
        .filter(UserContainer.role == ROLE.ROOT.value)
        .distinct()
        .count()
    )


def add(container_id: int, created_by_user_id: int | None = None, commit: bool = True) -> bool:
    container_id = int(container_id)
    if is_long_term(container_id):
        return True
    row = LongTermContainer(
        container_id=container_id,
        created_by_user_id=int(created_by_user_id) if created_by_user_id is not None else None,
    )
    db.session.add(row)
    if commit:
        db.session.commit()
    return True


def remove(container_id: int, commit: bool = True) -> bool:
    row = LongTermContainer.query.get(int(container_id))
    if not row:
        return True
    db.session.delete(row)
    if commit:
        db.session.commit()
    return True


def _get_long_term_container_limit() -> int:
    try:
        return max(0, int(getattr(AppConfig, "LONG_TERM_CONTAINER_LIMIT", 1) or 1))
    except Exception:
        return 1

def get_long_term_container_remaining(user_id: int) -> int:
    limit = _get_long_term_container_limit()
    used = count_by_user(user_id)
    return max(0, limit - used)
