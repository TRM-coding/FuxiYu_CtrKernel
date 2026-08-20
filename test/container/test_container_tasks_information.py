from datetime import datetime, timedelta

import pytest

from ...constant import ContainerStatus, MachineStatus, PERMISSION
from ...models.containers import Container
from ...repositories import container_ssh_login_repo, long_term_container_repo, machine_permission_repo
from ...services import container_tasks
from ..factories import create_container, create_machine, create_user
from .conftest import NODE_STATUS_404, NODE_STATUS_OFFLINE, NODE_STATUS_ONLINE


def test_get_container_detail_reads_status_from_db(db_session, container_graph):
    # getter 只查库：状态读 WSS 推送落库的 container_status 字段
    _root, machine, container = container_graph
    container.container_status = ContainerStatus.OFFLINE
    db_session.commit()

    info = container_tasks.get_container_detail_information(container.id)

    assert info["container_id"] == container.id
    assert info["container_status"] == ContainerStatus.OFFLINE.value


def test_get_container_detail_keeps_default_status_from_db(db_session, container_graph):
    # 工厂默认 ONLINE：不写 DB 状态时读默认值，不触发任何 Node 调用
    _root, _machine, container = container_graph

    info = container_tasks.get_container_detail_information(container.id)

    assert info["container_id"] == container.id
    assert info["container_status"] == ContainerStatus.ONLINE.value


def test_list_container_bref_operator_can_filter_by_user(monkeypatch, db_session):
    operator = create_user(permission=PERMISSION.OPERATOR)
    target = create_user()
    _root, machine, container = container_tasks_test_graph_for_user(target)

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

    result = container_tasks.list_all_container_bref_information(
        machine_id=None,
        request_user_id=user.id,
        page_number=0,
        page_size=10,
        user_id=user.id,
    )

    assert [c.container_id for c in result["containers"]] == [allowed_container.id]


def test_list_container_bref_includes_cleanup_info_from_ssh_record(monkeypatch, db_session, container_graph):
    from ...services.container_module import node_comms

    root, machine, container = container_graph
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
    db_session,
    container_graph,
):
    root, _machine, container = container_graph
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
