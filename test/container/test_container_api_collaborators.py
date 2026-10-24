from ...api import container_api, deps
from ...services import container_tasks


def _auth(monkeypatch, *, valid=True, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: valid)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.repositories.containers_repo.get_machine_id_by_container_id",
        lambda cid, session: 1,
    )


def test_add_collaborator_api_container_offline_returns_400(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(**kwargs):
        raise container_tasks.NodeServiceError("offline", reason="container_offline")

    monkeypatch.setattr(container_api.container_service, "start_add_collaborator", _raise)

    resp = client.post(
        "/api/containers/add_collaborator",
        json={"container_id": 1, "user_id": 2, "role": "COLLABORATOR"},
    )

    assert resp.status_code == 400


def test_add_collaborator_api_success_returns_201(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service, "start_add_collaborator",
        lambda **kwargs: {"login_name": "collab", "password": "Pwd_123"},
    )

    resp = client.post(
        "/api/containers/add_collaborator",
        json={"container_id": 1, "user_id": 2, "role": "COLLABORATOR"},
    )

    assert resp.status_code == 201


def test_remove_collaborator_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "remove_collaborator", lambda **kwargs: True)

    resp = client.post(
        "/api/containers/remove_collaborator",
        json={"container_id": 1, "user_id": 2},
    )

    assert resp.status_code == 200


def test_update_role_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "update_role", lambda **kwargs: True)

    resp = client.post(
        "/api/containers/update_role",
        json={"container_id": 1, "user_id": 2, "updated_role": "ADMIN"},
    )

    assert resp.status_code == 200


def test_add_collaborator_api_rejects_root_and_unknown_role_before_node(client, monkeypatch):
    _auth(monkeypatch)
    called = []
    monkeypatch.setattr(
        container_api.container_service, "start_add_collaborator",
        lambda **kwargs: called.append(kwargs) or {"login_name": "x", "password": "p"},
    )
    for role in ("ROOT", "SUPERADMIN", "admin"):
        resp = client.post(
            "/api/containers/add_collaborator",
            json={"container_id": 1, "user_id": 2, "role": role},
        )
        assert resp.status_code == 400, role
        assert resp.json()["error_reason"] == "invalid_payload"
    assert called == []


def test_update_role_api_rejects_unknown_role_before_node(client, monkeypatch):
    _auth(monkeypatch)
    called = []
    monkeypatch.setattr(
        container_api.container_service, "start_root_handover",
        lambda **kwargs: called.append(kwargs) or {"credentials": [{"login_name": "root", "password": "p"}]},
    )
    resp = client.post(
        "/api/containers/update_role",
        json={"container_id": 1, "user_id": 2, "updated_role": "SUPERADMIN"},
    )
    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_payload"
    assert called == []


def test_collaborator_openapi_role_enums_are_public_uppercase(client):
    schemas = client.app.openapi()["components"]["schemas"]
    assert set(schemas["CollaboratorRequest"]["properties"]["role"]["enum"]) == {
        "ADMIN", "COLLABORATOR",
    }
    assert set(schemas["UpdateRoleRequest"]["properties"]["updated_role"]["enum"]) == {
        "ADMIN", "COLLABORATOR", "ROOT",
    }
