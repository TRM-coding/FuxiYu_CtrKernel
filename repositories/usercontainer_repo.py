"""User-Container 关联仓储
封装用户与容器之间的多对多显式操作，便于未来扩展（如角色/授权时间）。
"""
from typing import Sequence, Any, Optional
from pydantic import BaseModel
from ..extensions import db
from ..models.user import User
from ..models.containers import Container
from ..models.usercontainer import UserContainer
from ..constant import ROLE

# 使用底层 Table 以便 Core 风格操作
uc = UserContainer.__table__


class BindingRow(BaseModel):
    user_id: int
    username: Optional[str] = None
    container_id: int
    public_key: Optional[str] = None
    role: ROLE


def get_binding(user_id: int, container_id: int) -> dict | None:
    row = db.session.execute(
        db.select(
            uc.c.user_id,
            uc.c.container_id,
            uc.c.public_key,
            uc.c.username,
            uc.c.role,
        ).where(
            uc.c.user_id == user_id,
            uc.c.container_id == container_id,
        )
    ).first()
    if not row:
        return None
    return {
        "user_id": row.user_id,
        "container_id": row.container_id,
        "public_key": row.public_key,
        "username": row.username,
        "role": row.role,
    }

def get_user_bindings(user_id:int)->Sequence[dict]:
    rows = db.session.execute(
        db.select(
            uc.c.user_id,
            uc.c.container_id,
            uc.c.public_key,
            uc.c.username,
            uc.c.role,
        ).where(
            uc.c.user_id == user_id,
        )
    ).all()
    bindings=[]
    for row in rows:
        bindings.append({
            "user_id": row.user_id,
            "container_id": row.container_id,
            "public_key": row.public_key,
            "username": row.username,
            "role": row.role,
        })
    return bindings

def get_container_bindings(container_id:int)->Sequence[dict]:
    rows = db.session.execute(
        db.select(
            uc.c.user_id,
            uc.c.container_id,
            uc.c.public_key,
            uc.c.username,
            uc.c.role,
        ).where(
            uc.c.container_id == container_id,
        )
    ).all()
    bindings=[]
    for row in rows:
        bindings.append({
            "user_id": row.user_id,
            "container_id": row.container_id,
            "public_key": row.public_key,
            "username": row.username,
            "role": row.role,
        })
    return bindings


def add_binding(
    user_id: int,
    container_id: int,
    role:ROLE,
    *,
    public_key: str | None = None,
    username: str | None = None,
    commit: bool = True,
) -> bool:
    """创建绑定（若存在可选择补充缺失字段）。"""
    if not User.query.get(user_id) or not Container.query.get(container_id):
        return False
    existing = get_binding(user_id, container_id)
    if existing:
        # 若已有绑定但传入新值且不同，调用 update_binding
        if (public_key and public_key != existing.get("public_key")) or (
            username and username != existing.get("username")
        ):
            update_binding(
                user_id,
                container_id,
                public_key=public_key or existing.get("public_key"),
                username=username or existing.get("username"),
                commit=commit,
            )
        return True
    insert_values: dict[str, Any] = {
        "user_id": user_id,
        "container_id": container_id,
        "role": role.value,
    }
    if public_key is not None:
        insert_values["public_key"] = public_key
    if username is not None:
        insert_values["username"] = username
    db.session.execute(uc.insert().values(**insert_values))
    if commit:
        db.session.commit()
    return True


def remove_binding(user_id: int, container_id: int, commit: bool = True, all=False) -> bool:
    if all:
        result = db.session.execute(
            uc.delete().where(
                uc.c.container_id == container_id,
            )
        )
    else:
        result = db.session.execute(
            uc.delete().where(
                uc.c.user_id == user_id,
                uc.c.container_id == container_id,
            )
        )
    if commit:
        db.session.commit()
    return result.rowcount > 0


def list_containers_by_user(user_id: int) -> Sequence[Container]:
    return (
        db.session.query(Container)
        .join(uc, Container.id == uc.c.container_id)
        .filter(uc.c.user_id == user_id)
        .order_by(Container.id)
        .all()
    )


def list_users_by_container(container_id: int) -> Sequence[User]:
    return (
        db.session.query(User)
        .join(uc, User.id == uc.c.user_id)
        .filter(uc.c.container_id == container_id)
        .order_by(User.id)
        .all()
    )


def update_binding(
    user_id: int,
    container_id: int,
    *,
    public_key: str | None = None,
    username: str | None = None,
    commit: bool = True,
    role: ROLE | None = None,
    **_extra,
) -> bool:
    """部分更新绑定字段，遵循统一 update 模式 (白名单 + 仅变更写入)。"""
    binding = get_binding(user_id, container_id)
    if not binding:
        return False

    allowed = {"public_key", "username", "role"}
    candidates = {"public_key": public_key, "username": username, "role": role.value if role else None}
    update_data: dict[str, Any] = {}
    for k, v in candidates.items():
        if k not in allowed or v is None:
            continue
        if binding.get(k) != v:
            update_data[k] = v

    if not update_data:
        return True  # 无变化

    db.session.execute(
        uc.update()
        .where(
            uc.c.user_id == user_id,
            uc.c.container_id == container_id,
        )
        .values(**update_data)
    )
    if commit:
        db.session.commit()
    return True


