"""Repository for deleted container restore snapshots."""

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot


def insert(
    snapshot: dict[str, Any],
    *,
    session: Session,
    mount_cleanup_id: int | None = None,
    mount_path: str | None = None,
    removed_trigger: str = "api",
    operator_user_id: int | None = None,
    removed_at: dt.datetime | None = None,
) -> DeletedContainerRestoreSnapshot:
    row = DeletedContainerRestoreSnapshot(
        original_container_id=int(snapshot.get("container_id") or 0),
        container_name=str(snapshot.get("container_name") or ""),
        machine_id=snapshot.get("machine_id"),
        machine_name=snapshot.get("machine_name"),
        machine_ip=snapshot.get("machine_ip"),
        mount_path=mount_path or snapshot.get("bind_mount_path"),
        mount_cleanup_id=mount_cleanup_id,
        removed_trigger=str(removed_trigger or "api"),
        operator_user_id=operator_user_id,
        snapshot=snapshot,
        removed_at=removed_at or dt.datetime.utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def get_by_id(record_id: int, *, session: Session) -> DeletedContainerRestoreSnapshot | None:
    return session.get(DeletedContainerRestoreSnapshot, int(record_id))


def list_records(
    *,
    session: Session,
    limit: int = 20,
    offset: int = 0,
) -> list[DeletedContainerRestoreSnapshot]:
    stmt = (
        select(DeletedContainerRestoreSnapshot)
        .order_by(DeletedContainerRestoreSnapshot.removed_at.desc(), DeletedContainerRestoreSnapshot.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def count_records(*, session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(DeletedContainerRestoreSnapshot)) or 0)


def delete(record_id: int, *, session: Session) -> bool:
    row = get_by_id(record_id, session=session)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True
