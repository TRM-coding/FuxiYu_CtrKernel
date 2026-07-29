"""已删除容器的 mount 清理追踪。

容器删除时记录 mount 路径。
- escalation=False → 14 天后定期清理
- escalation=True  → 立刻清理（宽限期已是最后机会）
"""

import datetime as dt

from ..extensions import db


class ContainerMountCleanup(db.Model):
    __tablename__ = "container_mount_cleanup"

    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, nullable=False)
    container_name = db.Column(db.String(120), nullable=False)
    machine_id = db.Column(db.Integer, nullable=False)
    mount_path = db.Column(db.String(512), nullable=False)
    escalation = db.Column(db.Boolean, nullable=False, default=False)
    removed_at = db.Column(db.DateTime, nullable=False)
    cleaned_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index("idx_mount_cleanup_pending", "cleaned_at", "removed_at"),
    )
