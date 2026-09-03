import pytest

from ...constant import ContainerStatus, ROLE
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

    binding = usercontainer_repo.get_binding(collaborator.id, container.id, session=db_session)
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
    assert usercontainer_repo.get_binding(collaborator.id, container.id, session=db_session) is None


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

    assert usercontainer_repo.get_binding(collaborator.id, container.id, session=db_session) is None


def test_remove_collaborator_rejects_root_owner(db_session, container_graph, mock_node_send):
    root, _machine, container = container_graph
    calls = mock_node_send(NODE_SUCCESS_TRUE)

    assert container_tasks.remove_collaborator(
        container_id=container.id,
        user_id=root.id,
        operator_user_id=root.id,
    ) is False
    assert calls == []
    assert usercontainer_repo.get_binding(root.id, container.id, session=db_session) is not None


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

    binding = usercontainer_repo.get_binding(collaborator.id, container.id, session=db_session)
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

    binding = usercontainer_repo.get_binding(collaborator.id, container.id, session=db_session)
    assert getattr(binding["role"], "value", binding["role"]) == ROLE.ROOT.value
    assert binding["username"] == "root"


def test_remove_collaborator_keeps_binding_when_node_returns_failure(
    db_session,
    container_graph_with_collaborator,
    mock_node_send,
):
    """Node 侧移除失败（容器内 userdel 失败）→ 任务抛 NodeServiceError，
    不得删除 DB 绑定 —— 否则容器内账号还在、Ctrl 却已放行，产生权限漂移。"""
    root, collaborator, _machine, container = container_graph_with_collaborator
    mock_node_send(
        {"success": 0, "error": "failed to remove collaborator inside container", "error_reason": "remove_failed"}
    )

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.remove_collaborator(
            container_id=container.id,
            user_id=collaborator.id,
            operator_user_id=root.id,
        )

    assert excinfo.value.reason == "remove_failed"
    assert usercontainer_repo.get_binding(collaborator.id, container.id, session=db_session) is not None
