from datetime import datetime

from ..constant import PERMISSION
from ..extensions import db, login_manager
from flask_login import UserMixin



class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    graduation_year=db.Column(db.String(120),unique=False,nullable=False)
    permission=db.Column(
        db.Enum(PERMISSION, values_callable=lambda obj: [e.value for e in obj]),
        default=PERMISSION.USER,
        nullable=False
    )

    containers = db.relationship(
        "Container",
        secondary="user_container",
        back_populates="users",
        lazy="dynamic",
        overlaps="user_container_links"  # 添加此参数
    )

    user_container_links = db.relationship(
        "UserContainer",
        back_populates="user",
        cascade="all, delete-orphan",
        overlaps="containers"  # 添加此参数
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))