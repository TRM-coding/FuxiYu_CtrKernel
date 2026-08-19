import pytest

from ...constant import ContainerStatus, PERMISSION, ROLE
from ...repositories import usercontainer_repo
from ...services import container_tasks
from ..factories import create_user
from .conftest import NODE_SUCCESS_TRUE


def test_add_collaborator_success_adds_binding_after_node_success(
    db_session,
    container_graph,
    mock_node_send,

):
    root, _machine, container = container_graph
    collaborator = create_user(username="collab_user")
    mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.add_collaborator(
        container_id=container.id,
        user_id=collaborator.id,
        role=ROLE.COLLABORATOR,
        operator_user_id=root.id,
    ) is True

    binding = usercontainer_repo.get_binding(collaborator.id, container.id)
    assert binding["username"] == collaborator.username
    assert getattr(binding["role"], "value", binding["role"]) == ROLE.COLLABORATOR.value


def test_add_collaborator_rejects_root_role_without_node_call(
    db_session,
    container_graph,
    mock_node_send,
):
    root, _machine, container = container_graph
    collaborator = create_user(username="root_rejected_user")
    calls = mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.add_collaborator(
        container_id=container.id,
        user_id=collaborator.id,
        role=ROLE.ROOT,
        operator_user_id=root.id,
    ) is False
    assert calls == []
    assert usercontainer_repo.get_binding(collaborator.id, container.id) is None


def test_add_collaborator_rejects_offline_container(db_session, container_graph):
    root, _machine, container = container_graph
    collaborator = create_user()
    container.container_status = ContainerStatus.OFFLINE
    db_session.commit()

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.add_collaborator(
            container_id=container.id,
            user_id=collaborator.id,
            role=ROLE.COLLABORATOR,
            operator_user_id=root.id,
        )

    assert excinfo.value.reason == "container_offline"


def test_add_collaborator_denies_inaccessible_machine(db_session, container_graph):
    _root, _machine, container = container_graph
    other = create_user(permission=PERMISSION.USER)
    collaborator = create_user()

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.add_collaborator(
            container_id=container.id,
            user_id=collaborator.id,
            role=ROLE.COLLABORATOR,
            operator_user_id=other.id,
        )

    assert excinfo.value.reason == "machine_permission_denied"


def test_remove_collaborator_success_removes_binding_after_node_success(
    db_session,
    container_graph_with_collaborator,
    mock_node_send,

):
    root, collaborator, _machine, container = container_graph_with_collaborator
    mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.remove_collaborator(
        container_id=container.id,
        user_id=collaborator.id,
        operator_user_id=root.id,
    ) is True

    assert usercontainer_repo.get_binding(collaborator.id, container.id) is None


def test_remove_collaborator_rejects_root_owner(db_session, container_graph, mock_node_send):
    root, _machine, container = container_graph
    calls = mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.remove_collaborator(
        container_id=container.id,
        user_id=root.id,
        operator_user_id=root.id,
    ) is False
    assert calls == []
    assert usercontainer_repo.get_binding(root.id, container.id) is not None


def test_update_role_success_updates_binding(
    db_session,
    container_graph_with_collaborator,
    mock_node_send,

):
    root, collaborator, _machine, container = container_graph_with_collaborator
    mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.update_role(
        container_id=container.id,
        user_id=collaborator.id,
        updated_role=ROLE.ADMIN,
        operator_user_id=root.id,
    ) is True

    binding = usercontainer_repo.get_binding(collaborator.id, container.id)
    assert getattr(binding["role"], "value", binding["role"]) == ROLE.ADMIN.value
    assert binding["username"] == collaborator.username


def test_update_role_to_root_sets_container_username_root(
    db_session,
    container_graph_with_collaborator,
    mock_node_send,

):
    root, collaborator, _machine, container = container_graph_with_collaborator
    mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.update_role(
        container_id=container.id,
        user_id=collaborator.id,
        updated_role=ROLE.ROOT,
        operator_user_id=root.id,
    ) is True

    binding = usercontainer_repo.get_binding(collaborator.id, container.id)
    assert getattr(binding["role"], "value", binding["role"]) == ROLE.ROOT.value
    assert binding["username"] == "root"
