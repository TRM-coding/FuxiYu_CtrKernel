from ..extensions import db
import datetime as dt
from ..constant import *


    

class UserContainer(db.Model):
    __tablename__ = "user_container"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey("containers.id", ondelete="CASCADE"))
    role = db.Column(db.Enum(ROLE), nullable=False)
    granted_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)
    # 额外属性列：用户在该容器中的公钥与登录用户名
    public_key=db.Column("public_key", db.String(500), nullable=True)
    username=db.Column("username", db.String(120), primary_key=True)

    user = db.relationship(
        "User",
        back_populates="user_container_links",
        overlaps="containers,users"  # 添加此参数
    )
    
    container = db.relationship(
        "Container",
        back_populates="user_container_links",
        overlaps="containers,users"  # 添加此参数
    )
