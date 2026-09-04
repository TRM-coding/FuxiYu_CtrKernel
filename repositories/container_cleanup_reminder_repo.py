"""容器清理提醒记录仓储。"""

import datetime as dt

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models.container_cleanup_reminder import ContainerCleanupReminder


def mark_sent(
    container_id: int,
    reminder_key: str,
    cleanup_at: dt.datetime,
    recipient_email: str,
    *,
    session: Session,
) -> bool:
    if was_sent(
        container_id,
        reminder_key,
        cleanup_at,
        recipient_email,
        session=session,
    ):
        return False
    row = ContainerCleanupReminder(
        container_id=int(container_id),
        reminder_key=str(reminder_key),
        cleanup_at=cleanup_at,
        recipient_email=recipient_email,
    )
    session.add(row)
    session.flush()
    return True


def was_sent(
    container_id: int,
    reminder_key: str,
    cleanup_at: dt.datetime,
    recipient_email: str,
    *,
    session: Session,
) -> bool:
    stmt = select(ContainerCleanupReminder.id).where(
        ContainerCleanupReminder.container_id == int(container_id),
        ContainerCleanupReminder.reminder_key == str(reminder_key),
        ContainerCleanupReminder.cleanup_at == cleanup_at,
        ContainerCleanupReminder.recipient_email == recipient_email,
    )
    return session.scalars(stmt).first() is not None


def clear_stale(container_id: int, current_cleanup_at: dt.datetime, *, session: Session) -> int:
    """删除同一容器中与当前 cleanup_at 不一致的旧提醒记录。"""

    result = session.execute(
        delete(ContainerCleanupReminder).where(
            ContainerCleanupReminder.container_id == int(container_id),
            ContainerCleanupReminder.cleanup_at != current_cleanup_at,
        )
    )
    session.flush()
    return int(result.rowcount or 0)
