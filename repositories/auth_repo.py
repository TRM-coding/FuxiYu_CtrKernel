"""RBAC auth 域仓储。

权限点枚举不落库（auth_entities 表已退役，2026-09 收敛）：AUTH_ENTITIES 常量是
唯一权威，组-权限绑定直接存 code 字符串（auth_group_entities.entity_code），
不存在代码/DB 两套分叉。

repo 只接收显式 session，负责查询、写入和 flush；事务提交由 service/tasks
的 session_scope 决定。
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import AuthGroup, AuthGroupEntity, UserGroup
from ..models.userimage import UserImage


#####################
# 查询


def get_group(name: str, *, session: Session) -> AuthGroup | None:
    return session.scalars(select(AuthGroup).where(AuthGroup.name == name)).first()


def get_group_by_id(group_id: int, *, session: Session) -> AuthGroup | None:
    return session.get(AuthGroup, group_id)


def list_groups(*, session: Session) -> list[AuthGroup]:
    return list(session.scalars(select(AuthGroup).order_by(AuthGroup.name)))


def list_group_entity_codes(*, session: Session) -> dict[int, set[str]]:
    result: dict[int, set[str]] = {}
    for group_id, code in session.execute(
        select(AuthGroupEntity.group_id, AuthGroupEntity.entity_code)
    ).all():
        result.setdefault(group_id, set()).add(code)
    return result


def group_has_entity(group_id: int, entity_code: str, *, session: Session) -> bool:
    stmt = select(AuthGroupEntity.group_id).where(
        AuthGroupEntity.group_id == group_id,
        AuthGroupEntity.entity_code == entity_code,
    )
    return session.scalars(stmt).first() is not None


def user_has_entity(user_id: int, entity_code: str, *, session: Session) -> bool:
    """用户显式组是否包含指定权限点。"""

    stmt = (
        select(AuthGroupEntity.group_id)
        .join(AuthGroup, AuthGroupEntity.group_id == AuthGroup.id)
        .join(UserGroup, UserGroup.group_id == AuthGroup.id)
        .where(
            UserGroup.user_id == user_id,
            AuthGroupEntity.entity_code == entity_code,
        )
    )
    return session.scalars(stmt).first() is not None


def user_has_any_group(user_id: int, *, session: Session) -> bool:
    stmt = select(UserGroup.user_id).where(UserGroup.user_id == user_id)
    return session.scalars(stmt).first() is not None


def user_in_group(user_id: int, group_name: str, *, session: Session) -> bool:
    stmt = (
        select(UserGroup.user_id)
        .join(AuthGroup, UserGroup.group_id == AuthGroup.id)
        .where(
            UserGroup.user_id == user_id,
            AuthGroup.name == group_name,
        )
    )
    return session.scalars(stmt).first() is not None


#####################
# user-i 资源授权（镜像表落地后启用）


def user_has_image(user_id: int, image_id: int, *, session: Session) -> bool:
    stmt = select(UserImage.id).where(
        UserImage.user_id == user_id,
        UserImage.image_id == image_id,
    )
    return session.scalars(stmt).first() is not None


#####################
# seed 写入（幂等）


def ensure_group(name: str, description: str, *, session: Session) -> AuthGroup:
    group = get_group(name, session=session)
    if group is None:
        group = AuthGroup(name=name, description=description)
        session.add(group)
        session.flush()
    return group


def create_group(name: str, description: str, *, session: Session) -> AuthGroup:
    group = AuthGroup(name=name, description=description)
    session.add(group)
    session.flush()
    return group


def ensure_group_entity(group_id: int, entity_code: str, *, session: Session) -> None:
    stmt = select(AuthGroupEntity.group_id).where(
        AuthGroupEntity.group_id == group_id,
        AuthGroupEntity.entity_code == entity_code,
    )
    if session.scalars(stmt).first() is None:
        session.add(AuthGroupEntity(group_id=group_id, entity_code=entity_code))
        session.flush()


def ensure_user_group(user_id: int, group_id: int, *, session: Session) -> None:
    stmt = select(UserGroup.user_id).where(
        UserGroup.user_id == user_id,
        UserGroup.group_id == group_id,
    )
    if session.scalars(stmt).first() is None:
        session.add(UserGroup(user_id=user_id, group_id=group_id))
        session.flush()


def list_user_group_ids(user_id: int, *, session: Session) -> list[int]:
    return list(session.scalars(
        select(UserGroup.group_id).where(UserGroup.user_id == user_id).order_by(UserGroup.group_id)
    ))


def replace_user_groups(user_id: int, group_ids: list[int], *, session: Session) -> None:
    """整组替换用户的权限组绑定（set 语义；组 id 合法性由 service 校验）。"""
    session.execute(delete(UserGroup).where(UserGroup.user_id == user_id))
    for gid in sorted({int(g) for g in group_ids}):
        session.add(UserGroup(user_id=user_id, group_id=gid))
    session.flush()


def replace_group_entities(group_id: int, entity_codes: set[str], *, session: Session) -> None:
    session.execute(delete(AuthGroupEntity).where(AuthGroupEntity.group_id == group_id))
    for code in sorted(entity_codes):
        session.add(AuthGroupEntity(group_id=group_id, entity_code=code))
    session.flush()


def prune_group_entity_codes(valid_codes: set[str], *, session: Session) -> list[str]:
    """清退绑定表中已不在常量集合内的残留 code（seed 收敛时调用）。"""
    stale = sorted({
        code for code in session.scalars(select(AuthGroupEntity.entity_code).distinct())
        if code not in valid_codes
    })
    if stale:
        session.execute(delete(AuthGroupEntity).where(AuthGroupEntity.entity_code.not_in(valid_codes)))
        session.flush()
    return stale
