"""RBAC 方法级权限点（authEntity）：操作权限的原子单位。"""
from ..extensions import db


class AuthEntity(db.Model):
    __tablename__ = "auth_entities"

    id = db.Column(db.Integer, primary_key=True)
    # 权限点代码（如 "container:create" / "user:manage"），稳定标识，跨环境唯一
    code = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuthEntity {self.code}>"
