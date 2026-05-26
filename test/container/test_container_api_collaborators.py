from ...blueprints import container_api
from ...services import container_tasks


def _auth(monkeypatch, *, valid=True, user_id=1):
    monkeypatch.setattr(container_api.authentications_repo, "is_token_valid", lambda token: valid)
    monkeypatch.setattr(container_api.authentications_repo, "get_user_id_by_token", lambda token: user_id)


def test_add_collaborator_api_container_offline_returns_400(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(**kwargs):
        raise container_tasks.NodeServiceError("offline", reason="container_offline")

    monkeypatch.setattr(container_api.container_service, "add_collaborator", _raise)

    resp = client.post(
        "/api/containers/add_collaborator",
        json={"container_id": 1, "user_id": 2, "role": "COLLABORATOR"},
        headers={"token": "t"},
    )

    assert resp.status_code == 400


def test_add_collaborator_api_success_returns_201(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "add_collaborator", lambda **kwargs: True)

    resp = client.post(
        "/api/containers/add_collaborator",
        json={"container_id": 1, "user_id": 2, "role": "COLLABORATOR"},
        headers={"token": "t"},
    )

    assert resp.status_code == 201


def test_remove_collaborator_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "remove_collaborator", lambda **kwargs: True)

    resp = client.post(
        "/api/containers/remove_collaborator",
        json={"container_id": 1, "user_id": 2},
        headers={"token": "t"},
    )

    assert resp.status_code == 200


def test_update_role_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "update_role", lambda **kwargs: True)

    resp = client.post(
        "/api/containers/update_role",
        json={"container_id": 1, "user_id": 2, "updated_role": "ADMIN"},
        headers={"token": "t"},
    )

    assert resp.status_code == 200
