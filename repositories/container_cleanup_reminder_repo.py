import datetime as dt

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.container_cleanup_reminder import ContainerCleanupReminder


def mark_sent(
    container_id: int,
    reminder_key: str,
    cleanup_at: dt.datetime,
    recipient_email: str,
) -> bool:
    row = ContainerCleanupReminder(
        container_id=int(container_id),
        reminder_key=str(reminder_key),
        cleanup_at=cleanup_at,
        recipient_email=recipient_email,
    )
    db.session.add(row)
    try:
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        return False


def was_sent(
    container_id: int,
    reminder_key: str,
    cleanup_at: dt.datetime,
    recipient_email: str,
) -> bool:
    return (
        ContainerCleanupReminder.query.filter_by(
            container_id=int(container_id),
            reminder_key=str(reminder_key),
            cleanup_at=cleanup_at,
            recipient_email=recipient_email,
        ).first()
        is not None
    )


def clear_stale(container_id: int, current_cleanup_at: dt.datetime) -> int:
    """删除同一容器中与当前 cleanup_at 不一致的旧提醒记录，返回删除条数。"""
    result = (
        ContainerCleanupReminder.query.filter(
            ContainerCleanupReminder.container_id == int(container_id),
            ContainerCleanupReminder.cleanup_at != current_cleanup_at,
        ).delete(synchronize_session="fetch")
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return 0
    return result