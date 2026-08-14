from sqlalchemy.exc import IntegrityError

from ...blueprints import container_api
from ...services import container_tasks


def _auth(monkeypatch, *, valid=True, user_id=1):
    monkeypatch.setattr(container_api.authentications_repo, "is_token_valid", lambda token: valid)
    monkeypatch.setattr(container_api.authentications_repo, "get_user_id_by_token", lambda token: user_id)


def test_create_container_api_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/containers/create_container", json={})

    assert resp.status_code == 401


def test_create_container_api_rejects_invalid_payload(client, monkeypatch):
    _auth(monkeypatch)

    resp = client.post(
        "/api/containers/create_container",
        json={"container": {"CPU_NUMBER": "bad"}}
    )

    assert resp.status_code == 400
    assert resp.get_json()["error_reason"] == "invalid_payload"


def test_create_container_api_duplicate_returns_409(client, monkeypatch):
    _auth(monkeypatch)
    err = IntegrityError("duplicate", params=None, orig="duplicate")
    monkeypatch.setattr(container_api.container_service, "Create_container", lambda **kwargs: (_ for _ in ()).throw(err))

    resp = client.post(
        "/api/containers/create_container",
        json={"user_name": "u", "machine_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c", "image": "i"}}
    )

    assert resp.status_code == 409


def test_create_container_api_machine_permission_denied_returns_403(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(**kwargs):
        raise container_tasks.NodeServiceError("denied", reason="machine_permission_denied")

    monkeypatch.setattr(container_api.container_service, "Create_container", _raise)

    resp = client.post(
        "/api/containers/create_container",
        json={"user_name": "u", "machine_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c", "image": "i"}}
    )

    assert resp.status_code == 403


def test_create_container_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "Create_container", lambda **kwargs: True)

    resp = client.post(
        "/api/containers/create_container",
        json={"user_name": "u", "machine_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c", "image": "i"}}
    )

    assert resp.status_code == 200
    assert resp.get_json()["success"] == 1


def test_delete_container_api_not_found_returns_404(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(**kwargs):
        raise container_tasks.NodeServiceError("missing", reason="not_found")

    monkeypatch.setattr(container_api.container_service, "remove_container", _raise)

    resp = client.post("/api/containers/delete_container", json={"container_id": 1} )

    assert resp.status_code == 404


def test_delete_container_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "remove_container", lambda **kwargs: True)

    resp = client.post("/api/containers/delete_container", json={"container_id": 1} )

    assert resp.status_code == 200


def test_start_stop_restart_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "start_container", lambda **kwargs: True)
    monkeypatch.setattr(container_api.container_service, "stop_container", lambda **kwargs: True)
    monkeypatch.setattr(container_api.container_service, "restart_container", lambda **kwargs: True)

    for endpoint in ("start_container", "stop_container", "restart_container"):
        resp = client.post(f"/api/containers/{endpoint}", json={"container_id": 1} )
        assert resp.status_code == 200
