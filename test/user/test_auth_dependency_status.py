"""Ctrl 认证依赖的状态码契约（Q04 的 Ctrl 侧）：401 与 403 不得互相冒充。

  - 无凭据 / 无效凭据 / 已过期凭据 → 401（认证问题，语义无歧义）
  - 凭据有效但权限不足 → 403（真权限不足）

前端依赖这条边界：401 触发全局失效（回登录页），403 只是一般拒绝（保留会话）。
这里用真实 cookie token 走 `require_current_user`，不 monkeypatch 掉校验本身。
"""
from datetime import datetime, timedelta

import pytest

from ...extensions import SessionRegistry, session_scope
from ...models.user import User
from ...repositories import auth_repo, authentications_repo
from ..factories import create_auth, create_user

pytestmark = pytest.mark.usefixtures("ensure_auth_users")

# /api/rbac/matrix 需要 rbac:manage：既覆盖 require_current_user，也覆盖 require_permission
MATRIX = "/api/rbac/matrix"


def _auth_user():
    return SessionRegistry.get(User, 1)


def _with_token(client, token):
    """把 cookie 设在 client 上（每个用例一个新 client，不会跨用例残留）。"""
    client.cookies.set("auth_token", token)
    return client


def test_missing_credential_is_401_not_403(client):
    resp = client.get(MATRIX)

    assert resp.status_code == 401
    assert resp.json()["error_reason"] == "invalid_token"


def test_unknown_credential_is_401_not_403(client):
    resp = _with_token(client, "not-a-real-token").get(MATRIX)

    assert resp.status_code == 401
    assert resp.json()["error_reason"] == "invalid_token"


def test_expired_credential_is_401_not_403(client):
    user = _auth_user()
    create_auth(user, token="expired-cookie-token", expires_at=datetime.utcnow() - timedelta(minutes=1))

    resp = _with_token(client, "expired-cookie-token").get(MATRIX)

    assert resp.status_code == 401
    assert resp.json()["error_reason"] == "invalid_token"


def test_valid_credential_without_permission_is_403(client):
    user = _auth_user()
    create_auth(user, token="valid-no-permission-token")

    resp = _with_token(client, "valid-no-permission-token").get(MATRIX)

    assert resp.status_code == 403
    assert resp.json()["error_reason"] == "insufficient_permission"


def test_valid_credential_with_permission_is_200(client):
    user = _auth_user()
    create_auth(user, token="valid-with-permission-token")
    with session_scope() as session:
        group = auth_repo.ensure_group("status_code_manage_test", "test", session=session)
        auth_repo.ensure_group_entity(group.id, "rbac:manage", session=session)
        auth_repo.ensure_user_group(1, group.id, session=session)

    resp = _with_token(client, "valid-with-permission-token").get(MATRIX)

    assert resp.status_code == 200
    assert resp.json()["success"] == 1


def test_logout_deletes_only_its_own_token(client):
    """登出按 token 删除，不做全用户清理——顺带锁住 token 只关联用户、不关联容器的语义。"""
    user = _auth_user()
    create_auth(user, token="logout-target-token")
    create_auth(user, token="logout-other-token")

    resp = _with_token(client, "logout-target-token").post("/api/logout")

    assert resp.status_code == 200
    with session_scope(commit=False) as session:
        assert authentications_repo.is_token_valid("logout-target-token", session=session) is False
        assert authentications_repo.is_token_valid("logout-other-token", session=session) is True


def test_unrelated_user_token_untouched_by_other_users_logout(client):
    owner = create_user(username="logout_owner_user")
    bystander = create_user(username="logout_bystander_user")
    create_auth(owner, token="owner-logout-token")
    create_auth(bystander, token="bystander-keep-token")

    resp = _with_token(client, "owner-logout-token").post("/api/logout")

    assert resp.status_code == 200
    with session_scope(commit=False) as session:
        assert authentications_repo.is_token_valid("bystander-keep-token", session=session) is True
