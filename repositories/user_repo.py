"""用户数据访问仓库

抽象出数据库访问逻辑，方便后续替换为其它存储。"""

from typing import Sequence

from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from ..models.user import User
from ..constant import PERMISSION
from .authentications_repo import get_user_id_by_token


def get_by_id(user_id: int, *, session: Session) -> User | None:
	return session.get(User, int(user_id))

def list_all_users(*, session: Session) -> Sequence[User]:
	"""全部用户（RBAC seed 存量映射用）。"""
	return list(session.scalars(select(User)).all())

def get_name_by_id(user_id:int, *, session: Session)->str|None:
    user = get_by_id(user_id, session=session)
    if user:
        return user.username
    return None


def get_by_name(username: str, *, session: Session) -> User | None:
	stmt = select(User).where(User.username == username)
	return session.scalars(stmt).first()


def get_by_email(email: str, *, session: Session) -> User | None:
	stmt = select(User).where(User.email == email)
	return session.scalars(stmt).first()


def list_users(limit: int = 50, offset: int = 0, user_search: str | None = None, visible_ids: set[int] | None = None, *, session: Session) -> Sequence[User]:
	stmt = select(User).order_by(User.id).offset(offset).limit(limit)
	if user_search:
		stmt = select(User).where(
			or_(
				User.username.ilike(keyword := f"%{user_search}%"),
				User.email.ilike(keyword),
				cast(User.id, String).ilike(keyword),
				cast(User.graduation_year, String).ilike(keyword),
			)
		).order_by(User.id).offset(offset).limit(limit)
	if visible_ids is not None:
		stmt = stmt.where(User.id.in_(visible_ids))
	return list(session.scalars(stmt).all())


def create_user(
	username: str,
	email: str,
	password_hash: str,
	graduation_year: str,
	*,
	session: Session,
) -> User:
	user = User(
		username=username,
		email=email,
		password_hash=password_hash,
		graduation_year=graduation_year,
		# permission 会使用默认值 PERMISSION.USER
	)
	session.add(user)
	session.flush()
	return user

def update_user(
    user_id: int,
    *,
    session: Session,
    **fields,
) -> User | None:
    """
    部分更新用户字段。
    使用示例:
        update_user(1, email="new@x.com", graduation_year=2026)
    """
    user = get_by_id(user_id, session=session)
    if not user:
        return None

    allowed = {"username", "email", "password_hash", "graduation_year"}
    dirty = False
    for k, v in fields.items():
        if k not in allowed:
            continue  # 忽略非法字段（也可选择抛异常）
        if v is None:
            continue  # 这里选择忽略 None；若需要可允许置空再改逻辑
        current = getattr(user, k, None)
        if current != v:
            setattr(user, k, v)
            dirty = True

    if dirty:
        session.flush()
    return user



def delete_user(user_id: int, *, session: Session) -> bool:
	user = get_by_id(user_id, session=session)
	if not user:
		return False
	session.delete(user)
	session.flush()
	return True

