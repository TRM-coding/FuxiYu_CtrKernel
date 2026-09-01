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


def get_by_id(record_id: int, *, session: Session) -> ContainerMountCleanup | None:
    return session.get(ContainerMountCleanup, int(record_id))


def get_latest_for_container(
    container_id: int,
    mount_path: str | None = None,
    *,
    session: Session,
) -> ContainerMountCleanup | None:
    stmt = select(ContainerMountCleanup).where(ContainerMountCleanup.container_id == int(container_id))
    if mount_path:
        stmt = stmt.where(ContainerMountCleanup.mount_path == str(mount_path))
    stmt = stmt.order_by(ContainerMountCleanup.removed_at.desc(), ContainerMountCleanup.id.desc()).limit(1)
    return session.scalars(stmt).first()


def list_records(limit: int = 1000, offset: int = 0, *, session: Session) -> list[ContainerMountCleanup]:
    stmt = (
        select(ContainerMountCleanup)
        .order_by(ContainerMountCleanup.removed_at.desc(), ContainerMountCleanup.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def mark_cleaned(record_id: int, *, session: Session, escalation: bool | None = None) -> bool:
    """标记一条记录为已清理。"""

    row = session.get(ContainerMountCleanup, int(record_id))
    if row is None:
        return False
    if escalation is not None:
        row.escalation = bool(escalation)
    row.cleaned_at = dt.datetime.utcnow()
    session.flush()
    return True
