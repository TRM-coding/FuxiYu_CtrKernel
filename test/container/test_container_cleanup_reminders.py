from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, select

from ...models.container_cleanup_reminder import ContainerCleanupReminder
from ...models.operation_log import OperationLog

from ...repositories import container_cleanup_reminder_repo
from ...schedulers import container_cleanup_task
from ..factories import create_container_graph


@pytest.mark.parametrize("raises", [False, True])
def test_each_failed_mail_retry_is_audited(db_session, monkeypatch, raises):
    _root, _machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=48)
    monkeypatch.setattr(container_cleanup_task.containers_repo, "get_container_root_owner_emails",
                        lambda *args, **kwargs: ["owner@example.test"])
    attempts = []

    def send(**kwargs):
        attempts.append(kwargs)
        if raises:
            raise RuntimeError("smtp unavailable")
        return {"ok": False, "error": "smtp unavailable"}

    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp", send)
    info = {"cleanup_status": "countdown", "seconds_until_cleanup": 48 * 3600,
            "cleanup_at": cleanup_at.isoformat()}
    for _ in range(3):
        container_cleanup_task._send_cleanup_reminders_if_needed(container.id, info, "72,24,12")
    # A nearer threshold is another real attempt and must also be audited.
    info["seconds_until_cleanup"] = 23 * 3600
    container_cleanup_task._send_cleanup_reminders_if_needed(container.id, info, "72,24,12")
    logs = db_session.scalars(select(OperationLog).where(OperationLog.operation == "send_cleanup_reminder")).all()
    assert len(logs) == 4
    assert len(attempts) == 4
    assert not container_cleanup_reminder_repo.was_sent(
        container.id, "72h", cleanup_at, "owner@example.test", session=db_session)


def test_parse_reminder_hours_filters_invalid_and_deduplicates():
    assert container_cleanup_task._parse_reminder_hours("72,bad,24,72,0,-1,12") == [72, 24, 12]


def test_send_cleanup_reminder_skips_non_countdown(monkeypatch):
    calls = []
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    container_cleanup_task._send_cleanup_reminders_if_needed(1, {"cleanup_status": "due"})

    assert calls == []


def test_send_cleanup_reminder_skips_without_owner_email(monkeypatch):
    calls = []
    monkeypatch.setattr(container_cleanup_task.containers_repo, "get_container_root_owner_emails", lambda container_id, **kwargs: [])
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    container_cleanup_task._send_cleanup_reminders_if_needed(
        1,
        {
            "cleanup_status": "countdown",
            "seconds_until_cleanup": 3600,
            "cleanup_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        },
    )

    assert calls == []


def test_send_cleanup_reminder_skips_when_already_sent(app, db_session, monkeypatch):
    _root, _machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    container_cleanup_reminder_repo.mark_sent(container.id, "12h", cleanup_at, "owner@bjtu.edu.cn", session=db_session)
    calls = []
    monkeypatch.setattr(container_cleanup_task.containers_repo, "get_container_root_owner_emails", lambda container_id, **kwargs: ["owner@bjtu.edu.cn"])
    monkeypatch.setattr(container_cleanup_task.container_tasks, "build_container_restore_snapshot", lambda *args, **kwargs: {"container_name": "c"})
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    db_session.commit()
    container_cleanup_task._send_cleanup_reminders_if_needed(
        container.id,
        {
            "cleanup_status": "countdown",
            "seconds_until_cleanup": 3600,
            "cleanup_at": cleanup_at.isoformat(),
        },
    )

    assert calls == []


def test_send_cleanup_reminder_marks_sent_after_mail_success(app, db_session, monkeypatch):
    _root, _machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    monkeypatch.setattr(container_cleanup_task.containers_repo, "get_container_root_owner_emails", lambda container_id, **kwargs: ["owner@bjtu.edu.cn"])
    monkeypatch.setattr(container_cleanup_task.container_tasks, "build_container_restore_snapshot", lambda *args, **kwargs: {"container_name": "c"})
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp", lambda **kwargs: {"ok": True})

    container_cleanup_task._send_cleanup_reminders_if_needed(
        container.id,
        {
            "cleanup_status": "countdown",
            "seconds_until_cleanup": 3600,
            "cleanup_at": cleanup_at.isoformat(),
        },
    )

    assert container_cleanup_reminder_repo.was_sent(container.id, "12h", cleanup_at, "owner@bjtu.edu.cn", session=db_session) is True


def test_send_cleanup_reminder_does_not_mark_sent_after_mail_failure(app, db_session, monkeypatch):
    _root, _machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    monkeypatch.setattr(container_cleanup_task.containers_repo, "get_container_root_owner_emails", lambda container_id, **kwargs: ["owner@bjtu.edu.cn"])
    monkeypatch.setattr(container_cleanup_task.container_tasks, "build_container_restore_snapshot", lambda *args, **kwargs: {"container_name": "c"})
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp", lambda **kwargs: {"ok": False, "error": "smtp"})

    container_cleanup_task._send_cleanup_reminders_if_needed(
        container.id,
        {
            "cleanup_status": "countdown",
            "seconds_until_cleanup": 3600,
            "cleanup_at": cleanup_at.isoformat(),
        },
    )

    assert container_cleanup_reminder_repo.was_sent(container.id, "12h", cleanup_at, "owner@bjtu.edu.cn", session=db_session) is False


@pytest.mark.parametrize("failure_stage", ["flush", "commit"])
def test_mark_sent_db_failure_rolls_back_and_continues(db_session, monkeypatch, caplog, failure_stage):
    _root, _machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    recipients = ["first@example.test", "second@example.test"]
    attempts = []
    rollbacks = []
    monkeypatch.setattr(container_cleanup_task.containers_repo, "get_container_root_owner_emails",
                        lambda *args, **kwargs: recipients)
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp",
                        lambda **kwargs: attempts.append(kwargs["to"]) or {"ok": True})
    original_mark_sent = container_cleanup_reminder_repo.mark_sent
    fail_once = True

    def mark_sent(container_id, reminder_key, cleanup_at, email, *, session):
        nonlocal fail_once
        marked = original_mark_sent(container_id, reminder_key, cleanup_at, email, session=session)
        if fail_once:
            fail_once = False
            event.listen(session, "after_rollback", lambda session: rollbacks.append(True))
            # A real NOT NULL violation leaves the session requiring rollback.
            session.add(ContainerCleanupReminder(
                container_id=container_id, reminder_key=reminder_key,
                cleanup_at=cleanup_at, recipient_email=None,
            ))
            if failure_stage == "flush":
                session.flush()
        return marked

    monkeypatch.setattr(container_cleanup_reminder_repo, "mark_sent", mark_sent)
    info = {"cleanup_status": "countdown", "seconds_until_cleanup": 3600,
            "cleanup_at": cleanup_at.isoformat()}

    container_cleanup_task._send_cleanup_reminders_if_needed(container.id, info, "12")

    assert attempts == recipients
    assert rollbacks == [True]
    assert "reminder sent but recording failed" in caplog.text
    assert not container_cleanup_reminder_repo.was_sent(
        container.id, "12h", cleanup_at, recipients[0], session=db_session)
    assert container_cleanup_reminder_repo.was_sent(
        container.id, "12h", cleanup_at, recipients[1], session=db_session)

    container_cleanup_task._send_cleanup_reminders_if_needed(container.id, info, "12")

    assert attempts == recipients + [recipients[0]]
    assert container_cleanup_reminder_repo.was_sent(
        container.id, "12h", cleanup_at, recipients[0], session=db_session)
