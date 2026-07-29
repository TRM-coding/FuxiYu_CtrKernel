"""ContainerMountCleanup 仓储层。

提供 mount 清理追踪记录的插入、查询待清理、标记已清理。
"""

import datetime as dt

from ..extensions import db
from ..models.container_mount_cleanup import ContainerMountCleanup


def insert(
    container_id: int,
    container_name: str,
    machine_id: int,
    mount_path: str,
    escalation: bool = False,
    removed_at: dt.datetime | None = None,
    cleaned_at: dt.datetime | None = None,
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
    db.session.add(row)
    db.session.commit()
    return row


def list_pending(cutoff: dt.datetime, limit: int = 100) -> list[ContainerMountCleanup]:
    """查询待清理的记录（cleaned_at IS NULL, escalation=False, removed_at < cutoff）。"""
    return (
        db.session.query(ContainerMountCleanup)
        .filter(
            ContainerMountCleanup.cleaned_at.is_(None),
            ContainerMountCleanup.escalation.is_(False),
            ContainerMountCleanup.removed_at < cutoff,
        )
        .order_by(ContainerMountCleanup.removed_at.asc())
        .limit(limit)
        .all()
    )


def mark_cleaned(record_id: int) -> bool:
    """标记一条记录为已清理。"""
    row = db.session.get(ContainerMountCleanup, int(record_id))
    if row is None:
        return False
    row.cleaned_at = dt.datetime.utcnow()
    db.session.commit()
    return True
