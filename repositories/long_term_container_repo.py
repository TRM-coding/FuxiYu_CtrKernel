"""长期容器仓储。"""

from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..constant import ROLE
from ..models.long_term_container import LongTermContainer
from ..models.usercontainer import UserContainer


def is_long_term(container_id: int, *, session: Session) -> bool:
    return session.get(LongTermContainer, int(container_id)) is not None


def list_long_term_container_ids(container_ids: Sequence[int], *, session: Session) -> set[int]:
    ids = [int(cid) for cid in container_ids if cid is not None]
    if not ids:
        return set()
    rows = session.scalars(
        select(LongTermContainer.container_id).where(LongTermContainer.container_id.in_(ids))
    ).all()
    return {int(container_id) for container_id in rows}


def count_by_user(user_id: int, *, session: Session) -> int:
    stmt = (
        select(func.count(func.distinct(LongTermContainer.container_id)))
        .join(UserContainer, UserContainer.container_id == LongTermContainer.container_id)
        .where(
            UserContainer.user_id == int(user_id),
            UserContainer.role == ROLE.ROOT.value,
        )
    )
    return int(session.scalar(stmt) or 0)


def add(container_id: int, created_by_user_id: int | None = None, *, session: Session) -> bool:
    container_id = int(container_id)
    if is_long_term(container_id, session=session):
        return True
    row = LongTermContainer(
        container_id=container_id,
        created_by_user_id=int(created_by_user_id) if created_by_user_id is not None else None,
    )
    session.add(row)
    session.flush()
    return True


def remove(container_id: int, *, session: Session) -> bool:
    row = session.get(LongTermContainer, int(container_id))
    if not row:
        return True
    session.delete(row)
    session.flush()
    return True


def get_long_term_container_limit() -> int:
    from ..services import settings_tasks

    try:
        return max(0, int(settings_tasks.get_long_term_container_limit() or 1))
    except Exception:
        return 1


def get_long_term_container_remaining(user_id: int, *, session: Session) -> int:
    limit = get_long_term_container_limit()
    used = count_by_user(user_id, session=session)
    return max(0, limit - used)
