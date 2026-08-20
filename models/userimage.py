"""RBAC 资源组 user-i：用户 ─ 镜像授权（镜像功能落地后启用）。

镜像表尚未创建，image_id 暂为裸列（无 FK）；镜像表落地时补外键。
"""
from ..extensions import db


class UserImage(db.Model):
    __tablename__ = "user_images"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # TODO: 镜像表落地后改为 db.ForeignKey("images.id", ondelete="CASCADE")
    image_id = db.Column(db.Integer, nullable=False, index=True)
    granted_at = db.Column(db.DateTime, default=db.func.now(), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "image_id", name="uq_user_images_user_image"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserImage user={self.user_id} image={self.image_id}>"
