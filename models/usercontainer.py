from ..extensions import db
import datetime as dt
from ..constant import *


    

class UserContainer(db.Model):
    __tablename__ = "user_container"

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True
    )
    container_id = db.Column(
        db.Integer,
        db.ForeignKey("containers.id", ondelete="CASCADE"),
        primary_key=True,  # 现在作为复合主键的一部分
        nullable=False
    )

    role = db.Column(db.Enum(ROLE), nullable=False)
    granted_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)
    public_key = db.Column(db.String(500), nullable=True)
    username = db.Column(db.String(120), nullable=False)  # 不再是主键，必要时可建索引

    user = db.relationship(
        "User",
        back_populates="user_container_links",
        overlaps="containers,users"
    )
    container = db.relationship(
        "Container",
        back_populates="user_container_links",
        overlaps="containers,users"
    )