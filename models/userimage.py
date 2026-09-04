"""RBAC 资源组 user-i：用户 ─ 镜像授权。"""
from ..extensions import db


class UserImage(db.Model):
    __tablename__ = "user_images"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    image_id = db.Column(db.Integer, db.ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True)
    granted_at = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    image = db.relationship("Image", back_populates="user_image_links")

    __table_args__ = (
        db.UniqueConstraint("user_id", "image_id", name="uq_user_images_user_image"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserImage user={self.user_id} image={self.image_id}>"
