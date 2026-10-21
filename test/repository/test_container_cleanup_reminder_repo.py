from datetime import datetime, timedelta

from sqlalchemy import select

from ...models.container_cleanup_reminder import NEVER_REMINDED, ContainerCleanupReminder
from ...repositories import container_cleanup_reminder_repo


def test_container_cleanup_reminder_repo_mark_and_check_sent(db_session):
    cleanup_at = datetime.utcnow() + timedelta(hours=12)

    assert container_cleanup_reminder_repo.mark_sent(1, "12h", cleanup_at, "u@bjtu.edu.cn", session=db_session) is True
    assert container_cleanup_reminder_repo.was_sent(1, "12h", "u@bjtu.edu.cn", session=db_session) is True
    assert container_cleanup_reminder_repo.mark_sent(1, "12h", cleanup_at, "u@bjtu.edu.cn", session=db_session) is False


def test_container_cleanup_reminder_repo_separates_level_and_email(db_session):
    cleanup_at = datetime.utcnow() + timedelta(hours=12)
    container_cleanup_reminder_repo.mark_sent(1, "12h", cleanup_at, "u@bjtu.edu.cn", session=db_session)

    assert container_cleanup_reminder_repo.was_sent(1, "24h", "u@bjtu.edu.cn", session=db_session) is False
    assert container_cleanup_reminder_repo.was_sent(1, "12h", "other@bjtu.edu.cn", session=db_session) is False


def test_container_cleanup_reminder_repo_advances_level_in_place(db_session):
    """档位推进是**更新同一行**，不是新增一行——一行一状态，判重才成立。"""

    cleanup_at = datetime.utcnow() + timedelta(hours=12)
    container_cleanup_reminder_repo.mark_sent(1, "72h", cleanup_at, "u@bjtu.edu.cn", session=db_session)
    container_cleanup_reminder_repo.mark_sent(1, "24h", cleanup_at, "u@bjtu.edu.cn", session=db_session)

    rows = db_session.scalars(select(ContainerCleanupReminder)).all()
    assert len(rows) == 1
    assert rows[0].reminder_key == "24h"
    assert container_cleanup_reminder_repo.was_sent(1, "24h", "u@bjtu.edu.cn", session=db_session) is True
    assert container_cleanup_reminder_repo.was_sent(1, "72h", "u@bjtu.edu.cn", session=db_session) is False


def test_container_cleanup_reminder_repo_reset_to_never_only_touches_that_container(db_session):
    """周期复位只作废本容器的档位——同机器上别的容器不该被连坐。"""

    cleanup_at = datetime.utcnow() + timedelta(hours=12)
    container_cleanup_reminder_repo.mark_sent(1, "12h", cleanup_at, "u@bjtu.edu.cn", session=db_session)
    container_cleanup_reminder_repo.mark_sent(2, "12h", cleanup_at, "u@bjtu.edu.cn", session=db_session)

    assert container_cleanup_reminder_repo.reset_to_never(1, session=db_session) == 1

    assert container_cleanup_reminder_repo.was_sent(1, "12h", "u@bjtu.edu.cn", session=db_session) is False
    assert container_cleanup_reminder_repo.was_sent(2, "12h", "u@bjtu.edu.cn", session=db_session) is True
    row = db_session.scalars(
        select(ContainerCleanupReminder).where(ContainerCleanupReminder.container_id == 1)
    ).one()
    assert row.reminder_key == NEVER_REMINDED
