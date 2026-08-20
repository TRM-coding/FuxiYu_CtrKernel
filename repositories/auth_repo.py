"""RBAC auth 域仓储：auth_entity / auth_group / auth_group_entity / user_group 的读写。

seed 与权限查询的 db 访问收敛于此（rbac_service 不再直接触碰 db.session）。
"""
from ..extensions import db
from ..models import AuthEntity, AuthGroup, AuthGroupEntity, UserGroup


#####################
# 查询

def get_entity(code: str) -> AuthEntity | None:
    return AuthEntity.query.filter_by(code=code).first()


def get_group(name: str) -> AuthGroup | None:
    return AuthGroup.query.filter_by(name=name).first()


def group_has_entity(group_id: int, entity_code: str) -> bool:
    return db.session.query(AuthGroupEntity.group_id).join(
        AuthEntity, AuthGroupEntity.entity_id == AuthEntity.id
    ).filter(
        AuthGroupEntity.group_id == group_id,
        AuthEntity.code == entity_code,
    ).first() is not None


def user_has_entity(user_id: int, entity_code: str) -> bool:
    """用户显式组是否包含指定权限点。"""
    return db.session.query(AuthGroupEntity.group_id).join(
        AuthGroup, AuthGroupEntity.group_id == AuthGroup.id
    ).join(
        UserGroup, UserGroup.group_id == AuthGroup.id
    ).join(
        AuthEntity, AuthGroupEntity.entity_id == AuthEntity.id
    ).filter(
        UserGroup.user_id == user_id,
        AuthEntity.code == entity_code,
    ).first() is not None


def user_has_any_group(user_id: int) -> bool:
    return db.session.query(UserGroup.user_id).filter_by(user_id=user_id).first() is not None


def user_has_image(user_id: int, image_id: int) -> bool:
    """user-i 资源授权（镜像表落地后启用）。"""
    from ..models.userimage import UserImage
    return UserImage.query.filter_by(user_id=user_id, image_id=image_id).first() is not None


#####################
# seed 写入（幂等）

def ensure_entity(code: str, name: str) -> AuthEntity:
    ent = get_entity(code)
    if ent is None:
        ent = AuthEntity(code=code, name=name)
        db.session.add(ent)
        db.session.flush()
    return ent


def ensure_group(name: str, description: str) -> AuthGroup:
    g = get_group(name)
    if g is None:
        g = AuthGroup(name=name, description=description)
        db.session.add(g)
        db.session.flush()
    return g


def ensure_group_entity(group_id: int, entity_id: int) -> None:
    if db.session.query(AuthGroupEntity.group_id).filter_by(
            group_id=group_id, entity_id=entity_id).first() is None:
        db.session.add(AuthGroupEntity(group_id=group_id, entity_id=entity_id))


def ensure_user_group(user_id: int, group_id: int) -> None:
    if db.session.query(UserGroup.user_id).filter_by(
            user_id=user_id, group_id=group_id).first() is None:
        db.session.add(UserGroup(user_id=user_id, group_id=group_id))


def apply_seed_changes() -> None:
    """提交 RBAC seed 结果。

    仅供 rbac_service.seed_rbac_defaults 使用，避免向 service 暴露通用 commit。
    """
    db.session.commit()
