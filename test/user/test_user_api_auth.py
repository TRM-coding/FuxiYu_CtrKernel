from types import SimpleNamespace

from ...api import user_api, deps
from ...constant import PERMISSION


def _fake_user(**overrides):
    data = {
        "id": 1,
        "username": "api_user",
        "email": "api_user@bjtu.edu.cn",
        "permission": PERMISSION.USER,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_register_success(client, monkeypatch):
    monkeypatch.setattr(user_api.user_tasks, "Register_with_code", lambda *args: (True, _fake_user(), None))

    resp = client.post("/api/register", json={
        "username": "api_user",
        "email": "api_user@bjtu.edu.cn",
        "password": "Password_123",
        "graduation_year": "2026",
        "registration_code": "123456",
    })

    assert resp.status_code == 201
    assert resp.json()["success"] == 1


def test_register_blank_graduation_year_is_optional(client, monkeypatch):
    captured = {}

    def _register(username, email, password, graduation_year, registration_code):
        captured["graduation_year"] = graduation_year
        return True, _fake_user(), None

    monkeypatch.setattr(user_api.user_tasks, "Register_with_code", _register)

    resp = client.post("/api/register", json={
        "username": "api_user",
        "email": "api_user@bjtu.edu.cn",
        "password": "Password_123",
        "graduation_year": "",
        "registration_code": "123456",
    })

    assert resp.status_code == 201
    assert captured["graduation_year"] is None


def test_register_invalid_json(client):
    resp = client.post("/api/register", content="not-json", headers={"content-type": "application/json"})

    assert resp.status_code == 400


def test_register_missing_required_fields(client):
    resp = client.post("/api/register", json={"username": "api_user"})

    assert resp.status_code == 400


def test_register_duplicate_username_returns_409(client, monkeypatch):
    monkeypatch.setattr(user_api.user_tasks, "Register_with_code", lambda *args: (False, "username_exists", None))

    resp = client.post("/api/register", json={
        "username": "api_user",
        "email": "api_user@bjtu.edu.cn",
        "password": "Password_123",
        "graduation_year": "2026",
        "registration_code": "123456",
    })

    assert resp.status_code == 409
    assert resp.json()["error_reason"] == "username_exists"


def test_register_registration_code_required_returns_400(client, monkeypatch):
    monkeypatch.setattr(user_api.user_tasks, "Register_with_code", lambda *args: (False, "registration_code_required", None))

    resp = client.post("/api/register", json={
        "username": "api_user",
        "email": "api_user@bjtu.edu.cn",
        "password": "Password_123",
        "graduation_year": "2026",
    })

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "registration_code_required"


def test_request_register_code_success(client, monkeypatch):
    monkeypatch.setattr(user_api.user_tasks, "Request_register_code", lambda email: (True, "code_sent"))

    resp = client.post("/api/request_register_code", json={"email": "api_user@bjtu.edu.cn"})

    assert resp.status_code == 200
    assert resp.json()["success"] == 1


def test_request_register_code_missing_email(client):
    resp = client.post("/api/request_register_code", json={})

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "missing_email"


def test_request_register_code_domain_not_allowed(client, monkeypatch):
    monkeypatch.setattr(user_api.user_tasks, "Request_register_code", lambda email: (False, "email_domain_not_allowed"))

    resp = client.post("/api/request_register_code", json={"email": "api_user@example.com"})

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "email_domain_not_allowed"


def test_login_success_sets_cookie(client, monkeypatch):
    monkeypatch.setattr(user_api.user_tasks, "Login", lambda username, password, remember: (True, _fake_user(), "token-1"))

    resp = client.post("/api/login", json={"username": "api_user", "password": "Password_123"})

    assert resp.status_code == 200
    # token 已不再出现在 JSON body，只走 httpOnly cookie
    assert "token" not in resp.json()
    assert "auth_token=token-1" in resp.headers.get("Set-Cookie", "")


def test_login_user_not_found(client, monkeypatch):
    monkeypatch.setattr(user_api.user_tasks, "Login", lambda username, password, remember: (False, "user_not_found", None))

    resp = client.post("/api/login", json={"username": "missing", "password": "Password_123"})

    assert resp.status_code == 404
    assert resp.json()["error_reason"] == "user_not_found"


def test_login_wrong_password(client, monkeypatch):
    monkeypatch.setattr(user_api.user_tasks, "Login", lambda username, password, remember: (False, "password_incorrect", None))

    resp = client.post("/api/login", json={"username": "api_user", "password": "bad"})

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "password_incorrect"
