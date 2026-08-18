from datetime import datetime, timedelta

import pytest

from ...constant import ContainerStatus, MachineStatus, PERMISSION
from ...models.containers import Container
from ...repositories import container_ssh_login_repo, long_term_container_repo, machine_permission_repo
from ...services import container_tasks
from ..factories import create_container, create_machine, create_user
from .conftest import NODE_STATUS_404, NODE_STATUS_OFFLINE, NODE_STATUS_ONLINE


def test_get_container_detail_success_skips_node_when_machine_offline(
    monkeypatch,
    db_session,
    container_graph,
):
    _root, machine, container = container_graph
    machine.machine_status = MachineStatus.OFFLINE
    db_session.commit()
    monkeypatch.setattr(
        container_tasks,
        "get_container_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call node")),
    )

    info = container_tasks.get_container_detail_information(container.id)

    assert info["container_id"] == container.id
    assert info["container_status"] == ContainerStatus.ONLINE.value


def test_get_container_detail_updates_status_when_node_returns_status(
    monkeypatch,
    db_session,
    container_graph,
):
    _root, _machine, container = container_graph
    monkeypatch.setattr(container_tasks, "get_container_status", lambda *args, **kwargs: NODE_STATUS_OFFLINE)

    info = container_tasks.get_container_detail_information(container.id)

    assert info["container_id"] == container.id
    assert Container.query.get(container.id).container_status == ContainerStatus.OFFLINE


def test_get_container_detail_node_404_deletes_local_container_and_raises(
    monkeypatch,
    db_session,
    container_graph,
):
    _root, _machine, container = container_graph
    monkeypatch.setattr(container_tasks, "get_container_status", lambda *args, **kwargs: NODE_STATUS_404)

    with pytest.raises(ValueError, match="Container not found"):
        container_tasks.get_container_detail_information(container.id)

    assert Container.query.get(container.id) is None


def test_get_container_detail_ignores_node_network_error(monkeypatch, db_session, container_graph):
    _root, _machine, container = container_graph
    monkeypatch.setattr(
        container_tasks,
        "get_container_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network")),
    )

    info = container_tasks.get_container_detail_information(container.id)

    assert info["container_id"] == container.id


def test_list_container_bref_operator_can_filter_by_user(monkeypatch, db_session):
    operator = create_user(permission=PERMISSION.OPERATOR)
    target = create_user()
    _root, machine, container = container_tasks_test_graph_for_user(target)
    monkeypatch.setattr(container_tasks, "get_container_status", lambda *args, **kwargs: NODE_STATUS_ONLINE)

    result = container_tasks.list_all_container_bref_information(
        machine_id=None,
        request_user_id=operator.id,
        page_number=0,
        page_size=10,
        user_id=target.id,
    )

    assert [c.container_id for c in result["containers"]] == [container.id]


def test_list_container_bref_non_operator_filters_by_machine_permission(monkeypatch, db_session):
    user = create_user()
    allowed_machine = create_machine()
    blocked_machine = create_machine()
    machine_permission_repo.add_permission(allowed_machine.id, user.id)
    allowed_container = create_container(machine=allowed_machine)
    blocked_container = create_container(machine=blocked_machine)
    container_tasks.add_binding(user.id, allowed_container.id, role=container_tasks.ROLE.ROOT, username="root")
    container_tasks.add_binding(user.id, blocked_container.id, role=container_tasks.ROLE.ROOT, username="root")
    monkeypatch.setattr(container_tasks, "get_container_status", lambda *args, **kwargs: NODE_STATUS_ONLINE)

    result = container_tasks.list_all_container_bref_information(
        machine_id=None,
        request_user_id=user.id,
        page_number=0,
        page_size=10,
        user_id=user.id,
    )

    assert [c.container_id for c in result["containers"]] == [allowed_container.id]


def test_list_container_bref_node_404_removes_and_skips_container(monkeypatch, db_session, container_graph):
    from ...services.container_module import node_comms

    root, _machine, container = container_graph
    monkeypatch.setattr(node_comms, "get_container_status", lambda *args, **kwargs: NODE_STATUS_404)

    result = container_tasks.list_all_container_bref_information(
        machine_id=None,
        request_user_id=root.id,
        page_number=0,
        page_size=10,
        user_id=root.id,
    )

    assert result["containers"] == []
    assert Container.query.get(container.id) is None


def test_list_container_bref_includes_cleanup_info_from_ssh_record(monkeypatch, db_session, container_graph):
    from ...services.container_module import node_comms

    root, machine, container = container_graph
    monkeypatch.setattr(node_comms, "get_container_status", lambda *args, **kwargs: NODE_STATUS_ONLINE)
    last_time = (datetime.utcnow() - timedelta(days=1)).isoformat()
    container_ssh_login_repo.upsert_last_ssh_login_time(machine.id, container.id, last_time)

    result = container_tasks.list_all_container_bref_information(
        machine_id=None,
        request_user_id=root.id,
        page_number=0,
        page_size=10,
        user_id=root.id,
    )

    info = result["containers"][0]
    assert info.last_ssh_login_time == last_time
    assert info.cleanup_status == "countdown"
    assert info.seconds_until_cleanup > 0


def test_list_container_bref_includes_long_term_remaining_when_user_filter_present(
    monkeypatch,
    db_session,
    container_graph,
):
    root, _machine, container = container_graph
    monkeypatch.setattr(container_tasks, "get_container_status", lambda *args, **kwargs: NODE_STATUS_ONLINE)
    long_term_container_repo.add(container.id, created_by_user_id=root.id)

    result = container_tasks.list_all_container_bref_information(
        machine_id=None,
        request_user_id=root.id,
        page_number=0,
        page_size=10,
        user_id=root.id,
    )

    assert result["long_term_container_limit"] == 1
    assert result["long_term_container_remaining"] == 0


def container_tasks_test_graph_for_user(user):
    machine = create_machine()
    container = create_container(machine=machine)
    machine_permission_repo.add_permission(machine.id, user.id)
    container_tasks.add_binding(user.id, container.id, role=container_tasks.ROLE.ROOT, username="root")
    return user, machine, container
