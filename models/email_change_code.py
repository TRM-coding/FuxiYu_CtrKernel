from datetime import datetime

from ..extensions import db


class EmailChangeCode(db.Model):
    __tablename__ = "email_change_codes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    new_email = db.Column(db.String(120), nullable=False, index=True)
    school_domain = db.Column(db.String(80), nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<EmailChangeCode user_id={self.user_id} new_email={self.new_email}>"
