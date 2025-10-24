from datetime import datetime
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

	containers = db.relationship(
		"Container",
		secondary="user_container",
		back_populates="users",
		lazy="dynamic",  # 如果想直接 .all()；不需要可改为 selectin
	)

	user_container_links = db.relationship(
        "UserContainer",
        back_populates="user",
        cascade="all, delete-orphan"
    )

	def __repr__(self) -> str:  # pragma: no cover 简单repr无需测试
		return f"<User {self.username}>"


@login_manager.user_loader
def load_user(user_id: str):
	return User.query.get(int(user_id))



