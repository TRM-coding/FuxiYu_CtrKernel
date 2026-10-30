"""RBAC 用户 ─ 权限组多对多。"""
from ..extensions import db


class UserGroup(db.Model):
    __tablename__ = "user_groups"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("auth_groups.id", ondelete="CASCADE"), primary_key=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserGroup user={self.user_id} group={self.group_id}>"
