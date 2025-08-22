"""User-Container 关联仓储
封装用户与容器之间的多对多显式操作，便于未来扩展（如角色/授权时间）。
"""
from typing import Sequence
from sqlalchemy import tuple_
from ..extensions import db
from ..models.user import User, user_containers
from ..models.containers import Container


def add_binding(user_id: int, container_id: int, commit: bool = True) -> bool:
    if not User.query.get(user_id) or not Container.query.get(container_id):
        return False
    # 直接插入关联表（避免加载 relationship 造成额外查询）
    exists = db.session.execute(
        db.select(user_containers.c.user_id).where(
            user_containers.c.user_id == user_id,
            user_containers.c.container_id == container_id,
        )
    ).first()
    if exists:
        return True
    db.session.execute(
        user_containers.insert().values(user_id=user_id, container_id=container_id)
    )
    if commit:
        db.session.commit()
    return True


def remove_binding(user_id: int, container_id: int, commit: bool = True) -> bool:
    result = db.session.execute(
        user_containers.delete().where(
            user_containers.c.user_id == user_id,
            user_containers.c.container_id == container_id,
        )
    )
    if commit:
        db.session.commit()
    return result.rowcount > 0


def list_containers_by_user(user_id: int) -> Sequence[Container]:
    return (
        db.session.query(Container)
        .join(user_containers, Container.id == user_containers.c.container_id)
        .filter(user_containers.c.user_id == user_id)
        .order_by(Container.id)
        .all()
    )


def list_users_by_container(container_id: int) -> Sequence[User]:
    return (
        db.session.query(User)
        .join(user_containers, User.id == user_containers.c.user_id)
        .filter(user_containers.c.container_id == container_id)
        .order_by(User.id)
        .all()
    )


