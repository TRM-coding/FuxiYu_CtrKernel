import pytest

from .. import mocks
from ..factories import create_auth, create_container_graph, create_machine, create_user
from ...blueprints import container_api
from ...constant import PERMISSION
from ...models.containers import Container
from ...repositories import machine_permission_repo
from ...services import container_tasks


pytestmark = pytest.mark.e2e


def test_ctrl_e2e_user_login_machine_permission_container_create_and_list(
    client,
    db_session,
    monkeypatch,
):
    user = create_user(username="e2e_user", password="Password_123")
    machine = create_machine(machine_name="e2e_machine", max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, user.id)

    login_resp = client.post("/api/login", json={"username": "e2e_user", "password": "Password_123"})
    mocks.mock_node_response(monkeypatch, container_tasks, {"success": 1})
    mocks.mock_container_crypto(monkeypatch, container_tasks)
    monkeypatch.setattr(container_tasks, "is_machine_online_remote", lambda machine_id: True)
    heartbeat_calls = []
    monkeypatch.setattr(
        container_tasks,
        "container_starting_status_heartbeat",
        lambda *args, **kwargs: heartbeat_calls.append((args, kwargs)),
    )

    create_resp = client.post(
        "/api/containers/create_container",
        json={
            "user_name": user.username,
            "machine_id": machine.id,
            "container": {
                "GPU_LIST": [],
                "CPU_NUMBER": 2,
                "MEMORY": 8,
                "SHARED_MEM": 2,
                "NAME": "e2e_container",
                "image": "ubuntu:22.04",
            },
        }
    )

    assert create_resp.status_code == 200
    created = Container.query.filter_by(name="e2e_container", machine_id=machine.id).first()
    assert created is not None
    assert heartbeat_calls

    monkeypatch.setattr(container_tasks, "get_container_status", lambda *args, **kwargs: {"success": 1, "container_status": "creating"})
    list_resp = client.post(
        "/api/containers/list_all_container_bref_information",
        json={"user_id": user.id, "page_number": 0, "page_size": 10}
    )

    assert list_resp.status_code == 200
    payload = list_resp.get_json()
    assert [c["container_id"] for c in payload["containers_info"]] == [created.id]
    assert payload["long_term_container_limit"] == 1


def test_ctrl_e2e_set_long_term_then_list_reflects_long_term_state(client, db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    token = "e2e-long-term-token"
    create_auth(root, token=token)
    monkeypatch.setattr(container_tasks, "get_container_status", lambda *args, **kwargs: {"success": 1, "container_status": "online"})

    set_resp = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": container.id, "is_long_term": True},
        environ_base={"HTTP_COOKIE": f"auth_token={token}"}
    )

    assert set_resp.status_code == 200

    list_resp = client.post(
        "/api/containers/list_all_container_bref_information",
        json={"user_id": root.id, "page_number": 0, "page_size": 10},
        environ_base={"HTTP_COOKIE": f"auth_token={token}"}
    )

    assert list_resp.status_code == 200
    info = list_resp.get_json()["containers_info"][0]
    assert info["is_long_term"] is True
    assert list_resp.get_json()["long_term_container_remaining"] == 0


def test_ctrl_e2e_operator_can_set_long_term_but_limit_still_applies(client, db_session):
    root, machine, container = create_container_graph()
    _root2, _machine2, second = create_container_graph(root_user=root, machine=machine)
    operator = create_user(permission=PERMISSION.OPERATOR)
    token = "e2e-operator-token"
    create_auth(operator, token=token)

    first = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": container.id, "is_long_term": True},
        environ_base={"HTTP_COOKIE": f"auth_token={token}"}
    )
    second_resp = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": second.id, "is_long_term": True},
        environ_base={"HTTP_COOKIE": f"auth_token={token}"}
    )

    assert first.status_code == 200
    assert second_resp.status_code == 409
    assert second_resp.get_json()["error_reason"] == "long_term_limit_reached"
