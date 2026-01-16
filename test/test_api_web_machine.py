import pytest
import uuid
import random
from http import HTTPStatus

from .. import create_app
from ..extensions import db
from ..models.user import User
from ..models.authentications import Authentication
from datetime import datetime, timedelta

# module-level test token placeholder
TOKEN_FOR_TESTING = None


@pytest.fixture(scope="session")
def app():
    app = create_app()
    app.config.update(TESTING=True)
    
    with app.app_context():
        # 确保所有模型已导入后再建表
        from ..models import user, machine, containers, usercontainer, authentications  # noqa: F401
        db.create_all()
        # 创建用于测试的认证 token
        try:
            from ..repositories.authentications_repo import create_auth, delete_auth
            global TOKEN_FOR_TESTING
            TOKEN_FOR_TESTING = f"test_{uuid.uuid4().hex}"
            expires_at = datetime.utcnow() + timedelta(hours=1)
            create_auth(TOKEN_FOR_TESTING, expires_at)
        except Exception:
            # 如果仓库或模型尚未准备好，则跳过创建（测试代码可以自行处理）
            TOKEN_FOR_TESTING = None
        yield app
        # 为避免误删开发库数据，这里不 drop_all
        # 测试结束后清理 token
        try:
            if TOKEN_FOR_TESTING:
                from ..repositories.authentications_repo import delete_auth
                delete_auth(TOKEN_FOR_TESTING)
        except Exception:
            pass


@pytest.fixture()
def client(app):
    return app.test_client()

@pytest.fixture()
def token():
    return TOKEN_FOR_TESTING

from types import SimpleNamespace


def test_add_machine_api_unauth(client, monkeypatch):
    from ..blueprints import machine_api as machine_api_module
    monkeypatch.setattr(machine_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.get("/api/containers/add_machine", json={})
    assert resp.status_code == 401


def test_add_machine_api_success(client, monkeypatch, token):
    from ..blueprints import machine_api as machine_api_module
    monkeypatch.setattr(machine_api_module.authentications_repo, "is_token_valid", lambda t: True)
    monkeypatch.setattr(machine_api_module.machine_service, "Add_machine", lambda **kwargs: True)
    headers = {"token": token or "dummy"}
    resp = client.get("/api/containers/add_machine", json={"machine_name": "m1"}, headers=headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data.get("success") == 1


def test_remove_machine_api_unauth(client, monkeypatch):
    from ..blueprints import machine_api as machine_api_module
    monkeypatch.setattr(machine_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.post("/api/machines/remove_machine", json={"machine_ids": [1]})
    assert resp.status_code == 401


def test_remove_machine_api_success(client, monkeypatch, token):
    from ..blueprints import machine_api as machine_api_module
    monkeypatch.setattr(machine_api_module.authentications_repo, "is_token_valid", lambda t: True)
    monkeypatch.setattr(machine_api_module.machine_service, "Remove_machine", lambda machine_id=None: True)
    headers = {"token": token or "dummy"}
    resp = client.post("/api/machines/remove_machine", json={"machine_ids": [1]}, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") == 1


def test_update_machine_api_unauth(client, monkeypatch):
    from ..blueprints import machine_api as machine_api_module
    monkeypatch.setattr(machine_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.get("/api/machines/update_machine", json={"machine_id": 1, "fields": {}})
    assert resp.status_code == 401


def test_update_machine_api_success(client, monkeypatch, token):
    from ..blueprints import machine_api as machine_api_module
    monkeypatch.setattr(machine_api_module.authentications_repo, "is_token_valid", lambda t: True)
    monkeypatch.setattr(machine_api_module.machine_service, "Update_machine", lambda machine_id=0, **fields: True)
    headers = {"token": token or "dummy"}
    resp = client.get("/api/machines/update_machine", json={"machine_id": 1, "fields": {"machine_name": "new"}}, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") == 1


def test_get_detail_information_api_unauth(client, monkeypatch):
    from ..blueprints import machine_api as machine_api_module
    monkeypatch.setattr(machine_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.post("/api/machines/get_detail_information", json={"machine_id": 1})
    assert resp.status_code == 401


def test_get_detail_information_api_success(client, monkeypatch, token):
    from ..blueprints import machine_api as machine_api_module
    monkeypatch.setattr(machine_api_module.authentications_repo, "is_token_valid", lambda t: True)
    fake_machine = SimpleNamespace(
        id=1,
        machine_name="m",
        machine_ip="127.0.0.1",
        machine_type="t",
        machine_description="d",
        cpu_core_number=4,
        gpu_number=0,
        gpu_type="",
        memory_size_gb=16,
        disk_size_gb=100,
        containers=[],
    )
    monkeypatch.setattr(machine_api_module.machine_service, "Get_detail_information", lambda machine_id=0: fake_machine)
    headers = {"token": token or "dummy"}
    resp = client.post("/api/machines/get_detail_information", json={"machine_id": 1}, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("machine_id") == 1


def test_list_all_machine_bref_information_api_unauth(client, monkeypatch):
    from ..blueprints import machine_api as machine_api_module
    monkeypatch.setattr(machine_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.get("/api/machines/list_all_machine_bref_information", json={})
    assert resp.status_code == 401


def test_list_all_machine_bref_information_api_success(client, monkeypatch, token):
    from ..blueprints import machine_api as machine_api_module
    monkeypatch.setattr(machine_api_module.authentications_repo, "is_token_valid", lambda t: True)
    fake_machine = SimpleNamespace(machine_ip="1.2.3.4", machine_type="t", machine_status="up")
    monkeypatch.setattr(machine_api_module.machine_service, "List_all_machine_bref_information", lambda page_number=0, page_size=10: [fake_machine])
    headers = {"token": token or "dummy"}
    resp = client.get("/api/machines/list_all_machine_bref_information", json={}, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data.get("machines"), list)
    
