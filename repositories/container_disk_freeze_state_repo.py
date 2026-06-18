"""ContainerDiskFreezeState 仓储层。

提供冻结升级状态的查询、记录、宽限期管理、重置操作。
"""

import datetime as dt

from ..extensions import db
from ..models.container_disk_freeze_state import ContainerDiskFreezeState


def get(container_id: int) -> ContainerDiskFreezeState | None:
    """获取冻结状态，无记录返回 None。"""
    return db.session.get(ContainerDiskFreezeState, int(container_id))


def upsert_first_frozen(container_id: int) -> ContainerDiskFreezeState:
    """记录首次冻结时间。

    - 已有记录：直接返回（first_frozen_at 不变，grace_until 不动）
    - 无记录：新建，first_frozen_at = utcnow
    """
    container_id = int(container_id)
    existing = get(container_id)
    if existing is not None:
        return existing

    row = ContainerDiskFreezeState(
        container_id=container_id,
        first_frozen_at=dt.datetime.utcnow(),
    )
    db.session.add(row)
    db.session.commit()
    return row


def set_grace(container_id: int, grace_days: int) -> bool:
    """设置宽限期（管理员解冻时调用）。

    无冻结记录时返回 False（无意义操作）。
    grace_until = utcnow + grace_days。
    多次调用会续期（覆盖旧值）。
    """
    row = get(container_id)
    if row is None:
        return False
    row.grace_until = dt.datetime.utcnow() + dt.timedelta(days=int(grace_days))
    db.session.commit()
    return True


def clear_grace(container_id: int) -> bool:
    """清除宽限期（到期后恢复冻结时调用）。"""
    row = get(container_id)
    if row is None or row.grace_until is None:
        return False
    row.grace_until = None
    db.session.commit()
    return True


def reset(container_id: int) -> bool:
    """删除冻结记录（容量回落时调用）。返回是否确实删除了记录。"""
    row = get(container_id)
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True
