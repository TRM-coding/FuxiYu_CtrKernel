"""User-Container 关联仓储
封装用户与容器之间的多对多显式操作，便于未来扩展（如角色/授权时间）。
"""
from typing import Sequence, Any, Optional
from pydantic import BaseModel
from ..extensions import db
from ..models.user import User
from ..models.containers import Container
from ..models.usercontainer import UserContainer
from ..constant import ROLE, ContainerStatus
from . import containers_repo

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

# 加入这个方法主要是提供更好的界面统计数据
def compute_user_container_counts(user_id: int) -> dict:
    bindings = get_user_bindings(user_id) or []
    container_ids = [b.get('container_id') for b in bindings]
    total = len(container_ids)
    functional = 0
    managed = 0

    for b in bindings:
        try:
            role_val = b.get('role')
            cid = b.get('container_id')
            if cid is None:
                continue

            # fetch container to check status
            container = containers_repo.get_by_id(int(cid))
            is_online = False
            if container and getattr(container, 'container_status', None) is not None:
                try:
                    is_online = (
                        container.container_status == ContainerStatus.ONLINE
                        or getattr(container.container_status, 'value', None) == ContainerStatus.ONLINE.value
                    )
                except Exception:
                    is_online = (str(container.container_status).lower() == ContainerStatus.ONLINE.value)

            if is_online:
                functional += 1

            # 这里是有时候会检测不到 故做了这样的设计
            # 这里因为枚举是str，所以做了一次统一转换
            try:
                if isinstance(role_val, ROLE):
                    role_name = role_val.value
                else:
                    role_name = str(role_val)
            except Exception:
                role_name = str(role_val)

            if role_name == ROLE.ADMIN.value or role_name == ROLE.ROOT.value:
                managed += 1
        except Exception:
            continue

    return {
        'container_ids': container_ids,
        'total': total,
        'functional': functional,
        'managed': managed,
    }


def remove_user_from_all_containers(user_id: int) -> dict:
    """
    业务如下：

    对目标用户所对应的所有非root身份的容器，做container_task.remove_collaborator即可；
    对是root且他是唯一用户的，返回false，使得APi返回success 0，并提示“Wild container NOT allowed. Must remove all affected containers first.”
    对是root且不是唯一用户的：（1）对第一位是root的做update_role为root；（2）对目标需要删除的用户做update_role为collaborator；（3）对目标需要删除的用户做remove_collaborator。
    直到相关联的容器全部删除，方可返回true。
    """
    bindings = get_user_bindings(user_id) or []
    # local import to avoid circular import at module load
    try:
        from ..services import container_tasks
    except Exception:
        # unable to import service layer
        return {"ok": False}

    wild_containers = []

    for b in bindings:
        cid = b.get('container_id')
        role_val = b.get('role')
        try:
            if isinstance(role_val, ROLE):
                role_name = role_val.value
            else:
                role_name = str(role_val or '')
        except Exception:
            role_name = str(role_val or '')

        if str(role_name).upper() != ROLE.ROOT.value.upper():
            # non-root: simply remove collaborator
            ok = container_tasks.remove_collaborator(container_id=cid, user_id=user_id)
            if not ok:
                return {"ok": False}
            # continue to next binding
            continue

        # role is ROOT
        container_bindings = get_container_bindings(cid) or []
        if len(container_bindings) <= 1:
            # this is a wild container (only root owner) — cannot proceed
            wild_containers.append(cid)
            # do not proceed with modifications for this container
            continue

        # find a candidate to promote (first user that is not the target)
        candidate = None
        for cb in container_bindings:
            if cb.get('user_id') != user_id:
                candidate = cb
                break
        if not candidate:
            return {"ok": False}

        new_root_uid = candidate.get('user_id')

        # promote candidate to ROOT
        ok = container_tasks.update_role(container_id=cid, user_id=new_root_uid, updated_role=ROLE.ROOT)
        if not ok:
            return {"ok": False}

        # demote target to COLLABORATOR
        ok = container_tasks.update_role(container_id=cid, user_id=user_id, updated_role=ROLE.COLLABORATOR)
        if not ok:
            return {"ok": False}

        # finally remove the (now non-root) collaborator
        ok = container_tasks.remove_collaborator(container_id=cid, user_id=user_id)
        if not ok:
            return {"ok": False}

    if wild_containers:
        return {"ok": False, "wild_containers": wild_containers}

    return {"ok": True}


