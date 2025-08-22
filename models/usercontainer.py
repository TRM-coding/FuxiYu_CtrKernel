from ..extensions import db
import datetime as dt
from enum import Enum

class ROLE(Enum):
    ADMIN="admin"
    COLLABORATOR="collaborator"
    

class UserContainer(db.Model):
    __tablename__ = "user_container"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey("containers.id", ondelete="CASCADE"), primary_key=True)
    role = db.Column(db.Enum(ROLE), nullable=False)
    granted_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)

    user = db.relationship("User", back_populates="user_container_links")
    container = db.relationship("Container", back_populates="user_container_links")
