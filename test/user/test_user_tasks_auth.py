from werkzeug.security import check_password_hash

from ...models.authentications import Authentication
from ...models.user import User
from ...services import user_tasks
from ..factories import create_user


def test_login_success_creates_auth_token(db_session):
    user = create_user(username="login_user", password="Password_123")

    success, login_user, token = user_tasks.Login("login_user", "Password_123")

    assert success is True
    assert login_user.id == user.id
    assert token
    auth = Authentication.query.filter_by(token=token).first()
    assert auth is not None
    assert auth.user_id == user.id


def test_login_user_not_found(db_session):
    success, reason, token = user_tasks.Login("missing", "Password_123")

    assert success is False
    assert reason == "user_not_found"
    assert token is None


def test_login_with_email(db_session):
    """登录字段允许填邮箱：用户名查不到时按 email 回退。"""
    user = create_user(username="email_login_user", password="Password_123")

    success, login_user, token = user_tasks.Login(user.email, "Password_123")

    assert success is True
    assert login_user.id == user.id
    assert token


def test_login_wrong_password_does_not_create_token(db_session):
    create_user(username="wrong_password_user", password="Password_123")

    success, reason, token = user_tasks.Login("wrong_password_user", "bad")

    assert success is False
    assert reason == "password_incorrect"
    assert token is None
    assert Authentication.query.count() == 0


def test_change_password_success(db_session):
    user = create_user(username="change_password_user", password="old_password")

    assert user_tasks.Change_password(user, "old_password", "new_password") is True

    refreshed = User.query.get(user.id)
    assert check_password_hash(refreshed.password_hash, "new_password")
    success, _, _ = user_tasks.Login("change_password_user", "new_password")
    assert success is True


def test_change_password_wrong_old_password_keeps_original(db_session):
    user = create_user(username="change_password_fail_user", password="old_password")
    before_hash = user.password_hash

    assert user_tasks.Change_password(user, "bad_old_password", "new_password") is False

    refreshed = User.query.get(user.id)
    assert refreshed.password_hash == before_hash
    assert check_password_hash(refreshed.password_hash, "old_password")


def test_reset_password_success_returns_expected_plain_password_and_saves_hash(db_session):
    user = create_user(username="reset_user", password="old_password", graduation_year="2026")

    new_password = user_tasks.Reset_password(user.id)

    assert new_password == "2026reset_user"
    refreshed = User.query.get(user.id)
    assert check_password_hash(refreshed.password_hash, new_password)


def test_reset_password_missing_user_returns_none(db_session):
    assert user_tasks.Reset_password(999999) is None
