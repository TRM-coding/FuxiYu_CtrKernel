"""RBAC auth 域仓储。

repo 只接收显式 session，负责查询、写入和 flush；事务提交由 service/tasks
的 session_scope 决定。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuthEntity, AuthGroup, AuthGroupEntity, UserGroup
from ..models.userimage import UserImage


#####################
# 查询


def get_entity(code: str, *, session: Session) -> AuthEntity | None:
    return session.scalars(select(AuthEntity).where(AuthEntity.code == code)).first()


def get_group(name: str, *, session: Session) -> AuthGroup | None:
    return session.scalars(select(AuthGroup).where(AuthGroup.name == name)).first()


def group_has_entity(group_id: int, entity_code: str, *, session: Session) -> bool:
    stmt = (
        select(AuthGroupEntity.group_id)
        .join(AuthEntity, AuthGroupEntity.entity_id == AuthEntity.id)
        .where(
            AuthGroupEntity.group_id == group_id,
            AuthEntity.code == entity_code,
        )
    )
    return session.scalars(stmt).first() is not None


def user_has_entity(user_id: int, entity_code: str, *, session: Session) -> bool:
    """用户显式组是否包含指定权限点。"""

    stmt = (
        select(AuthGroupEntity.group_id)
        .join(AuthGroup, AuthGroupEntity.group_id == AuthGroup.id)
        .join(UserGroup, UserGroup.group_id == AuthGroup.id)
        .join(AuthEntity, AuthGroupEntity.entity_id == AuthEntity.id)
        .where(
            UserGroup.user_id == user_id,
            AuthEntity.code == entity_code,
        )
    )
    return session.scalars(stmt).first() is not None


def user_has_any_group(user_id: int, *, session: Session) -> bool:
    stmt = select(UserGroup.user_id).where(UserGroup.user_id == user_id)
    return session.scalars(stmt).first() is not None


def user_has_image(user_id: int, image_id: int, *, session: Session) -> bool:
    """user-i 资源授权（镜像表落地后启用）。"""

    stmt = select(UserImage.id).where(
        UserImage.user_id == user_id,
        UserImage.image_id == image_id,
    )
    return session.scalars(stmt).first() is not None


#####################
# seed 写入（幂等）


def ensure_entity(code: str, name: str, *, session: Session) -> AuthEntity:
    ent = get_entity(code, session=session)
    if ent is None:
        ent = AuthEntity(code=code, name=name)
        session.add(ent)
        session.flush()
    return ent


def ensure_group(name: str, description: str, *, session: Session) -> AuthGroup:
    group = get_group(name, session=session)
    if group is None:
        group = AuthGroup(name=name, description=description)
        session.add(group)
        session.flush()
    return group


def ensure_group_entity(group_id: int, entity_id: int, *, session: Session) -> None:
    stmt = select(AuthGroupEntity.group_id).where(
        AuthGroupEntity.group_id == group_id,
        AuthGroupEntity.entity_id == entity_id,
    )
    if session.scalars(stmt).first() is None:
        session.add(AuthGroupEntity(group_id=group_id, entity_id=entity_id))
        session.flush()


def ensure_user_group(user_id: int, group_id: int, *, session: Session) -> None:
    stmt = select(UserGroup.user_id).where(
        UserGroup.user_id == user_id,
        UserGroup.group_id == group_id,
    )
    if session.scalars(stmt).first() is None:
        session.add(UserGroup(user_id=user_id, group_id=group_id))
        session.flush()
