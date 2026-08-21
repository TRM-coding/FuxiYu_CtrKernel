from datetime import datetime, timedelta

import pytest

from ...models.container_ssh_login import ContainerSSHLogin
from ...repositories import container_cleanup_reminder_repo, long_term_container_repo
from ...schedulers import container_cleanup_task
from ..factories import create_container_graph


pytestmark = pytest.mark.e2e


def _ssh_record(db_session, machine_id, container_id, last_ssh_login_time):
    record = ContainerSSHLogin(
        machine_id=machine_id,
        container_id=container_id,
        last_ssh_login_time=last_ssh_login_time,
    )
    db_session.add(record)
    db_session.commit()
    return record


def test_ctrl_e2e_cleanup_reminder_sends_mail_for_countdown_container(db_session, monkeypatch):
    root, machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    last_ssh_time = cleanup_at - timedelta(days=7)
    _ssh_record(db_session, machine.id, container.id, last_ssh_time.isoformat())
    calls = []
    monkeypatch.setattr(container_cleanup_task, "send_mail", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert calls
    assert calls[0]["to"] == root.email
    assert container_cleanup_reminder_repo.was_sent(container.id, "12h", cleanup_at, root.email, session=db_session) is True


def test_ctrl_e2e_cleanup_reminder_skips_long_term_container(db_session, monkeypatch):
    _root, machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    last_ssh_time = cleanup_at - timedelta(days=7)
    _ssh_record(db_session, machine.id, container.id, last_ssh_time.isoformat())
    long_term_container_repo.add(container.id, session=db_session)
    db_session.commit()
    calls = []
    monkeypatch.setattr(container_cleanup_task, "send_mail", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert calls == []
