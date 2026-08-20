from ...api import machine_api, deps


def _auth(monkeypatch, *, valid=True, operator=True):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token: valid)
    monkeypatch.setattr(deps.user_repo, "check_permission", lambda token, required_permission: operator)


def test_add_machine_permission_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/machines/add_machine_permission", json={"machine_id": 1, "user_id": 2})

    assert resp.status_code == 401


def test_add_machine_permission_requires_operator(client, monkeypatch):
    _auth(monkeypatch, operator=False)

    resp = client.post("/api/machines/add_machine_permission", json={"machine_id": 1, "user_id": 2} )

    assert resp.status_code == 403


def test_add_machine_permission_missing_fields(client, monkeypatch):
    _auth(monkeypatch)

    resp = client.post("/api/machines/add_machine_permission", json={"machine_id": 1} )

    assert resp.status_code == 400
    assert resp.get_json()["error_reason"] == "missing_fields"


def test_add_machine_permission_machine_not_found(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(machine_api.machine_service, "Add_machine_permission", lambda machine_id, user_id, operator_user_id=None: (_ for _ in ()).throw(ValueError("machine_not_found")))

    resp = client.post("/api/machines/add_machine_permission", json={"machine_id": 1, "user_id": 2} )

    assert resp.status_code == 404
    assert resp.get_json()["error_reason"] == "machine_not_found"


def test_add_machine_permission_user_not_found(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(machine_api.machine_service, "Add_machine_permission", lambda machine_id, user_id, operator_user_id=None: (_ for _ in ()).throw(ValueError("user_not_found")))

    resp = client.post("/api/machines/add_machine_permission", json={"machine_id": 1, "user_id": 2} )

    assert resp.status_code == 404
    assert resp.get_json()["error_reason"] == "user_not_found"


def test_add_machine_permission_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(machine_api.machine_service, "Add_machine_permission", lambda machine_id, user_id, operator_user_id=None: True)

    resp = client.post("/api/machines/add_machine_permission", json={"machine_id": 1, "user_id": 2} )

    assert resp.status_code == 200


def test_list_machine_permissions_requires_token(client, monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token: False)

    resp = client.get("/api/machines/list_machine_permissions?machine_id=1")

    assert resp.status_code == 401


def test_list_machine_permissions_missing_machine_id(client, monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token: True)

    resp = client.get("/api/machines/list_machine_permissions" )

    assert resp.status_code == 400


def test_list_machine_permissions_success(client, monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token: True)
    monkeypatch.setattr(machine_api.machine_service, "List_machine_permissions", lambda machine_id: [2, 3])

    resp = client.get("/api/machines/list_machine_permissions?machine_id=1" )

    assert resp.status_code == 200
    assert resp.get_json()["user_ids"] == [2, 3]
