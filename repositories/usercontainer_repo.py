"""User-Container 关联仓储
封装用户与容器之间的多对多显式操作，便于未来扩展（如角色/授权时间）。
"""
from typing import Sequence, Any
from pydantic import BaseModel
from ..extensions import db
from ..models.user import User
from ..models.containers import Container
from ..models.usercontainer import UserContainer as user_containers
from ..constant import ROLE


class BindingRow(BaseModel, total=False):
    user_id: int
    username: str | None
    container_id: int
    public_key: str | None
    role:ROLE


def get_binding(user_id: int, container_id: int) -> BindingRow | None:
    row = db.session.execute(
        db.select(
            user_containers.c.user_id,
            user_containers.c.container_id,
            user_containers.c.public_key,
            user_containers.c.username,
        ).where(
            user_containers.c.user_id == user_id,
            user_containers.c.container_id == container_id,
        )
    ).first()
    if not row:
        return None
    return {
        "user_id": row.user_id,
        "container_id": row.container_id,
        "public_key": row.public_key,
        "username": row.username,
        "role":row.role,
    }

def get_user_bindings(user_id:int)->Sequence[BindingRow]:
    rows = db.session.execute(
        db.select(
            user_containers.c.user_id,
            user_containers.c.container_id,
            user_containers.c.public_key,
            user_containers.c.username,
        ).where(
            user_containers.c.user_id == user_id,
        )
    ).all()
    bindings=[]
    for row in rows:
        bindings.append({
            "user_id": row.user_id,
            "container_id": row.container_id,
            "public_key": row.public_key,
            "username": row.username,
            "role":row.role,
        })
    return bindings

def get_container_bindings(container_id:int)->Sequence[BindingRow]:
    rows = db.session.execute(
        db.select(
            user_containers.c.user_id,
            user_containers.c.container_id,
            user_containers.c.public_key,
            user_containers.c.username,
        ).where(
            user_containers.c.container_id == container_id,
        )
    ).all()
    bindings=[]
    for row in rows:
        bindings.append({
            "user_id": row.user_id,
            "container_id": row.container_id,
            "public_key": row.public_key,
            "username": row.username,
            "role":row.role,
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
    insert_values: dict[str, Any] = {"user_id": user_id, "container_id": container_id, "role":role.value}
    if public_key is not None:
        insert_values["public_key"] = public_key
    if username is not None:
        insert_values["username"] = username
    db.session.execute(user_containers.insert().values(**insert_values))
    if commit:
        db.session.commit()
    return True


def remove_binding(user_id: int, container_id: int, commit: bool = True,all=False) -> bool:
    result = db.session.execute(
        user_containers.delete().where(
            user_containers.c.user_id == user_id,
            user_containers.c.container_id == container_id,
        )
    )
    if all:
        result = db.session.execute(
            user_containers.delete().where(
                user_containers.c.container_id == container_id,
            )
        )
    if commit:
        db.session.commit()
    return result.rowcount > 0


def list_containers_by_user(user_id: int) -> Sequence[Container]:
    return (
        db.session.query(Container)
        .join(user_containers, Container.id == user_containers.c.container_id)
        .filter(user_containers.c.user_id == user_id)
        .order_by(Container.id)
        .all()
    )


def list_users_by_container(container_id: int) -> Sequence[User]:
    return (
        db.session.query(User)
        .join(user_containers, User.id == user_containers.c.user_id)
        .filter(user_containers.c.container_id == container_id)
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
    role:ROLE|None=None,
    **_extra,
) -> bool:
    """部分更新绑定字段，遵循统一 update 模式 (白名单 + 仅变更写入)。"""
    binding = get_binding(user_id, container_id)
    if not binding:
        return False

    allowed = {"public_key", "username","role"}
    # 构造候选字段
    candidates = {"public_key": public_key, "username": username,"role":role}
    update_data: dict[str, Any] = {}
    for k, v in candidates.items():
        if k not in allowed or v is None:
            continue
        if binding.get(k) != v:
            update_data[k] = v

    if not update_data:
        return True  # 无变化

    db.session.execute(
        user_containers.update()
        .where(
            user_containers.c.user_id == user_id,
            user_containers.c.container_id == container_id,
        )
        .values(**update_data)
    )
    if commit:
        db.session.commit()
    return True


