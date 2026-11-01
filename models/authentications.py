from datetime import datetime
from ..extensions import db


class Authentication(db.Model):
    """登录态 Token。

    只通过 `user_id` 关联 users，**不关联任何容器**：容器协作关系在 user_container，
    机器授权在 machine_permissions。因此删除用户时由用户删除事务显式清掉这些行
    （见 services/user_tasks.Delete_user 与 authentications_repo.delete_tokens_by_user_id），
    不涉及容器归属判定，也不应被当成「容器阻止删除」。
    """

    __tablename__ = "authentications"
    
    token = db.Column(db.String(255), primary_key=True, unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    
    def __repr__(self) -> str:
        return f"<Authentication token={self.token[:8]}...>"
