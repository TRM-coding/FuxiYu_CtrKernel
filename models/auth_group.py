"""RBAC 权限组：预设组（user/operator/admin/teacher/student...），组内持有 auth_entity 集合。"""
from ..extensions import db


class AuthGroup(db.Model):
    __tablename__ = "auth_groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description = db.Column(db.String(500), nullable=True)
    # 组内权限点（group ─ auth_entity 多对多）
    entities = db.relationship(
        "AuthEntity",
        secondary="auth_group_entities",
        backref=db.backref("groups", lazy="dynamic"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuthGroup {self.name}>"


class AuthGroupEntity(db.Model):
    """auth_group ─ auth_entity 多对多关联表。"""

    __tablename__ = "auth_group_entities"

    group_id = db.Column(db.Integer, db.ForeignKey("auth_groups.id", ondelete="CASCADE"), primary_key=True)
    entity_id = db.Column(db.Integer, db.ForeignKey("auth_entities.id", ondelete="CASCADE"), primary_key=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuthGroupEntity group={self.group_id} entity={self.entity_id}>"
