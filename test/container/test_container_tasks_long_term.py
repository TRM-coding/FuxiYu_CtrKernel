import pytest

from ...models.long_term_container import LongTermContainer
from ...repositories import long_term_container_repo
from ...services import container_tasks
from ..factories import create_container_graph, create_user


def test_set_long_term_success_for_root_owner(db_session, container_graph):
    root, _machine, container = container_graph

    result = container_tasks.set_long_term_container(container.id, True, operator_user_id=root.id)

    assert result["container_id"] == container.id
    assert result["is_long_term"] is True
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True


def test_set_long_term_success_for_operator_on_owned_container(db_session, container_graph):
    operator = create_user(operator=True)
    _root, _machine, container = container_graph

    result = container_tasks.set_long_term_container(container.id, True, operator_user_id=operator.id)

    assert result["is_long_term"] is True


def test_set_long_term_rejects_when_root_owner_limit_reached(db_session, container_graph):
    root, machine, _container = container_graph
    _root2, _machine2, second_container = create_container_graph(root_user=root, machine=machine)
    db_session.add(LongTermContainer(container_id=second_container.id, created_by_user_id=root.id))
    db_session.commit()

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.set_long_term_container(_container.id, True, operator_user_id=root.id)

    assert excinfo.value.reason == "long_term_limit_reached"


def test_unset_long_term_removes_record(db_session, container_graph):
    root, _machine, container = container_graph
    long_term_container_repo.add(container.id, created_by_user_id=root.id, session=db_session)

    db_session.commit()

    result = container_tasks.set_long_term_container(container.id, False, operator_user_id=root.id)

    assert result["is_long_term"] is False
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is False


def test_build_long_term_state_blocks_only_when_not_already_long_term(db_session, container_graph):
    root, machine, container = container_graph
    _root2, _machine2, second_container = create_container_graph(root_user=root, machine=machine)
    long_term_container_repo.add(second_container.id, created_by_user_id=root.id, session=db_session)

    db_session.commit()

    blocked_state = container_tasks.build_long_term_container_state(container.id)
    existing_state = container_tasks.build_long_term_container_state(second_container.id)

    assert blocked_state["long_term_container_can_enable"] is False
    assert blocked_state["long_term_container_blocked_user_ids"] == [root.id]
    assert existing_state["is_long_term"] is True
    assert existing_state["long_term_container_can_enable"] is True
    assert existing_state["long_term_container_blocked_user_ids"] == []
