import pytest
import uuid
import random
from http import HTTPStatus

from .. import create_app
from ..extensions import db
from ..models.user import User
from ..utils.Authentication import Authentication


@pytest.fixture(scope="session")
def app():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        # 确保所有模型已导入后再建表
        from ..models import user, machine, containers, usercontainer  # noqa: F401
        from ..utils import Authentication as _auth  # noqa: F401
        db.create_all()
        yield app
        # 为避免误删开发库数据，这里不 drop_all


@pytest.fixture()
def client(app):
    return app.test_client()


def _random_user_payload():
    username = f"api_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = f"P@ss_{uuid.uuid4().hex[:6]}"
    graduation_year = str(random.randint(2020, 2030))
    return {
        "username": username,
        "email": email,
        "password": password,
        "graduation_year": graduation_year,
    }


def test_register_api_success(client):
    payload = _random_user_payload()
    resp = client.post("/api/register", json=payload)
    assert resp.status_code == HTTPStatus.CREATED
    data = resp.get_json()
    assert data.get("success") == 1
    assert data.get("user", {}).get("username") == payload["username"]

    # 清理：删除创建的用户
    with client.application.app_context():
        u = User.query.filter_by(username=payload["username"]).first()
        if u:
            db.session.delete(u)
            db.session.commit()


def test_login_api_success_sets_cookie(client):
    # 先注册
    payload = _random_user_payload()
    r = client.post("/api/register", json=payload)
    assert r.status_code in (HTTPStatus.CREATED, HTTPStatus.BAD_REQUEST)
    if r.status_code == HTTPStatus.BAD_REQUEST:
        pytest.skip("随机用户名冲突，跳过")

    # 再登录
    login_resp = client.post("/api/login", json={
        "username": payload["username"],
        "password": payload["password"],
    })
    assert login_resp.status_code == HTTPStatus.OK
    data = login_resp.get_json()
    assert data.get("success") == 1

    # Set-Cookie 应包含 auth_token
    set_cookie = login_resp.headers.get("Set-Cookie", "")
    assert "auth_token=" in set_cookie

    # 清理
    with client.application.app_context():
        u = User.query.filter_by(username=payload["username"]).first()
        if u:
            db.session.delete(u)
            db.session.commit()


def test_login_api_failure_wrong_password(client):
    # 注册
    payload = _random_user_payload()
    r = client.post("/api/register", json=payload)
    assert r.status_code in (HTTPStatus.CREATED, HTTPStatus.BAD_REQUEST)
    if r.status_code == HTTPStatus.BAD_REQUEST:
        pytest.skip("随机用户名冲突，跳过")

    # 用错误密码登录
    bad_login = client.post("/api/login", json={
        "username": payload["username"],
        "password": payload["password"] + "x",
    })
    assert bad_login.status_code == HTTPStatus.UNAUTHORIZED
    data = bad_login.get_json()
    assert data.get("success") == 0

    # 清理
    with client.application.app_context():
        u = User.query.filter_by(username=payload["username"]).first()
        if u:
            db.session.delete(u)
            db.session.commit()
