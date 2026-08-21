"""ContainerMountCleanup 仓储层。"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.container_mount_cleanup import ContainerMountCleanup


def insert(
    container_id: int,
    container_name: str,
    machine_id: int,
    mount_path: str,
    escalation: bool = False,
    removed_at: dt.datetime | None = None,
    cleaned_at: dt.datetime | None = None,
    *,
    session: Session,
) -> ContainerMountCleanup:
    """插入一条 mount 清理追踪记录。"""

    row = ContainerMountCleanup(
        container_id=int(container_id),
        container_name=str(container_name),
        machine_id=int(machine_id),
        mount_path=str(mount_path),
        escalation=bool(escalation),
        removed_at=removed_at or dt.datetime.utcnow(),
        cleaned_at=cleaned_at,
    )
    session.add(row)
    session.flush()
    return row


def list_pending(cutoff: dt.datetime, limit: int = 100, *, session: Session) -> list[ContainerMountCleanup]:
    """查询待清理记录。"""

    stmt = (
        select(ContainerMountCleanup)
        .where(
            ContainerMountCleanup.cleaned_at.is_(None),
            ContainerMountCleanup.escalation.is_(False),
            ContainerMountCleanup.removed_at < cutoff,
        )
        .order_by(ContainerMountCleanup.removed_at.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def mark_cleaned(record_id: int, *, session: Session) -> bool:
    """标记一条记录为已清理。"""

    row = session.get(ContainerMountCleanup, int(record_id))
    if row is None:
        return False
    row.cleaned_at = dt.datetime.utcnow()
    session.flush()
    return True
