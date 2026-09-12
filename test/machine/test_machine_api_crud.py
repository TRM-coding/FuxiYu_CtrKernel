from types import SimpleNamespace

from ...services.container_module.exceptions import NodeServiceError

from ...api import machine_api, deps


def _auth(monkeypatch, *, valid=True, operator=True):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: valid)
    from ...services import rbac_service
    monkeypatch.setattr(rbac_service, "_has_entity_direct", lambda uid, entity: operator)


def test_manual_machine_creation_route_is_removed(client):
    response = client.post("/api/machines/add_machine", json={})
    assert response.status_code == 404


def test_register_machine_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)
    response = client.post("/api/machines/register_machine", json={"machine_name": "node", "machine_ip": "10.0.0.1"})
    assert response.status_code == 401


def test_register_machine_requires_operator(client, monkeypatch):
    _auth(monkeypatch, operator=False)
    response = client.post("/api/machines/register_machine", json={"machine_name": "node", "machine_ip": "10.0.0.1"})
    assert response.status_code == 403


def test_register_machine_requires_registration_permission(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_entity",
        lambda user_id, code: code == "machine:manage",
    )
    response = client.post("/api/machines/register_machine", json={"machine_name": "node", "machine_ip": "10.0.0.1"})
    assert response.status_code == 403


def test_register_machine_success_calls_machine_task(client, monkeypatch):
    _auth(monkeypatch)
    calls = []

    def register(name, ip, description):
        calls.append((name, ip, description))
        return {"machine_id": 1, "uid": "node-uid", "certificate_fingerprint": "fingerprint", "hardware": {}}

    monkeypatch.setattr(machine_api.machine_service, "Register_machine", register)
    response = client.post(
        "/api/machines/register_machine",
        json={"machine_name": "node", "machine_ip": "10.0.0.1", "machine_description": "GPU host"},
    )
    assert response.status_code == 200
    assert response.json()["machine_id"] == 1
    assert response.json()["uid"] == "node-uid"
    assert calls == [("node", "10.0.0.1", "GPU host")]


def test_register_machine_error_reason_returns_422(client, monkeypatch):
    _auth(monkeypatch)

    def fail(*args):
        raise NodeServiceError("unreachable", reason="machine_unreachable")

    monkeypatch.setattr(machine_api.machine_service, "Register_machine", fail)
    response = client.post("/api/machines/register_machine", json={"machine_name": "node", "machine_ip": "10.0.0.1"})
    assert response.status_code == 422
    assert response.json()["error_reason"] == "machine_unreachable"


def test_remove_machine_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/machines/remove_machine", json={"machine_ids": [1]})

    assert resp.status_code == 401


def test_remove_machine_requires_operator(client, monkeypatch):
    _auth(monkeypatch, operator=False)

    resp = client.post("/api/machines/remove_machine", json={"machine_ids": [1]} )

    assert resp.status_code == 403


def test_remove_machine_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(machine_api.machine_service, "Remove_machine", lambda machine_id, operator_user_id=None: {"removed": list(machine_id), "blocked": []})

    resp = client.post("/api/machines/remove_machine", json={"machine_ids": [1]} )

    assert resp.status_code == 200


def test_update_machine_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {}})

    assert resp.status_code == 401


def test_update_machine_requires_operator(client, monkeypatch):
    _auth(monkeypatch, operator=False)

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {}} )

    assert resp.status_code == 403


def test_update_machine_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(machine_api.machine_service, "Update_machine", lambda machine_id, **fields: True)

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {"machine_name": "new"}} )

    assert resp.status_code == 200


def test_update_machine_validation_error_returns_422(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(machine_id, **fields):
        exc = ValueError("bad")
        exc.error_reason = "update_failed"
        raise exc

    monkeypatch.setattr(machine_api.machine_service, "Update_machine", _raise)

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {"max_shared_gb": 99}} )

    assert resp.status_code == 422


def test_set_maintenance_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/machines/set_maintenance", json={"machine_id": 1, "is_maintenance": True})

    assert resp.status_code == 401


def test_set_maintenance_requires_operator(client, monkeypatch):
    _auth(monkeypatch, operator=False)

    resp = client.post("/api/machines/set_maintenance", json={"machine_id": 1, "is_maintenance": True})

    assert resp.status_code == 403


def test_set_maintenance_success(client, monkeypatch):
    _auth(monkeypatch)
    called = {}

    def _set(machine_id, is_maintenance, operator_user_id=None):
        called["machine_id"] = machine_id
        called["is_maintenance"] = is_maintenance
        return True

    monkeypatch.setattr(machine_api.machine_service, "Set_maintenance", _set)

    resp = client.post("/api/machines/set_maintenance", json={"machine_id": 1, "is_maintenance": True})

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert called == {"machine_id": 1, "is_maintenance": True}


def test_set_maintenance_missing_machine_returns_404(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(machine_api.machine_service, "Set_maintenance", lambda **kwargs: False)

    resp = client.post("/api/machines/set_maintenance", json={"machine_id": 1, "is_maintenance": True})

    assert resp.status_code == 404
    assert resp.json()["error_reason"] == "machine_not_found"


def test_get_machine_detail_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/machines/get_detail_information", json={"machine_id": 1})

    assert resp.status_code == 401


def test_get_machine_detail_not_found(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(machine_api.machine_service, "Get_detail_information", lambda machine_id: None)

    resp = client.post("/api/machines/get_detail_information", json={"machine_id": 1} )

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

    resp = client.post("/api/machines/get_detail_information", json={"machine_id": 1} )

    assert resp.status_code == 200
    assert resp.json()["machine_name"] == "m"


#####################
# 重新钉信任锚


def test_renew_machine_trust_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/machines/renew_machine_trust", json={"machine_id": 1})

    assert resp.status_code == 401


def test_renew_machine_trust_requires_operator(client, monkeypatch):
    _auth(monkeypatch, operator=False)

    resp = client.post("/api/machines/renew_machine_trust", json={"machine_id": 1})

    assert resp.status_code == 403


def test_renew_machine_trust_success_passes_operator_and_returns_result(client, monkeypatch):
    _auth(monkeypatch)
    called = {}

    def _renew(machine_id, operator_user_id=None):
        called["machine_id"] = machine_id
        return {
            "success": True,
            "machine_id": machine_id,
            "machine_name": "m",
            "machine_ip": "10.0.0.9",
            "certificate_fingerprint": "fp-new",
            "previous_certificate_fingerprint": "fp-old",
            "uid": "u1",
            "uid_reissued": True,
            "uid_adopted": False,
            "uid_mismatch": False,
        }

    monkeypatch.setattr(machine_api.machine_service, "Renew_machine_trust", _renew)

    resp = client.post("/api/machines/renew_machine_trust", json={"machine_id": 7})

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] == 1
    assert body["certificate_fingerprint"] == "fp-new"
    assert body["uid_reissued"] is True
    assert called["machine_id"] == 7


def test_renew_machine_trust_missing_machine_returns_404(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(machine_id, operator_user_id=None):
        raise NodeServiceError("renew_machine_trust failed: machine 7 not found", reason="machine_not_found")

    monkeypatch.setattr(machine_api.machine_service, "Renew_machine_trust", _raise)

    resp = client.post("/api/machines/renew_machine_trust", json={"machine_id": 7})

    assert resp.status_code == 404
    assert resp.json()["error_reason"] == "machine_not_found"


def test_renew_machine_trust_unreachable_returns_422(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(machine_id, operator_user_id=None):
        raise NodeServiceError("cannot reach", reason="machine_unreachable")

    monkeypatch.setattr(machine_api.machine_service, "Renew_machine_trust", _raise)

    resp = client.post("/api/machines/renew_machine_trust", json={"machine_id": 7})

    assert resp.status_code == 422
    assert resp.json()["error_reason"] == "machine_unreachable"


def test_renew_machine_trust_rejects_invalid_machine_id(client, monkeypatch):
    """入参校验失败走框架的 400（与其它端点一致），不到服务层。"""
    _auth(monkeypatch)

    resp = client.post("/api/machines/renew_machine_trust", json={"machine_id": 0})

    assert resp.status_code == 400
