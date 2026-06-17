from datetime import datetime

from ..extensions import db


class OperationLog(db.Model):
    __tablename__ = "operation_logs"

    id = db.Column(db.Integer, primary_key=True)
    operator_user_id = db.Column(db.Integer, nullable=True)
    operation = db.Column(db.String(80), nullable=False)
    target_type = db.Column(db.String(80), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    detail = db.Column(db.JSON, nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=True)
    error_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
