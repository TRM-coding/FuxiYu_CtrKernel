"""ContainerDiskFreezeState 仓储层。"""

import datetime as dt

from sqlalchemy.orm import Session

from ..models.container_disk_freeze_state import ContainerDiskFreezeState


def get(container_id: int, *, session: Session) -> ContainerDiskFreezeState | None:
    """获取冻结状态，无记录返回 None。"""

    return session.get(ContainerDiskFreezeState, int(container_id))


def upsert_first_frozen(container_id: int, *, session: Session) -> ContainerDiskFreezeState:
    """记录首次冻结时间；已有记录时不改 first_frozen_at。"""

    container_id = int(container_id)
    existing = get(container_id, session=session)
    if existing is not None:
        return existing

    row = ContainerDiskFreezeState(
        container_id=container_id,
        first_frozen_at=dt.datetime.utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def set_grace(container_id: int, grace_days: int, *, session: Session) -> bool:
    """设置宽限期；无冻结记录时返回 False。"""

    row = get(container_id, session=session)
    if row is None:
        return False
    row.grace_until = dt.datetime.utcnow() + dt.timedelta(days=int(grace_days))
    session.flush()
    return True


def clear_grace(container_id: int, *, session: Session) -> bool:
    """清除宽限期。"""

    row = get(container_id, session=session)
    if row is None or row.grace_until is None:
        return False
    row.grace_until = None
    session.flush()
    return True


def reset(container_id: int, *, session: Session) -> bool:
    """删除冻结记录，返回是否确实删除了记录。"""

    row = get(container_id, session=session)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True
