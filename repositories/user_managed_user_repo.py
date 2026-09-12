"""用户管理关系仓储（教师/助教 → 学生）。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.user_managed_user import UserManagedUser


def is_managed(*, manager_user_id: int, managed_user_id: int, session: Session) -> bool:
    """管理者是否被授权管理目标用户。"""
    stmt = select(UserManagedUser.id).where(
        UserManagedUser.manager_user_id == int(manager_user_id),
        UserManagedUser.managed_user_id == int(managed_user_id),
    )
    return session.scalars(stmt).first() is not None


def list_managed_ids(*, manager_user_id: int, session: Session) -> set[int]:
    """管理者被授权管理的全部用户 id 集合。"""
    stmt = select(UserManagedUser.managed_user_id).where(
        UserManagedUser.manager_user_id == int(manager_user_id),
    )
    return set(session.scalars(stmt).all())
