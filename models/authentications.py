from datetime import datetime
from ..extensions import db


class Authentication(db.Model):
    __tablename__ = "authentications"
    
    token = db.Column(db.String(255), primary_key=True, unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    
    def __repr__(self) -> str:
        return f"<Authentication token={self.token[:8]}...>"
