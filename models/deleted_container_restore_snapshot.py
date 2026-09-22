"""Persisted restore input for a deleted container."""

import datetime as dt

from ..extensions import db


class DeletedContainerRestoreSnapshot(db.Model):
    __tablename__ = "deleted_container_restore_snapshot"

    id = db.Column(db.Integer, primary_key=True)
    original_container_id = db.Column(db.Integer, nullable=False, index=True)
    container_name = db.Column(db.String(120), nullable=False)
    machine_id = db.Column(db.Integer, nullable=True, index=True)
    mount_cleanup_id = db.Column(db.Integer, nullable=True, index=True)
    removed_trigger = db.Column(db.String(64), nullable=False, default="api")
    snapshot = db.Column(db.JSON, nullable=False)
    removed_at = db.Column(db.DateTime, nullable=False, default=dt.datetime.utcnow, index=True)
    mount_cleaned = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("0"), index=True)
    # 删除后机器不可用的累计时长。挂载目录保留期按"业务正常时间"计：宕机/维护期
    # 用户无法恢复，那段不算数。读侧比较 removed_at + deferral < cutoff。
    # 记录是一次性的（清理后不再复用），故不需要清零。
    deferral_seconds = db.Column(db.Integer, nullable=True, default=0, server_default=db.text("0"))

    __table_args__ = (
        db.Index("idx_deleted_container_removed", "removed_at"),
    )
