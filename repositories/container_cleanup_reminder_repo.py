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


def ensure_table() -> None:
    engine = db.engine
    dialect = engine.dialect.name
    if dialect == "mysql":
        sql = """
        CREATE TABLE IF NOT EXISTS container_cleanup_reminders (
            id INT NOT NULL AUTO_INCREMENT,
            container_id INT NOT NULL,
            reminder_key VARCHAR(32) NOT NULL,
            cleanup_at DATETIME NOT NULL,
            recipient_email VARCHAR(120) NOT NULL,
            sent_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uq_container_cleanup_reminder_once
                (container_id, reminder_key, cleanup_at, recipient_email),
            KEY ix_container_cleanup_reminders_container_id (container_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    else:
        sql = """
        CREATE TABLE IF NOT EXISTS container_cleanup_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_id INTEGER NOT NULL,
            reminder_key VARCHAR(32) NOT NULL,
            cleanup_at DATETIME NOT NULL,
            recipient_email VARCHAR(120) NOT NULL,
            sent_at DATETIME NOT NULL,
            UNIQUE (container_id, reminder_key, cleanup_at, recipient_email)
        )
        """
    with engine.begin() as conn:
        conn.execute(sa.text(sql))
