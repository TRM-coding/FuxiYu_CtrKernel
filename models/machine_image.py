from datetime import datetime

from ..extensions import db


class MachineImage(db.Model):
    """机器与镜像模板配对的已选构建版本；不代表宿主制品已建成。"""

    __tablename__ = "machine_image"

    id: int = db.Column(db.Integer, primary_key=True)
    machine_id: int = db.Column(
        db.Integer, db.ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_id: int = db.Column(
        db.Integer, db.ForeignKey("images.id"), nullable=False, index=True
    )
    image_tag: str = db.Column(db.String(200), nullable=False)
    created_at: datetime = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    # 配方指纹（2026-10 决策）：本次派发所依据的 Dockerfile 文本的 sha256。
    # 只用于判定"这一行缓存还算不算当前配方"，MUST NOT 参与标签/版本推导，也 MUST NOT
    # 被当成第二套身份。旧行没有这一列 → 读回为 NULL → 判旧一次、就地更换补齐。
    recipe_fingerprint: str | None = db.Column(db.String(64), nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            "machine_id", "image_id", name="uq_machine_image_machine_id_image_id"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MachineImage machine={self.machine_id} image={self.image_id} tag={self.image_tag}>"
