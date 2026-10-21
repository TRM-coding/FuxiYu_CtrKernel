from types import SimpleNamespace

import pytest

from ...extensions import session_scope
from ...models.machine import Machine
from ...services.container_module.exceptions import NodeServiceError

from ...api import machine_api, deps
from ..factories import create_machine


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

    def register(name, ip, description, port=None):
        calls.append((name, ip, description, port))
        return {"machine_id": 1, "uid": "node-uid", "certificate_fingerprint": "fingerprint", "hardware": {}}

    monkeypatch.setattr(machine_api.machine_service, "Register_machine", register)
    response = client.post(
        "/api/machines/register_machine",
        json={"machine_name": "node", "machine_ip": "10.0.0.1", "machine_description": "GPU host"},
    )
    assert response.status_code == 200
    assert response.json()["machine_id"] == 1
    assert response.json()["uid"] == "node-uid"
    assert calls == [("node", "10.0.0.1", "GPU host", None)]


def test_register_machine_error_reason_returns_422(client, monkeypatch):
    _auth(monkeypatch)

    def fail(*args, **kwargs):
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


def test_update_machine_forwards_port(client, monkeypatch):
    _auth(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        machine_api.machine_service, "Update_machine",
        lambda machine_id, **fields: seen.update(fields) or True,
    )

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {"port": 6789}})

    assert resp.status_code == 200
    assert seen.get("port") == 6789


def test_update_machine_explicit_null_clears_port(client, monkeypatch):
    """显式传 null ≠ 没传这个字段。

    前者是「清空」（端口回落全局默认），后者是「别动它」。接口因此用 exclude_unset
    取字段——若用 exclude_none，两者不可分辨，端口一旦设过就再也去不掉。
    """
    _auth(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        machine_api.machine_service, "Update_machine",
        lambda machine_id, **fields: seen.update(fields) or True,
    )

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {"port": None}})

    assert resp.status_code == 200
    assert "port" in seen and seen["port"] is None


def test_update_machine_omitted_port_is_untouched(client, monkeypatch):
    """没传 port → 落到 Update_machine 的字段里根本没有它。"""
    _auth(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        machine_api.machine_service, "Update_machine",
        lambda machine_id, **fields: seen.update(fields) or True,
    )

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {"machine_name": "new"}})

    assert resp.status_code == 200
    assert "port" not in seen


def test_register_machine_forwards_optional_port(client, monkeypatch):
    _auth(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        machine_api.machine_service, "Register_machine",
        lambda name, ip, description, port=None: seen.update(port=port)
        or {"machine_id": 1, "uid": "u", "certificate_fingerprint": "f", "hardware": {}},
    )

    resp = client.post(
        "/api/machines/register_machine",
        json={"machine_name": "node", "machine_ip": "10.0.0.1", "port": 6789},
    )

    assert resp.status_code == 200
    assert seen.get("port") == 6789


@pytest.mark.parametrize("bad_port", [0, 65536, -1])
def test_register_machine_rejects_out_of_range_port(client, monkeypatch, bad_port):
    _auth(monkeypatch)
    called = []
    monkeypatch.setattr(
        machine_api.machine_service, "Register_machine",
        lambda *a, **k: called.append(1) or {},
    )

    resp = client.post(
        "/api/machines/register_machine",
        json={"machine_name": "node", "machine_ip": "10.0.0.1", "port": bad_port},
    )

    assert resp.status_code == 400, "请求体校验失败由框架挡下（本项目用 400）"
    assert called == [], "越界端口不该走到服务层"


def test_update_machine_validation_error_returns_422(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(machine_id, **fields):
        exc = ValueError("bad")
        exc.error_reason = "update_failed"
        raise exc

    monkeypatch.setattr(machine_api.machine_service, "Update_machine", _raise)

    resp = client.post("/api/machines/update_machine", json={"machine_id": 1, "fields": {"max_shared_gb": 99}} )

    assert resp.status_code == 422


def test_update_machine_api_saves_shared_above_8_within_memory(client, monkeypatch, db_session):
    """真实服务路径（不替换 Update_machine）：32GB 内存的机器可存下 16GB 共享上限。

    旧实现固定按 8GB 拒绝，这条会 422；移除硬码后必须真的落库。
    """
    _auth(monkeypatch)
    machine = create_machine(max_memory_gb=32, max_shared_gb=8)

    resp = client.post(
        "/api/machines/update_machine",
        json={"machine_id": machine.id, "fields": {"max_shared_gb": 16}},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    db_session.expire_all()
    assert db_session.get(Machine, machine.id).max_shared_gb == 16


def test_update_machine_api_rejects_shared_above_memory(client, monkeypatch, db_session):
    """真实服务路径：共享上限超过目标内存上限 → 422 update_failed，且记录不变。"""
    _auth(monkeypatch)
    machine = create_machine(max_memory_gb=8, max_shared_gb=4)

    resp = client.post(
        "/api/machines/update_machine",
        json={"machine_id": machine.id, "fields": {"max_shared_gb": 16}},
    )

    assert resp.status_code == 422
    body = resp.json()
    assert body["error_reason"] == "update_failed"
    assert "cannot be greater" in body["message"]
    db_session.expire_all()
    assert db_session.get(Machine, machine.id).max_shared_gb == 4


def test_update_machine_api_accepts_memory_lowered_to_shared(client, monkeypatch, db_session):
    """真实服务路径：只降内存上限但仍 >= 既有共享上限 → 200 且两字段落库。"""
    _auth(monkeypatch)
    machine = create_machine(max_memory_gb=32, max_shared_gb=16)

    resp = client.post(
        "/api/machines/update_machine",
        json={"machine_id": machine.id, "fields": {"max_memory_gb": 16}},
    )

    assert resp.status_code == 200
    db_session.expire_all()
    refreshed = db_session.get(Machine, machine.id)
    assert refreshed.max_memory_gb == 16
    assert refreshed.max_shared_gb == 16


def test_update_machine_api_accepts_equal_shared_and_memory(client, monkeypatch, db_session):
    """真实服务路径：同请求 mem=8/shared=8 → 200。"""
    _auth(monkeypatch)
    machine = create_machine(max_memory_gb=32, max_shared_gb=4)

    resp = client.post(
        "/api/machines/update_machine",
        json={"machine_id": machine.id, "fields": {"max_shared_gb": 8, "max_memory_gb": 8}},
    )

    assert resp.status_code == 200
    db_session.expire_all()
    refreshed = db_session.get(Machine, machine.id)
    assert refreshed.max_shared_gb == 8
    assert refreshed.max_memory_gb == 8


def test_update_machine_api_rejects_memory_lowered_below_existing_shared(client, monkeypatch, db_session):
    """真实服务路径：既有 shared16/mem32，只请求降 mem=8 → 422，且两个字段与改名都不落。"""
    _auth(monkeypatch)
    machine = create_machine(max_memory_gb=32, max_shared_gb=16, machine_name="api_before_reject")

    resp = client.post(
        "/api/machines/update_machine",
        json={
            "machine_id": machine.id,
            "fields": {"max_memory_gb": 8, "machine_name": "api_renamed"},
        },
    )

    assert resp.status_code == 422
    body = resp.json()
    assert body["error_reason"] == "update_failed"
    assert "cannot be greater" in body["message"]
    db_session.expire_all()
    refreshed = db_session.get(Machine, machine.id)
    assert refreshed.max_shared_gb == 16
    assert refreshed.max_memory_gb == 32
    assert refreshed.machine_name == "api_before_reject"


def test_update_machine_api_rejects_null_shared_with_memory_lowered(client, monkeypatch, db_session):
    """真实 API：{max_shared_gb: null, max_memory_gb: 8} 不能绕过。

    `exclude_unset` 会把显式 null 送进服务层，但仓库层对这两个字段跳过 None、不执行清空，
    所以落库后共享仍是 16，与 mem=8 组合照样越界；同请求改名也不落。
    """
    _auth(monkeypatch)
    machine = create_machine(max_memory_gb=32, max_shared_gb=16, machine_name="api_null_shared_before")

    resp = client.post(
        "/api/machines/update_machine",
        json={
            "machine_id": machine.id,
            "fields": {
                "max_shared_gb": None,
                "max_memory_gb": 8,
                "machine_name": "api_null_shared_after",
            },
        },
    )

    assert resp.status_code == 422
    assert resp.json()["error_reason"] == "update_failed"
    db_session.expire_all()
    refreshed = db_session.get(Machine, machine.id)
    assert refreshed.max_shared_gb == 16
    assert refreshed.max_memory_gb == 32
    assert refreshed.machine_name == "api_null_shared_before"


def test_update_machine_api_rejects_null_memory_with_shared_raised(client, monkeypatch, db_session):
    """真实 API：{max_memory_gb: null, max_shared_gb: 40} 不能绕过——落库后内存仍是 32。"""
    _auth(monkeypatch)
    machine = create_machine(max_memory_gb=32, max_shared_gb=16)

    resp = client.post(
        "/api/machines/update_machine",
        json={"machine_id": machine.id, "fields": {"max_memory_gb": None, "max_shared_gb": 40}},
    )

    assert resp.status_code == 422
    assert resp.json()["error_reason"] == "update_failed"
    db_session.expire_all()
    refreshed = db_session.get(Machine, machine.id)
    assert refreshed.max_shared_gb == 16
    assert refreshed.max_memory_gb == 32


@pytest.mark.parametrize("bad_shared", [-1, "bad", 3.5])
def test_update_machine_api_rejects_invalid_shared_input(client, monkeypatch, bad_shared):
    """负数/非整数/非整小数在请求模型层被挡下：400 + 既有 invalid_payload（不改错误映射契约）。

    服务层的 `update_failed`（422）只覆盖通过请求模型的合法整数输入；两者是不同边界。
    """
    _auth(monkeypatch)
    machine = create_machine(max_memory_gb=32)

    resp = client.post(
        "/api/machines/update_machine",
        json={"machine_id": machine.id, "fields": {"max_shared_gb": bad_shared}},
    )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_payload"


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


def test_get_machine_detail_returns_configured_port(client, monkeypatch, db_session):
    """Q15：response_model 必须保留服务返回的 port，不能把自定义端口过滤成默认。"""

    _auth(monkeypatch)
    machine = create_machine(machine_name="detail_port_machine")
    with session_scope() as session:
        session.get(Machine, machine.id).port = 6789

    resp = client.post("/api/machines/get_detail_information", json={"machine_id": machine.id})

    assert resp.status_code == 200
    assert resp.json()["port"] == 6789


def test_get_machine_detail_keeps_null_port_without_default_filling(client, monkeypatch, db_session):
    """Q15：未配置端口回传 null，MUST NOT 填入全局默认端口号掩盖真实配置。"""

    _auth(monkeypatch)
    machine = create_machine(machine_name="detail_default_port_machine")
    with session_scope() as session:
        session.get(Machine, machine.id).port = None

    resp = client.post("/api/machines/get_detail_information", json={"machine_id": machine.id})

    assert resp.status_code == 200
    assert resp.json()["port"] is None


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
