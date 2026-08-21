import pytest

from . import mocks
from .conftest import TEST_AUTH_TOKEN
from .factories import create_container_graph, create_machine, create_user
from ..constant import MachineStatus, PERMISSION, ROLE
from ..repositories import authentications_repo
from ..services import container_tasks


def test_user_factory_creates_unique_users(db_session):
    first = create_user()
    second = create_user()

    assert first.username != second.username
    assert first.email != second.email


def test_user_factory_can_create_operator(db_session):
    operator = create_user(permission=PERMISSION.OPERATOR)

    assert operator.permission == PERMISSION.OPERATOR


def test_machine_factory_creates_online_machine_by_default(db_session):
    machine = create_machine()

    assert machine.machine_status == MachineStatus.ONLINE


def test_container_factory_creates_root_binding_by_default(db_session):
    root, _machine, container = create_container_graph()

    bindings = container_tasks.get_container_bindings(container.id)

    assert bindings[0]["user_id"] == root.id
    assert getattr(bindings[0]["role"], "value", bindings[0]["role"]) == ROLE.ROOT.value


def test_auth_token_factory_creates_valid_token(db_session):
    user = create_user()

    token = mocks.auth_token_factory(user, token=TEST_AUTH_TOKEN)

    assert authentications_repo.is_token_valid(token, session=db_session) is True


def test_auth_token_factory_can_create_expired_token(db_session):
    user = create_user()

    token = mocks.auth_token_factory(user, expired=True, token="expired-platform-token")

    assert authentications_repo.is_token_valid(token, session=db_session) is False


def test_mock_node_response_records_calls(monkeypatch):
    calls = mocks.mock_node_response(monkeypatch, container_tasks, {"success": 1})

    result = container_tasks.send("http://node", {"config": {}})

    assert result == {"success": 1}
    assert calls[0]["args"] == ("http://node", {"config": {}})


def test_mock_mail_success_records_recipient_subject_content(monkeypatch):
    from ..schedulers import container_cleanup_task

    calls = mocks.mock_mail_success(monkeypatch, container_cleanup_task)

    result = container_cleanup_task.send_mail(to="u@bjtu.edu.cn", subject="s", content="c")

    assert result["ok"] is True
    assert calls[0]["kwargs"]["to"] == "u@bjtu.edu.cn"
    assert calls[0]["kwargs"]["subject"] == "s"


def test_assertion_helpers_validate_api_payloads(client):
    from .assertions import assert_json_error

    response = client.post("/api/containers/create_container")

    assert_json_error(response, 401, "invalid_token")
