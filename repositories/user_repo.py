"""用户数据访问仓库

抽象出数据库访问逻辑，方便后续替换为其它存储。"""

from typing import Sequence
from ..extensions import db
from ..models.user import User
from ..constant import PERMISSION
from .authentications_repo import get_user_id_by_token


def get_by_id(user_id: int) -> User | None:
	return User.query.get(user_id)

def get_name_by_id(user_id:int)->str|None:
    user=User.query.get(user_id)
    if user:
        return user.username
    return None


def get_by_name(username: str) -> User | None:
	return User.query.filter_by(username=username).first()


def list_users(limit: int = 50, offset: int = 0) -> Sequence[User]:
	return User.query.order_by(User.id).offset(offset).limit(limit).all()


def create_user(username: str, email: str, password_hash: str, graduation_year: str) -> User:
	user = User(
		username=username,
		email=email,
		password_hash=password_hash,
		graduation_year=graduation_year # 小bug，但之前没调用这个函数，故之前未报错；现已修复
		# permission 会使用默认值 PERMISSION.USER
	)
	db.session.add(user)
	db.session.commit()
	return user

def update_user(user_id: int, *, commit: bool = True, **fields) -> User | None:
    """
    部分更新用户字段。
    使用示例:
        update_user(1, email="new@x.com", graduation_year=2026)
        update_user(1, username="alice2", commit=False)  # 由调用方稍后统一提交
    """
    user = get_by_id(user_id)
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
       
       db.session.commit()
    return user



def delete_user(user_id: int) -> bool:
	user = get_by_id(user_id)
	if not user:
		return False
	db.session.delete(user)
	db.session.commit()
	return True

def check_permission(token: str, required_permission: PERMISSION) -> bool:
    user_id = get_user_id_by_token(token)

    if not user_id:
        return False
    user = get_by_id(user_id)
    if not user:
        return False

    # 这里是迎合数据库返回内容；保证兼容性。
    # 只是保险起见，一般情况下 permission 应该总是 PERMISSION 枚举类型。
    def _norm(p):
        return p.value if hasattr(p, "value") else p

    user_perm = _norm(user.permission)
    req_perm = _norm(required_permission)

    cast_permission = {
        "user": 1,
        "operator": 2,
    }

    return cast_permission.get(user_perm, 0) >= cast_permission.get(req_perm, 0)