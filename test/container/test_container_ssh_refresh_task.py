from ...schedulers import container_ssh_refresh_task
from ..factories import create_container, create_machine


def test_refresh_all_containers_last_ssh_login_time_pages_until_empty(monkeypatch, db_session):
    machine = create_machine()
    containers = [create_container(machine=machine) for _ in range(3)]
    seen = []
    monkeypatch.setattr(
        container_ssh_refresh_task.container_tasks,
        "get_container_last_ssh_login_time",
        lambda container_id: seen.append(container_id),
    )

    container_ssh_refresh_task.refresh_all_containers_last_ssh_login_time_once(page_size=2)

    assert seen == [c.id for c in containers]


def test_refresh_all_containers_last_ssh_login_time_continues_after_single_failure(monkeypatch, db_session):
    machine = create_machine()
    first = create_container(machine=machine)
    second = create_container(machine=machine)
    seen = []

    def _refresh(container_id):
        seen.append(container_id)
        if container_id == first.id:
            raise RuntimeError("node failed")

    monkeypatch.setattr(container_ssh_refresh_task.container_tasks, "get_container_last_ssh_login_time", _refresh)

    container_ssh_refresh_task.refresh_all_containers_last_ssh_login_time_once(page_size=10)

    assert seen == [first.id, second.id]


def test_ssh_refresh_scheduler_returns_existing_thread_when_alive(app):
    class _Thread:
        def is_alive(self):
            return True

    existing = _Thread()
    app.extensions["container_ssh_refresh_scheduler"] = {"thread": existing}

    assert container_ssh_refresh_task.start_container_ssh_refresh_scheduler(app, interval_seconds=999) is existing
