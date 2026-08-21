from datetime import datetime, timedelta

from ...models.container_ssh_login import ContainerSSHLogin
from ...repositories import long_term_container_repo
from ...schedulers import container_cleanup_task
from ..factories import create_container_graph


def _ssh_record(db_session, machine_id, container_id, last_ssh_login_time):
    record = ContainerSSHLogin(
        machine_id=machine_id,
        container_id=container_id,
        last_ssh_login_time=last_ssh_login_time,
    )
    db_session.add(record)
    db_session.commit()
    return record


def test_cleanup_expired_containers_skips_long_term(app, db_session, monkeypatch):
    _root, machine, container = create_container_graph()
    _ssh_record(db_session, machine.id, container.id, (datetime.utcnow() - timedelta(days=8)).isoformat())
    long_term_container_repo.add(container.id, session=db_session)
    db_session.commit()
    removed = []
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container", lambda container_id: removed.append(container_id) or True)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert removed == []


def test_cleanup_expired_containers_sends_reminder_for_countdown(app, db_session, monkeypatch):
    _root, machine, container = create_container_graph()
    _ssh_record(db_session, machine.id, container.id, (datetime.utcnow() - timedelta(days=6, hours=13)).isoformat())
    reminded = []
    monkeypatch.setattr(container_cleanup_task, "_send_cleanup_reminders_if_needed", lambda cid, info, app_obj: reminded.append((cid, info["cleanup_status"])))
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container", lambda container_id: True)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert reminded == [(container.id, "countdown")]


def test_cleanup_expired_containers_removes_due_container_after_snapshot(app, db_session, monkeypatch):
    _root, machine, container = create_container_graph()
    _ssh_record(db_session, machine.id, container.id, (datetime.utcnow() - timedelta(days=8)).isoformat())
    snapshots = []
    removed = []
    monkeypatch.setattr(container_cleanup_task.container_tasks, "build_container_restore_snapshot", lambda cid, cleanup_context=None: snapshots.append(cid) or {"container_id": cid})
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container", lambda container_id: removed.append(container_id) or True)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert snapshots == [container.id]
    assert removed == [container.id]


def test_cleanup_expired_containers_continues_after_remove_failure(app, db_session, monkeypatch):
    _root1, machine1, first = create_container_graph()
    _root2, machine2, second = create_container_graph()
    old = (datetime.utcnow() - timedelta(days=8)).isoformat()
    _ssh_record(db_session, machine1.id, first.id, old)
    _ssh_record(db_session, machine2.id, second.id, old)
    removed = []

    def _remove(container_id):
        removed.append(container_id)
        if container_id == first.id:
            raise RuntimeError("remove failed")
        return True

    monkeypatch.setattr(container_cleanup_task.container_tasks, "build_container_restore_snapshot", lambda cid, cleanup_context=None: {"container_id": cid})
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container", _remove)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert removed == [first.id, second.id]


def test_cleanup_scheduler_returns_existing_thread_when_alive():
    class _Thread:
        def is_alive(self):
            return True

    existing = _Thread()
    container_cleanup_task._SCHEDULER_STATE["container_cleanup_scheduler"] = {"thread": existing}

    assert container_cleanup_task.start_container_cleanup_scheduler(interval_seconds=999) is existing
