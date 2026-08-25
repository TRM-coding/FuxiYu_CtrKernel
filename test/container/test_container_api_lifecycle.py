from sqlalchemy.exc import IntegrityError
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


def test_create_container_api_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/containers/create_container", json={})

    assert resp.status_code == 401


def test_create_container_api_rejects_invalid_payload(client, monkeypatch):
    _auth(monkeypatch)

    resp = client.post(
        "/api/containers/create_container",
        json={"machine_id": 1, "container": {"CPU_NUMBER": "bad"}}
    )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_payload"


def test_create_container_api_duplicate_returns_409(client, monkeypatch):
    _auth(monkeypatch)
    err = IntegrityError("duplicate", params=None, orig="duplicate")
    monkeypatch.setattr(container_api.container_service, "Create_container", lambda **kwargs: (_ for _ in ()).throw(err))

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c", "image": "i"}}
    )

    assert resp.status_code == 409


def test_create_container_api_machine_permission_denied_returns_403(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(**kwargs):
        raise container_tasks.NodeServiceError("denied", reason="machine_permission_denied")

    monkeypatch.setattr(container_api.container_service, "Create_container", _raise)

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c", "image": "i"}}
    )

    assert resp.status_code == 403


def test_create_container_api_rejects_owner_without_machine_access(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_resource",
        lambda uid, rtype, rid: uid == 1,
    )

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c", "image": "i"}}
    )

    assert resp.status_code == 403
    assert resp.json()["error_reason"] == "resource_access_denied"


def test_create_container_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "Create_container", lambda **kwargs: True)

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c", "image": "i"}}
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1


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
