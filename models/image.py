from datetime import datetime

from ..constant import ImageStatus
from ..extensions import db


class Image(db.Model):
    """镜像模板主表。

    镜像在 Ctrl 侧保存用户可维护的环境模板内容；最终 Dockerfile 由构建器
    在临时目录中生成，不回写 DB。
    """

    __tablename__ = "images"

    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description: str | None = db.Column(db.String(500), nullable=True)
    base_image: str = db.Column(db.String(255), nullable=False)
    dockerfile_body: str = db.Column(db.Text, nullable=False, default="")
    pre_build: str | None = db.Column(db.Text, nullable=True)
    status: ImageStatus = db.Column(
        db.Enum(ImageStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=ImageStatus.DRAFT,
    )
    created_by_user_id: int | None = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: datetime = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    updated_at: datetime = db.Column(
        db.DateTime,
        default=db.func.now(),
        onupdate=db.func.now(),
        nullable=False,
    )

    user_image_links = db.relationship(
        "UserImage",
        back_populates="image",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Image {self.name}>"
