from datetime import datetime

from ..extensions import db


class SystemSetting(db.Model):
    """系统级可编辑设置。

    value 使用 Text，避免 Dockerfile 注入模板、长文本策略等配置被长度截断。
    """

    __tablename__ = "system_settings"

    id: int = db.Column(db.Integer, primary_key=True)
    key: str = db.Column(db.String(120), unique=True, nullable=False, index=True)
    value: str = db.Column(db.Text, nullable=False)
    description: str | None = db.Column(db.String(500), nullable=True)
    created_at: datetime = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    updated_at: datetime = db.Column(
        db.DateTime,
        default=db.func.now(),
        onupdate=db.func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SystemSetting {self.key}>"
