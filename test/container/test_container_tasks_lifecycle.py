import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ...constant import ContainerStatus, MachineStatus, PERMISSION, ROLE
from ...models.containers import Container
from ...repositories import machine_permission_repo
from ...services import container_tasks
from ..factories import create_container, create_machine, create_user
from .conftest import NODE_REMOVE_FAILED, NODE_REMOVE_NOT_FOUND, NODE_REMOVE_SUCCESS, NODE_SUCCESS_TRUE, VALID_PUBLIC_KEY


def test_create_container_success_sends_node_then_creates_db_record_and_root_binding(
    db_session,
    container_info,
    mock_node_send,

):
    owner = create_user(username="owner_lifecycle")
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    calls = mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.Create_container(
        owner_name=owner.username,
        machine_id=machine.id,
        container=container_info,
        public_key=VALID_PUBLIC_KEY,
        operator_user_id=owner.id,
    ) is True

    created = db_session.scalars(
        select(Container).where(Container.name == container_info.NAME, Container.machine_id == machine.id)
    ).first()
    assert created is not None
    assert created.container_status == ContainerStatus.CREATING
    bindings = container_tasks.get_container_bindings(created.id)
    assert bindings[0]["user_id"] == owner.id
    assert bindings[0]["username"] == "root"
    assert getattr(bindings[0]["role"], "value", bindings[0]["role"]) == ROLE.ROOT.value
    assert calls[0]["url"].endswith("/create_container")
    assert calls[0]["payload"]["owner_name"] == owner.username


def test_create_container_denies_inaccessible_machine(db_session, container_info):
    user = create_user()
    machine = create_machine()

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.Create_container(user.username, machine.id, container_info, operator_user_id=user.id)

    assert excinfo.value.reason == "machine_permission_denied"


def test_create_container_rejects_machine_not_found(db_session, container_info):
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.Create_container("missing", 999999, container_info)

    assert excinfo.value.reason == "machine_not_found"


def test_create_container_rejects_machine_maintenance(db_session, container_info):
    owner = create_user()
    machine = create_machine(is_maintenance=True)

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.Create_container(owner.username, machine.id, container_info)

    assert excinfo.value.reason == "machine_maintenance"


def test_create_container_rejects_machine_offline(monkeypatch, db_session, container_info):
    from ...services.container_module import node_comms

    owner = create_user()
    machine = create_machine()
    monkeypatch.setattr(node_comms, "is_machine_online_remote", lambda machine_id: False)

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.Create_container(owner.username, machine.id, container_info)

    assert excinfo.value.reason == "machine_offline"


def test_create_container_rejects_invalid_resource_payload(db_session, container_info):
    owner = create_user()
    machine = create_machine(max_memory_gb=4)
    container_info.MEMORY = 8

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.Create_container(owner.username, machine.id, container_info)

    assert excinfo.value.reason == "invalid_config"


def test_create_container_rejects_duplicate_name_before_node_write(
    db_session,
    container_info,
    mock_node_send,

):
    owner = create_user()
    machine = create_machine()
    create_container(machine=machine, name=container_info.NAME)
    calls = mock_node_send(NODE_SUCCESS_TRUE)

    with pytest.raises(IntegrityError):
        container_tasks.Create_container(owner.username, machine.id, container_info)

    assert calls == []


def test_create_container_node_failure_does_not_create_local_record(
    db_session,
    container_info,
    mock_node_send,

):
    owner = create_user()
    machine = create_machine()
    mock_node_send({"success": 0, "error_reason": "docker_init_failed"})

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.Create_container(owner.username, machine.id, container_info)

    assert excinfo.value.reason == "docker_init_failed"
    assert db_session.scalars(select(Container).where(Container.name == container_info.NAME)).first() is None


def test_create_container_success_after_node_ack(
    db_session,
    container_info,
    mock_node_send,
):
    # 心跳三件套已退役（WSS 推送接管状态推进）：创建成功即返回 True
    owner = create_user()
    machine = create_machine()
    mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.Create_container(owner.username, machine.id, container_info) is True

    assert db_session.scalars(select(Container).where(Container.name == container_info.NAME)).first() is not None


@pytest.mark.parametrize("node_response", [NODE_REMOVE_SUCCESS, NODE_REMOVE_NOT_FOUND])
def test_remove_container_success_deletes_bindings_and_container(
    db_session,
    container_graph,
    mock_node_send,

    node_response,
):
    root, _machine, container = container_graph
    container_id = container.id
    mock_node_send(node_response)

    assert container_tasks.remove_container(container_id, operator_user_id=root.id) is True

    db_session.expire_all()
    assert db_session.get(Container, container_id) is None
    assert container_tasks.get_container_bindings(container_id) == []


def test_remove_container_node_failed_raises_and_keeps_local_record(
    db_session,
    container_graph,
    mock_node_send,

):
    root, _machine, container = container_graph
    mock_node_send(NODE_REMOVE_FAILED)

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.remove_container(container.id, operator_user_id=root.id)

    assert excinfo.value.reason == "remove_failed"
    assert db_session.get(Container, container.id) is not None


def test_start_container_success(
    db_session,
    container_graph,
    mock_node_send,
):
    # 心跳三件套已退役：状态推进由 WSS 推送接管，动作成功即返回
    root, _machine, container = container_graph
    mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.start_container(container.id, operator_user_id=root.id) is True


def test_stop_container_success(
    db_session,
    container_graph,
    mock_node_send,
):
    root, _machine, container = container_graph
    mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.stop_container(container.id, operator_user_id=root.id) is True


def test_restart_container_success(
    db_session,
    container_graph,
    mock_node_send,
):
    root, _machine, container = container_graph
    mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.restart_container(container.id, operator_user_id=root.id) is True


@pytest.mark.parametrize("operation", ["start_container", "stop_container", "restart_container"])
def test_start_stop_restart_denies_inaccessible_machine(db_session, container_graph, operation):
    other = create_user(permission=PERMISSION.USER)
    _root, _machine, container = container_graph

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        getattr(container_tasks, operation)(container.id, operator_user_id=other.id)

    assert excinfo.value.reason == "machine_permission_denied"
