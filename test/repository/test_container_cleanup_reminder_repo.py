from datetime import datetime, timedelta

from ...repositories import container_cleanup_reminder_repo


def test_container_cleanup_reminder_repo_mark_and_check_sent(db_session):
    cleanup_at = datetime.utcnow() + timedelta(hours=12)

    assert container_cleanup_reminder_repo.mark_sent(1, "12h", cleanup_at, "u@bjtu.edu.cn", session=db_session) is True
    assert container_cleanup_reminder_repo.was_sent(1, "12h", cleanup_at, "u@bjtu.edu.cn", session=db_session) is True
    assert container_cleanup_reminder_repo.mark_sent(1, "12h", cleanup_at, "u@bjtu.edu.cn", session=db_session) is False


def test_container_cleanup_reminder_repo_separates_threshold_cleanup_at_and_email(db_session):
    cleanup_at = datetime.utcnow() + timedelta(hours=12)
    other_cleanup_at = cleanup_at + timedelta(minutes=1)
    container_cleanup_reminder_repo.mark_sent(1, "12h", cleanup_at, "u@bjtu.edu.cn", session=db_session)

    assert container_cleanup_reminder_repo.was_sent(1, "24h", cleanup_at, "u@bjtu.edu.cn", session=db_session) is False
    assert container_cleanup_reminder_repo.was_sent(1, "12h", other_cleanup_at, "u@bjtu.edu.cn", session=db_session) is False
    assert container_cleanup_reminder_repo.was_sent(1, "12h", cleanup_at, "other@bjtu.edu.cn", session=db_session) is False
