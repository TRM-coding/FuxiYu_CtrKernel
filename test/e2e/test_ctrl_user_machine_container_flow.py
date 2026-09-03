import pytest

from .. import mocks
from ..factories import create_auth, create_container_graph, create_machine, create_user
from ...api import container_api, deps
from ...extensions import session_scope
from ...repositories import containers_repo, machine_permission_repo
from ...services import container_tasks
from ...services.container_module import node_comms


pytestmark = pytest.mark.e2e


def test_ctrl_e2e_user_login_machine_permission_container_create_and_list(
    client,
    db_session,
    monkeypatch,
):
    user = create_user(username="e2e_user", password="Password_123")
    machine = create_machine(machine_name="e2e_machine", max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, user.id, session=db_session)
    db_session.commit()

    login_resp = client.post("/api/login", json={"username": "e2e_user", "password": "Password_123"})
    assert login_resp.status_code == 200
    auth = create_auth(user, token="e2e-user-token")
    client.cookies.set("auth_token", auth.token)
    mocks.mock_node_response(monkeypatch, container_tasks, {"success": 1})
    monkeypatch.setattr(node_comms, "is_machine_online_remote", lambda machine_id: True)

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
    with session_scope(commit=False) as session:
        created = containers_repo.get_id_by_name_machine("e2e_container", machine.id, session=session)
    assert created is not None

    list_resp = client.post(
        "/api/containers/list_all_container_bref_information",
        json={"user_id": user.id, "page_number": 0, "page_size": 10}
    )

    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert [c["container_id"] for c in payload["containers_info"]] == [created]
    assert payload["long_term_container_limit"] == 1


def test_ctrl_e2e_set_long_term_then_list_reflects_long_term_state(client, db_session, monkeypatch):
    root, machine, container = create_container_graph()
    machine_permission_repo.add_permission(machine.id, root.id, session=db_session)
    db_session.commit()
    token = "e2e-long-term-token"
    create_auth(root, token=token)

    client.cookies.set("auth_token", token)

    set_resp = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": container.id, "is_long_term": True},
    )

    assert set_resp.status_code == 200

    list_resp = client.post(
        "/api/containers/list_all_container_bref_information",
        json={"user_id": root.id, "page_number": 0, "page_size": 10},
    )

    assert list_resp.status_code == 200
    info = list_resp.json()["containers_info"][0]
    assert info["is_long_term"] is True
    assert list_resp.json()["long_term_container_remaining"] == 0


def test_ctrl_e2e_operator_can_set_long_term_but_limit_still_applies(client, db_session):
    root, machine, container = create_container_graph()
    _root2, _machine2, second = create_container_graph(root_user=root, machine=machine)
    operator = create_user(operator=True)
    # 模拟建号流程组绑定:operator 加入含 bypass 的组
    from ...repositories import auth_repo
    from ...extensions import session_scope as _ss
    with _ss() as session:
        group = auth_repo.ensure_group("operator", "t", session=session)
        auth_repo.ensure_group_entity(group.id, "bypass_resource", session=session)
        auth_repo.ensure_user_group(operator.id, group.id, session=session)
    token = "e2e-operator-token"
    create_auth(operator, token=token)

    client.cookies.set("auth_token", token)

    first = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": container.id, "is_long_term": True},
    )
    second_resp = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": second.id, "is_long_term": True},
    )

    assert first.status_code == 200
    assert second_resp.status_code == 409
    assert second_resp.json()["error_reason"] == "long_term_limit_reached"
