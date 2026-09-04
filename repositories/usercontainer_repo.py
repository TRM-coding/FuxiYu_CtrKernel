"""User-Container 关联仓储。"""

from typing import Any, Optional, Sequence

from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..constant import ContainerStatus, ROLE
from ..models.containers import Container
from ..models.user import User
from ..models.usercontainer import UserContainer


class BindingRow(BaseModel):
    user_id: int
    username: Optional[str] = None
    container_id: int
    public_key: Optional[str] = None
    role: ROLE


def _binding_dict(row) -> dict:
    return {
        "user_id": row.user_id,
        "container_id": row.container_id,
        "public_key": row.public_key,
        "username": row.username,
        "role": row.role,
        "granted_at": getattr(row, "granted_at", None),
    }


def get_binding(user_id: int, container_id: int, *, session: Session) -> dict | None:
    row = session.scalars(
        select(UserContainer).where(
            UserContainer.user_id == int(user_id),
            UserContainer.container_id == int(container_id),
        )
    ).first()
    return _binding_dict(row) if row else None


def get_user_bindings(user_id: int, *, session: Session) -> Sequence[dict]:
    rows = session.scalars(
        select(UserContainer).where(UserContainer.user_id == int(user_id))
    ).all()
    return [_binding_dict(row) for row in rows]


def get_container_bindings(container_id: int, *, session: Session) -> Sequence[dict]:
    rows = session.scalars(
        select(UserContainer).where(UserContainer.container_id == int(container_id))
    ).all()
    return [_binding_dict(row) for row in rows]


def add_binding(
    user_id: int,
    container_id: int,
    role: ROLE,
    *,
    session: Session,
    public_key: str | None = None,
    username: str | None = None,
) -> bool:
    """创建绑定；若存在可补充缺失字段。"""

    if session.get(User, int(user_id)) is None or session.get(Container, int(container_id)) is None:
        return False

    existing = get_binding(user_id, container_id, session=session)
    if existing:
        if (public_key and public_key != existing.get("public_key")) or (
            username and username != existing.get("username")
        ):
            update_binding(
                user_id,
                container_id,
                public_key=public_key or existing.get("public_key"),
                username=username or existing.get("username"),
                session=session,
            )
        return True

    row = UserContainer(
        user_id=int(user_id),
        container_id=int(container_id),
        role=role.value,
        public_key=public_key,
        username=username,
    )
    session.add(row)
    session.flush()
    return True


def remove_binding(
    user_id: int,
    container_id: int,
    *,
    session: Session,
    all: bool = False,
) -> bool:
    if all:
        stmt = delete(UserContainer).where(UserContainer.container_id == int(container_id))
    else:
        stmt = delete(UserContainer).where(
            UserContainer.user_id == int(user_id),
            UserContainer.container_id == int(container_id),
        )
    result = session.execute(stmt)
    session.flush()
    return int(result.rowcount or 0) > 0


def list_containers_by_user(user_id: int, *, session: Session) -> Sequence[Container]:
    stmt = (
        select(Container)
        .join(UserContainer, Container.id == UserContainer.container_id)
        .where(UserContainer.user_id == int(user_id))
        .order_by(Container.id)
    )
    return list(session.scalars(stmt).all())


def list_users_by_container(container_id: int, *, session: Session) -> Sequence[User]:
    stmt = (
        select(User)
        .join(UserContainer, User.id == UserContainer.user_id)
        .where(UserContainer.container_id == int(container_id))
        .order_by(User.id)
    )
    return list(session.scalars(stmt).all())


def update_binding(
    user_id: int,
    container_id: int,
    *,
    session: Session,
    public_key: str | None = None,
    username: str | None = None,
    role: ROLE | None = None,
    **_extra: Any,
) -> bool:
    """部分更新绑定字段。"""

    binding = get_binding(user_id, container_id, session=session)
    if not binding:
        return False

    candidates = {
        "public_key": public_key,
        "username": username,
        "role": role.value if role else None,
    }
    update_data = {
        key: value
        for key, value in candidates.items()
        if value is not None and binding.get(key) != value
    }
    if not update_data:
        return True

    session.execute(
        update(UserContainer)
        .where(
            UserContainer.user_id == int(user_id),
            UserContainer.container_id == int(container_id),
        )
        .values(**update_data)
    )
    session.flush()
    return True


def compute_user_container_counts(user_id: int, *, session: Session) -> dict:
    """统计用户容器数量、在线数量、可管理数量。"""

    rows = list(
        session.execute(
            select(
                UserContainer.container_id,
                UserContainer.role,
                Container.container_status,
            )
            .join(Container, Container.id == UserContainer.container_id)
            .where(UserContainer.user_id == int(user_id))
        ).all()
    )
    container_ids = [row.container_id for row in rows]
    functional = 0
    managed = 0

    for row in rows:
        status = row.container_status
        status_value = status.value if hasattr(status, "value") else str(status or "")
        if status_value == ContainerStatus.ONLINE.value:
            functional += 1

        role = row.role
        role_value = role.value if hasattr(role, "value") else str(role or "")
        if role_value in (ROLE.ADMIN.value, ROLE.ROOT.value):
            managed += 1

    return {
        "container_ids": container_ids,
        "total": len(container_ids),
        "functional": functional,
        "managed": managed,
    }


def remove_user_from_all_containers(user_id: int, *, session: Session) -> dict:
    """返回删除用户前需要处理的容器绑定快照。

    具体协作者降级/删除由 service 层完成；repo 只提供当前绑定与野容器判定。
    """

    bindings = get_user_bindings(user_id, session=session) or []
    wild_containers = []
    removable = []
    transfer_required = []

    for binding in bindings:
        container_id = binding.get("container_id")
        role_value = binding.get("role")
        role_name = role_value.value if hasattr(role_value, "value") else str(role_value or "")

        if role_name.upper() != ROLE.ROOT.value.upper():
            removable.append(container_id)
            continue

        container_bindings = get_container_bindings(container_id, session=session) or []
        if len(container_bindings) <= 1:
            wild_containers.append(container_id)
            continue

        candidate = next((item for item in container_bindings if item.get("user_id") != user_id), None)
        if candidate is None:
            return {"ok": False}
        transfer_required.append(
            {
                "container_id": container_id,
                "new_root_user_id": candidate.get("user_id"),
            }
        )

    return {
        "ok": not wild_containers,
        "wild_containers": wild_containers,
        "removable": removable,
        "transfer_required": transfer_required,
    }
