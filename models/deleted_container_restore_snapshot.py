"""Persisted restore input for a deleted container."""

import datetime as dt

from ..extensions import db


class DeletedContainerRestoreSnapshot(db.Model):
    __tablename__ = "deleted_container_restore_snapshot"

    id = db.Column(db.Integer, primary_key=True)
    original_container_id = db.Column(db.Integer, nullable=False, index=True)
    container_name = db.Column(db.String(120), nullable=False)
    machine_id = db.Column(db.Integer, nullable=True, index=True)
    machine_name = db.Column(db.String(120), nullable=True)
    machine_ip = db.Column(db.String(100), nullable=True)
    mount_path = db.Column(db.String(512), nullable=True)
    mount_cleanup_id = db.Column(db.Integer, nullable=True, index=True)
    removed_trigger = db.Column(db.String(64), nullable=False, default="api")
    operator_user_id = db.Column(db.Integer, nullable=True)
    snapshot = db.Column(db.JSON, nullable=False)
    removed_at = db.Column(db.DateTime, nullable=False, default=dt.datetime.utcnow, index=True)

    __table_args__ = (
        db.Index("idx_deleted_container_removed", "removed_at"),
    )
