import pytest
import uuid
import random
from http import HTTPStatus

from .. import create_app
from ..extensions import db
from ..models.user import User
from ..models.authentications import Authentication
from ..blueprints import container_api as container_api_module
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


def test_create_container_unauth(client, monkeypatch):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.post("/api/containers/create_container", json={})
    assert resp.status_code == 401


def test_create_container_success(client, monkeypatch, token):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: True)
    monkeypatch.setattr(container_api_module.container_service, "Create_container", lambda **kwargs: True)
    headers = {"token": token or "dummy"}
    body = {"user_name": "u", "machine_id": 1, "GPU_LIST": [], "CPU_NUMBER": 1, "MEMORY": 128, "NAME": "c1", "image": "img", "public_key": "key"}
    resp = client.post("/api/containers/create_container", json=body, headers=headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data.get("success") == 1


def test_delete_container_unauth(client, monkeypatch):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.post("/api/containers/delete_container", json={"container_id": 1})
    assert resp.status_code == 401


def test_delete_container_success(client, monkeypatch, token):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: True)
    monkeypatch.setattr(container_api_module.container_service, "remove_container", lambda container_id=0: True)
    headers = {"token": token or "dummy"}
    resp = client.post("/api/containers/delete_container", json={"container_id": 1}, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") == 1


def test_add_collaborator_unauth(client, monkeypatch):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.post("/api/containers/add_collaborator", json={})
    assert resp.status_code == 401


def test_add_collaborator_success(client, monkeypatch, token):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: True)
    monkeypatch.setattr(container_api_module.container_service, "add_collaborator", lambda **kwargs: True)
    headers = {"token": token or "dummy"}
    resp = client.post("/api/containers/add_collaborator", json={"user_id": 1, "container_id": 1, "role": "COLLABORATOR"}, headers=headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data.get("success") == 1


def test_remove_collaborator_unauth(client, monkeypatch):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.post("/api/containers/remove_collaborator", json={})
    assert resp.status_code == 401


def test_remove_collaborator_success(client, monkeypatch, token):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: True)
    monkeypatch.setattr(container_api_module.container_service, "remove_collaborator", lambda **kwargs: True)
    headers = {"token": token or "dummy"}
    resp = client.post("/api/containers/remove_collaborator", json={"container_id": 1, "user_id": 1}, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") == 1


def test_update_role_unauth(client, monkeypatch):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.post("/api/containers/update_role", json={})
    assert resp.status_code == 401


def test_update_role_success(client, monkeypatch, token):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: True)
    monkeypatch.setattr(container_api_module.container_service, "update_role", lambda **kwargs: True)
    headers = {"token": token or "dummy"}
    resp = client.post("/api/containers/update_role", json={"container_id": 1, "user_id": 1, "updated_role": "ADMIN"}, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") == 1


def test_get_container_detail_information_unauth(client, monkeypatch):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.get("/api/containers/get_container_detail_information", json={"container_id": 1})
    assert resp.status_code == 401


def test_get_container_detail_information_success(client, monkeypatch, token):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: True)
    fake_info = {"id": 1, "name": "c1", "image": "img"}
    monkeypatch.setattr(container_api_module.container_service, "get_container_detail_information", lambda container_id=0: fake_info)
    headers = {"token": token or "dummy"}
    resp = client.get("/api/containers/get_container_detail_information", json={"container_id": 1}, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") == 1
    assert isinstance(data.get("container_info"), dict)


def test_list_all_containers_bref_information_unauth(client, monkeypatch):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: False)
    resp = client.get("/api/containers/list_all_container_bref_information", json={})
    assert resp.status_code == 401


def test_list_all_containers_bref_information_success(client, monkeypatch, token):
    
    monkeypatch.setattr(container_api_module.authentications_repo, "is_token_valid", lambda t: True)
    fake_item = {"name": "c1", "machine_id": 1}
    monkeypatch.setattr(container_api_module.container_service, "list_all_container_bref_information", lambda machine_id=None, page_number=1, page_size=10: [fake_item])
    headers = {"token": token or "dummy"}
    resp = client.get("/api/containers/list_all_container_bref_information", json={"machine_id": 1}, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") == 1
    assert isinstance(data.get("containers_info"), list)

