"""用户数据访问仓库

抽象出数据库访问逻辑，方便后续替换为其它存储。"""

from typing import Sequence
from ..extensions import db
from ..models.user import User


def get_by_id(user_id: int) -> User | None:
	return User.query.get(user_id)


def get_by_username(username: str) -> User | None:
	return User.query.filter_by(username=username).first()


def list_users(limit: int = 50, offset: int = 0) -> Sequence[User]:
	return User.query.order_by(User.id).offset(offset).limit(limit).all()


def create_user(username: str, email: str, password_hash: str,graduation_year) -> User:
	user = User(username=username, 
			    email=email, 
				password_hash=password_hash,
				graduation_hash=graduation_year)
	db.session.add(user)
	db.session.commit()
	return user


def delete_user(user_id: int) -> bool:
	user = get_by_id(user_id)
	if not user:
		return False
	db.session.delete(user)
	db.session.commit()
	return True


