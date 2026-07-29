from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from ...blueprints import machine_api


def _auth(monkeypatch, *, valid=True, operator=True):
    monkeypatch.setattr(machine_api.authentications_repo, "is_token_valid", lambda token: valid)
    monkeypatch.setattr(machine_api.user_repo, "check_permission", lambda token, required_permission: operator)


def test_add_machine_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/machines/add_machine", json={})

    assert resp.status_code == 401


def test_add_machine_requires_operator(client, monkeypatch):
    _auth(monkeypatch, operator=False)

    resp = client.post("/api/machines/add_machine", json={}, headers={"token": "t"})

    assert resp.status_code == 403


def test_add_machine_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(machine_api.machine_service, "Add_machine", lambda **kwargs: True)

    resp = client.post("/api/machines/add_machine", json={"machine_name": "m"}, headers={"token": "t"})

    assert resp.status_code == 201


def test_add_machine_duplicate_entry_returns_409(client, monkeypatch):
    _auth(monkeypatch)
    err = IntegrityError("duplicate", params=None, orig="duplicate")
    monkeypatch.setattr(machine_api.machine_service, "Add_machine", lambda **kwargs: (_ for _ in ()).throw(err))

    resp = client.post("/api/machines/add_machine", json={"machine_name": "m"}, headers={"token": "t"})

    assert resp.status_code == 409
    assert resp.get_json()["error_reason"] == "duplicate_entry"


def test_add_machine_validation_error_returns_422(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(**kwargs):
        exc = ValueError("bad")
        exc.error_reason = "create_failed"
        raise exc

    monkeypatch.setattr(machine_api.machine_service, "Add_machine", _raise)

    resp = client.post("/api/machines/add_machine", json={"machine_name": "m"}, headers={"token": "t"})

    assert resp.status_code == 422


def test_remove_machine_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/machines/remove_machine", json={"machine_ids": [1]})

    assert resp.status_code == 401


def test_remove_machine_requires_operator(client, monkeypatch):
    _auth(monkeypatch, operator=False)

    resp = client.post("/api/machines/remove_machine", json={"machine_ids": [1]}, headers={"token": "t"})

    assert resp.status_code == 403


def test_remove_machine_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(machine_api.machine_service, "Remove_machine", lambda machine_id: True)

    resp = client.post("/api/machines/remove_machine", json={"machine_ids": [1]}, headers={"token": "t"})

    assert resp.status_code == 200


def test_update_machine_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {}})

    assert resp.status_code == 401


def test_update_machine_requires_operator(client, monkeypatch):
    _auth(monkeypatch, operator=False)

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {}}, headers={"token": "t"})

    assert resp.status_code == 403


def test_update_machine_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(machine_api.machine_service, "Update_machine", lambda machine_id, **fields: True)

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {"machine_name": "new"}}, headers={"token": "t"})

    assert resp.status_code == 200


def test_update_machine_validation_error_returns_422(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(machine_id, **fields):
        exc = ValueError("bad")
        exc.error_reason = "update_failed"
        raise exc

    monkeypatch.setattr(machine_api.machine_service, "Update_machine", _raise)

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {"max_shared_gb": 99}}, headers={"token": "t"})

    assert resp.status_code == 422


def test_get_machine_detail_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/machines/get_detail_information", json={"machine_id": 1})

    assert resp.status_code == 401


def test_get_machine_detail_not_found(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(machine_api.machine_service, "Get_detail_information", lambda machine_id: None)

    resp = client.post("/api/machines/get_detail_information", json={"machine_id": 1}, headers={"token": "t"})

    assert resp.status_code == 404


def test_get_machine_detail_success(client, monkeypatch):
    _auth(monkeypatch)
    info = SimpleNamespace(
        machine_name="m",
        machine_ip="127.0.0.1",
        machine_type="GPU",
        machine_description="d",
        cpu_core_number=4,
        gpu_number=1,
        gpu_type="A100",
        memory_size_gb=32,
        max_shared_gb=4,
        max_memory_gb=32,
        max_gpu_number=1,
        max_cpu_core_number=4,
        disk_size_gb=100,
        containers=[],
    )
    monkeypatch.setattr(machine_api.machine_service, "Get_detail_information", lambda machine_id: info)

    resp = client.post("/api/machines/get_detail_information", json={"machine_id": 1}, headers={"token": "t"})

    assert resp.status_code == 200
    assert resp.get_json()["machine_name"] == "m"
