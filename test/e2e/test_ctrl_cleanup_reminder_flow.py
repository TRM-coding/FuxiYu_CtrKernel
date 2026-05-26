from datetime import datetime, timedelta

import pytest

from ...extensions import db
from ...models.container_ssh_login import ContainerSSHLogin
from ...models.container_cleanup_reminder import ContainerCleanupReminder
from ...repositories import long_term_container_repo
from ...schemas import container_cleanup_task
from ..factories import create_container_graph


pytestmark = pytest.mark.e2e


def _ssh_record(machine_id, container_id, last_ssh_login_time):
    record = ContainerSSHLogin(
        machine_id=machine_id,
        container_id=container_id,
        last_ssh_login_time=last_ssh_login_time,
    )
    db.session.add(record)
    db.session.commit()
    return record


def test_ctrl_e2e_cleanup_reminder_sends_mail_for_countdown_container(app, db_session, monkeypatch):
    root, machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    last_ssh_time = cleanup_at - timedelta(days=7)
    _ssh_record(machine.id, container.id, last_ssh_time.isoformat())
    calls = []
    monkeypatch.setattr(container_cleanup_task, "send_mail", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    with app.app_context():
        container_cleanup_task.cleanup_expired_containers_once(7)

    assert calls
    assert calls[0]["to"] == root.email
    assert ContainerCleanupReminder.query.filter_by(container_id=container.id, recipient_email=root.email).first() is not None


def test_ctrl_e2e_cleanup_reminder_skips_long_term_container(app, db_session, monkeypatch):
    _root, machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    last_ssh_time = cleanup_at - timedelta(days=7)
    _ssh_record(machine.id, container.id, last_ssh_time.isoformat())
    long_term_container_repo.add(container.id)
    calls = []
    monkeypatch.setattr(container_cleanup_task, "send_mail", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    with app.app_context():
        container_cleanup_task.cleanup_expired_containers_once(7)

    assert calls == []
