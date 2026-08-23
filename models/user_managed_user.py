"""用户管理关系（教师/助教 → 学生）。

user 资源授权的第二层：除「自己是 owner」外，管理者（teacher/assistant）
对目标学生有资源访问权。写入端（授权管理接口）待业务规则落地。
"""

from datetime import datetime

from ..extensions import db


class UserManagedUser(db.Model):
    __tablename__ = "user_managed_users"

    id = db.Column(db.Integer, primary_key=True)
    manager_user_id = db.Column(db.Integer, nullable=False)  # 管理者：教师/助教
    managed_user_id = db.Column(db.Integer, nullable=False)  # 被管理者：学生
    granted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("manager_user_id", "managed_user_id", name="uq_user_managed_pair"),
    )
