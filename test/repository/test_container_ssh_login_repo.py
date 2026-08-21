from ...repositories import container_ssh_login_repo
from ..factories import create_container_graph


def test_container_ssh_login_repo_upsert_insert_and_update(db_session):
    _root, machine, container = create_container_graph()

    first = container_ssh_login_repo.upsert_last_ssh_login_time(machine.id, container.id, "2026-05-25T10:00:00", session=db_session)
    first_updated_at = first.updated_at
    second = container_ssh_login_repo.upsert_last_ssh_login_time(machine.id, container.id, "2026-05-25T12:00:00", session=db_session)

    assert second.last_ssh_login_time == "2026-05-25T12:00:00"
    assert second.updated_at >= first_updated_at
    assert container_ssh_login_repo.get_by_machine_container(machine.id, container.id, session=db_session).last_ssh_login_time == "2026-05-25T12:00:00"


def test_container_ssh_login_repo_get_missing_returns_none(db_session):
    assert container_ssh_login_repo.get_by_container(999999, session=db_session) is None
