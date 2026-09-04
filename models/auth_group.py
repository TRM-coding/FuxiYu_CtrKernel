"""RBAC 权限组（auth_group）与组-权限点绑定。

权限点枚举（auth_entity）已退役：AUTH_ENTITIES 常量是唯一权威，
组内直接持有权限点 code（auth_group_entities.entity_code），
不再缓存一份 DB 枚举表（避免代码/DB 两套分叉——2026-09 收敛）。
"""
from ..extensions import db


class AuthGroup(db.Model):
    __tablename__ = "auth_groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description = db.Column(db.String(500), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuthGroup {self.name}>"


class AuthGroupEntity(db.Model):
    """auth_group ─ 权限点 code 绑定（多对多，直接存 code 字符串）。"""

    __tablename__ = "auth_group_entities"

    group_id = db.Column(db.Integer, db.ForeignKey("auth_groups.id", ondelete="CASCADE"), primary_key=True)
    entity_code = db.Column(db.String(120), nullable=False, primary_key=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuthGroupEntity group={self.group_id} entity={self.entity_code}>"
