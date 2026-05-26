from datetime import datetime, timedelta

from ...repositories import container_cleanup_reminder_repo
from ...schemas import container_cleanup_task
from ..factories import create_container_graph


def test_parse_reminder_hours_filters_invalid_and_deduplicates():
    assert container_cleanup_task._parse_reminder_hours("72,bad,24,72,0,-1,12") == [72, 24, 12]


def test_send_cleanup_reminder_skips_non_countdown(app, monkeypatch):
    calls = []
    monkeypatch.setattr(container_cleanup_task, "send_mail", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    with app.app_context():
        container_cleanup_task._send_cleanup_reminders_if_needed(1, {"cleanup_status": "due"}, app)

    assert calls == []


def test_send_cleanup_reminder_skips_without_owner_email(app, monkeypatch):
    calls = []
    monkeypatch.setattr(container_cleanup_task.container_tasks, "get_container_root_owner_emails", lambda container_id: [])
    monkeypatch.setattr(container_cleanup_task, "send_mail", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    with app.app_context():
        container_cleanup_task._send_cleanup_reminders_if_needed(
            1,
            {
                "cleanup_status": "countdown",
                "seconds_until_cleanup": 3600,
                "cleanup_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            },
            app,
        )

    assert calls == []


def test_send_cleanup_reminder_skips_when_already_sent(app, db_session, monkeypatch):
    _root, _machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    container_cleanup_reminder_repo.mark_sent(container.id, "12h", cleanup_at, "owner@bjtu.edu.cn")
    calls = []
    monkeypatch.setattr(container_cleanup_task.container_tasks, "get_container_root_owner_emails", lambda container_id: ["owner@bjtu.edu.cn"])
    monkeypatch.setattr(container_cleanup_task.container_tasks, "build_container_restore_snapshot", lambda *args, **kwargs: {"container_name": "c"})
    monkeypatch.setattr(container_cleanup_task, "send_mail", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    with app.app_context():
        container_cleanup_task._send_cleanup_reminders_if_needed(
            container.id,
            {
                "cleanup_status": "countdown",
                "seconds_until_cleanup": 3600,
                "cleanup_at": cleanup_at.isoformat(),
            },
            app,
        )

    assert calls == []


def test_send_cleanup_reminder_marks_sent_after_mail_success(app, db_session, monkeypatch):
    _root, _machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    monkeypatch.setattr(container_cleanup_task.container_tasks, "get_container_root_owner_emails", lambda container_id: ["owner@bjtu.edu.cn"])
    monkeypatch.setattr(container_cleanup_task.container_tasks, "build_container_restore_snapshot", lambda *args, **kwargs: {"container_name": "c"})
    monkeypatch.setattr(container_cleanup_task, "send_mail", lambda **kwargs: {"ok": True})

    with app.app_context():
        container_cleanup_task._send_cleanup_reminders_if_needed(
            container.id,
            {
                "cleanup_status": "countdown",
                "seconds_until_cleanup": 3600,
                "cleanup_at": cleanup_at.isoformat(),
            },
            app,
        )

    assert container_cleanup_reminder_repo.was_sent(container.id, "12h", cleanup_at, "owner@bjtu.edu.cn") is True


def test_send_cleanup_reminder_does_not_mark_sent_after_mail_failure(app, db_session, monkeypatch):
    _root, _machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    monkeypatch.setattr(container_cleanup_task.container_tasks, "get_container_root_owner_emails", lambda container_id: ["owner@bjtu.edu.cn"])
    monkeypatch.setattr(container_cleanup_task.container_tasks, "build_container_restore_snapshot", lambda *args, **kwargs: {"container_name": "c"})
    monkeypatch.setattr(container_cleanup_task, "send_mail", lambda **kwargs: {"ok": False, "error": "smtp"})

    with app.app_context():
        container_cleanup_task._send_cleanup_reminders_if_needed(
            container.id,
            {
                "cleanup_status": "countdown",
                "seconds_until_cleanup": 3600,
                "cleanup_at": cleanup_at.isoformat(),
            },
            app,
        )

    assert container_cleanup_reminder_repo.was_sent(container.id, "12h", cleanup_at, "owner@bjtu.edu.cn") is False
