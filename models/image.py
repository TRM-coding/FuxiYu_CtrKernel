from datetime import datetime

from ..constant import ImageStatus
from ..extensions import db


class Image(db.Model):
    """镜像模板主表。

    镜像在 Ctrl 侧是 Dockerfile 管理对象；内容直接存 DB Text（与元数据同事务，
    无文件系统悬挂态）；Node 构建时由 Ctrl 下发内容或落临时文件。
    """

    __tablename__ = "images"

    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description: str | None = db.Column(db.String(500), nullable=True)
    dockerfile: str = db.Column(db.Text, nullable=False)
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
