from datetime import datetime, timedelta
import json

import pytest
from sqlalchemy import select

from ...extensions import session_scope
from ...models.operation_log import OperationLog
from ...models.registration_code import RegistrationCode

from ...repositories import registration_code_repo
from ...services import user_tasks
from ..factories import create_user


def _issue_code(email, code, *, minutes=3):
    """在独立事务里发一条验证码（等价 /request_register_code 的落库部分）。"""
    with session_scope() as session:
        registration_code_repo.create_code(
            email=email,
            school_domain=email.rsplit("@", 1)[-1].lower(),
            code=code,
            expires_at=datetime.utcnow() + timedelta(minutes=minutes),
            session=session,
        )


def _code_consumed(email) -> bool:
    with session_scope(commit=False) as session:
        record = session.scalars(
            select(RegistrationCode).where(RegistrationCode.email == email)
        ).first()
    return record is not None and record.consumed_at is not None


def test_request_register_code_success_creates_code_and_sends_mail(monkeypatch, db_session):
    sent = []
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp", lambda **kwargs: sent.append(kwargs) or {"ok": True})
    monkeypatch.setattr(user_tasks.secrets, "randbelow", lambda _: 12345)

    success, reason, retry_after = user_tasks.Request_register_code("code_user@bjtu.edu.cn")

    assert success is True
    assert reason == "code_sent"
    assert sent and sent[0]["to"] == "code_user@bjtu.edu.cn"

    record = db_session.scalars(select(RegistrationCode).where(RegistrationCode.email == "code_user@bjtu.edu.cn")).first()
    assert record is not None
    assert registration_code_repo.verify_code("code_user@bjtu.edu.cn", "012345", "bjtu.edu.cn", session=db_session) is True
    log = db_session.scalars(select(OperationLog).where(OperationLog.operation == "send_mail")).one()
    assert log.detail["mail_type"] == "registration_code"
    assert log.detail["name"] == "code_user@bjtu.edu.cn"
    assert "012345" not in json.dumps(log.detail)


def test_request_register_code_rejects_unallowed_domain(db_session):
    success, reason, retry_after = user_tasks.Request_register_code("user@example.com")

    assert success is False
    assert reason == "email_domain_not_allowed"


def test_registered_email_does_not_receive_new_registration_code(monkeypatch, db_session):
    user = create_user(email="already@bjtu.edu.cn")
    sent = []
    monkeypatch.setattr(user_tasks, "send_mail", lambda **kwargs: sent.append(kwargs))
    assert user_tasks.Request_register_code(user.email) == (False, "email_exists", None)
    assert sent == []
    assert db_session.scalars(select(RegistrationCode).where(RegistrationCode.email == user.email)).first() is None


def test_registration_code_cooldown_blocks_repeat_email(monkeypatch, db_session):
    sent = []
    monkeypatch.setattr(user_tasks, "send_mail", lambda **kwargs: sent.append(kwargs) or {"ok": True})
    success, reason, remaining = user_tasks.Request_register_code("new@bjtu.edu.cn")
    assert success and reason == "code_sent" and 0 <= remaining <= 60
    success, reason, remaining = user_tasks.Request_register_code("NEW@bjtu.edu.cn")
    assert not success and reason == "rate_limited" and 0 < remaining <= 60
    assert len(sent) == 1


def test_registration_code_api_reports_existing_email_and_cooldown(client, monkeypatch, db_session):
    create_user(email="registered@bjtu.edu.cn")
    sent = []
    monkeypatch.setattr(user_tasks, "send_mail", lambda **kwargs: sent.append(kwargs) or {"ok": True})
    conflict = client.post("/api/request_register_code", json={"email": "registered@bjtu.edu.cn"})
    assert conflict.status_code == 409
    assert conflict.json()["error_reason"] == "email_exists"
    assert "retry_after_seconds" not in conflict.json()
    sent_response = client.post("/api/request_register_code", json={"email": "fresh@bjtu.edu.cn"})
    assert sent_response.status_code == 200
    assert 0 <= sent_response.json()["retry_after_seconds"] <= 60
    limited = client.post("/api/request_register_code", json={"email": "fresh@bjtu.edu.cn"})
    assert limited.status_code == 429
    assert limited.json()["error_reason"] == "rate_limited"
    assert 0 < limited.json()["retry_after_seconds"] <= 60
    assert len(sent) == 1


def test_request_register_code_handles_create_failure(monkeypatch, db_session):
    monkeypatch.setattr(user_tasks.registration_code_repo, "create_code", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db failed")))

    success, reason, retry_after = user_tasks.Request_register_code("user@bjtu.edu.cn")

    assert success is False
    assert reason == "code_creation_failed"


def test_request_register_code_handles_mail_failure(monkeypatch, db_session):
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp", lambda **kwargs: {"ok": False})

    success, reason, retry_after = user_tasks.Request_register_code("user@bjtu.edu.cn")

    assert success is False
    assert reason == "mail_send_failed"
    log = db_session.scalars(select(OperationLog).where(OperationLog.operation == "send_mail")).one()
    assert log.success is False


def test_register_with_code_requires_code(db_session):
    success, reason, user = user_tasks.Register_with_code("u", "u@bjtu.edu.cn", "Password_123", "2026", "")

    assert success is False
    assert reason == "registration_code_required"
    assert user is None


def test_register_with_code_rejects_unallowed_domain(db_session):
    success, reason, user = user_tasks.Register_with_code("u", "u@example.com", "Password_123", "2026", "123456")

    assert success is False
    assert reason == "email_domain_not_allowed"
    assert user is None


def test_register_with_code_success_consumes_code_and_creates_user(db_session):
    _issue_code("ok@bjtu.edu.cn", "123456")

    success, user, token = user_tasks.Register_with_code("ok_user", "ok@bjtu.edu.cn", "Password_123", "2026", "123456")

    assert success is True
    assert token is None
    assert user.username == "ok_user"
    assert _code_consumed("ok@bjtu.edu.cn") is True

    # 必要身份关联已生效：新用户绑定默认 user 组（与注册成功同一提交）
    from ...repositories import auth_repo

    with session_scope(commit=False) as session:
        default_group = auth_repo.get_group("user", session=session)
        group_ids = auth_repo.list_user_group_ids(user.id, session=session)
    assert default_group is not None
    assert default_group.id in group_ids


def test_register_with_code_default_group_failure_rolls_back(monkeypatch, db_session):
    """必要注册步骤（默认组绑定）失败时遵守同一成功边界：用户与消费整体回滚。"""

    from ...models.user import User

    _issue_code("group_fail@bjtu.edu.cn", "123456")

    def boom(session, user_id):
        raise RuntimeError("group bind failed")

    monkeypatch.setattr(user_tasks, "_bind_default_group_in_session", boom)

    with pytest.raises(RuntimeError, match="group bind failed"):
        user_tasks.Register_with_code("group_fail", "group_fail@bjtu.edu.cn", "Password_123", "2026", "123456")

    assert _code_consumed("group_fail@bjtu.edu.cn") is False
    with session_scope(commit=False) as session:
        assert session.scalars(select(User).where(User.username == "group_fail")).first() is None


def test_register_with_code_rejects_invalid_code(db_session):
    _issue_code("bad_code@bjtu.edu.cn", "123456")

    success, reason, user = user_tasks.Register_with_code("bad_code", "bad_code@bjtu.edu.cn", "Password_123", "2026", "bad")

    assert success is False
    assert reason == "registration_code_invalid"
    assert user is None
    assert _code_consumed("bad_code@bjtu.edu.cn") is False


def test_register_with_code_rejects_expired_code(db_session):
    _issue_code("expired@bjtu.edu.cn", "123456", minutes=-5)

    success, reason, user = user_tasks.Register_with_code("expired", "expired@bjtu.edu.cn", "Password_123", "2026", "123456")

    assert success is False
    assert reason == "registration_code_invalid"
    assert user is None
    assert _code_consumed("expired@bjtu.edu.cn") is False


def test_register_with_code_duplicate_username_keeps_code_for_retry(db_session):
    create_user(username="taken", email="taken@bjtu.edu.cn")
    _issue_code("dup_user@bjtu.edu.cn", "123456")

    success, reason, user = user_tasks.Register_with_code("taken", "dup_user@bjtu.edu.cn", "Password_123", "2026", "123456")

    assert (success, reason, user) == (False, "username_exists", None)
    assert _code_consumed("dup_user@bjtu.edu.cn") is False, "注册失败不得消费验证码"

    # 同一验证码仍可用：改一个未被占用的用户名即注册成功
    retry_success, retry_user, _ = user_tasks.Register_with_code("dup_user", "dup_user@bjtu.edu.cn", "Password_123", "2026", "123456")
    assert retry_success is True and retry_user.username == "dup_user"
    assert _code_consumed("dup_user@bjtu.edu.cn") is True


def test_register_with_code_duplicate_email_keeps_code(db_session):
    create_user(username="email_owner", email="dup_email@bjtu.edu.cn")
    _issue_code("dup_email@bjtu.edu.cn", "123456")

    success, reason, user = user_tasks.Register_with_code("email_new", "dup_email@bjtu.edu.cn", "Password_123", "2026", "123456")

    assert (success, reason, user) == (False, "email_exists", None)
    assert _code_consumed("dup_email@bjtu.edu.cn") is False


def test_register_with_code_invalid_username_does_not_consume_code(db_session):
    _issue_code("bad_name@bjtu.edu.cn", "123456")

    success, reason, user = user_tasks.Register_with_code("bad name", "bad_name@bjtu.edu.cn", "Password_123", "2026", "123456")

    assert (success, reason, user) == (False, "invalid_username", None)
    assert _code_consumed("bad_name@bjtu.edu.cn") is False


def test_register_with_code_non_ascii_password_does_not_consume_code(db_session):
    _issue_code("bad_pass@bjtu.edu.cn", "123456")

    success, reason, user = user_tasks.Register_with_code("bad_pass", "bad_pass@bjtu.edu.cn", "密码123", "2026", "123456")

    assert (success, reason, user) == (False, "no_none_ascii", None)
    assert _code_consumed("bad_pass@bjtu.edu.cn") is False


def test_register_with_code_success_is_not_reusable(db_session):
    _issue_code("reuse@bjtu.edu.cn", "123456")

    success, _, _ = user_tasks.Register_with_code("reuse", "reuse@bjtu.edu.cn", "Password_123", "2026", "123456")
    assert success is True

    again_success, again_reason, _ = user_tasks.Register_with_code("reuse2", "reuse@bjtu.edu.cn", "Password_123", "2026", "123456")
    assert (again_success, again_reason) == (False, "registration_code_invalid")


def test_register_with_code_unique_constraint_backstops_precheck_race(monkeypatch, db_session):
    """预检与写入之间冒出同名用户（模拟并发）：唯一约束兜底，消费回滚，返回既有原因。"""

    create_user(username="race_user", email="race_owner@bjtu.edu.cn")
    _issue_code("race_new@bjtu.edu.cn", "123456")

    real_get_by_name = user_tasks.get_by_name
    state = {"blinded": False}

    def blinded_once(username, *, session):
        if username == "race_user" and not state["blinded"]:
            state["blinded"] = True
            return None  # 模拟预检时对方还没落库
        return real_get_by_name(username, session=session)

    monkeypatch.setattr(user_tasks, "get_by_name", blinded_once)

    success, reason, user = user_tasks.Register_with_code("race_user", "race_new@bjtu.edu.cn", "Password_123", "2026", "123456")

    assert (success, reason, user) == (False, "username_exists", None)
    assert _code_consumed("race_new@bjtu.edu.cn") is False


def test_register_with_code_db_failure_rolls_back_consumption_and_retry_succeeds(monkeypatch, db_session):
    _issue_code("db_fail@bjtu.edu.cn", "123456")

    from ...repositories import user_repo

    real_create = user_repo.create_user
    calls = {"n": 0}

    def flaky_create_user(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db write failed")
        return real_create(**kwargs)

    monkeypatch.setattr(user_tasks, "create_user", flaky_create_user)

    with pytest.raises(RuntimeError, match="db write failed"):
        user_tasks.Register_with_code("db_fail", "db_fail@bjtu.edu.cn", "Password_123", "2026", "123456")

    assert _code_consumed("db_fail@bjtu.edu.cn") is False, "数据库写失败必须回滚验证码消费"

    retry_success, retry_user, _ = user_tasks.Register_with_code("db_fail", "db_fail@bjtu.edu.cn", "Password_123", "2026", "123456")
    assert retry_success is True and retry_user.username == "db_fail"
    assert _code_consumed("db_fail@bjtu.edu.cn") is True


def test_code_api_failure_then_cooldown(client, monkeypatch, db_session):
    monkeypatch.setattr(user_tasks, "send_mail", lambda **kwargs: {"ok": False})
    first = client.post("/api/request_register_code", json={"email": "failed@bjtu.edu.cn"})
    assert first.status_code == 500 and "retry_after_seconds" not in first.json()
    second = client.post("/api/request_register_code", json={"email": "failed@bjtu.edu.cn"})
    assert second.status_code == 429 and 0 < second.json()["retry_after_seconds"] <= 60


def test_code_api_cooldown_expires(client, monkeypatch, db_session):
    monkeypatch.setattr(user_tasks, "send_mail", lambda **kwargs: {"ok": True})
    email = "expired_cooldown@bjtu.edu.cn"
    assert client.post("/api/request_register_code", json={"email": email}).status_code == 200
    with session_scope() as session:
        record = session.scalars(select(RegistrationCode).where(RegistrationCode.email == email)).one()
        record.created_at = datetime.utcnow() - timedelta(seconds=61)
    assert client.post("/api/request_register_code", json={"email": email}).status_code == 200


def test_success_remaining_accounts_for_mail_send_time(client, monkeypatch, db_session):
    class Clock(datetime):
        offset = 0
        @classmethod
        def utcnow(cls):
            return datetime.utcnow() + timedelta(seconds=cls.offset)

    def slow_send(**kwargs):
        Clock.offset = 25
        return {"ok": True}

    monkeypatch.setattr(user_tasks, "datetime", Clock)
    monkeypatch.setattr(user_tasks, "send_mail", slow_send)
    response = client.post("/api/request_register_code", json={"email": "slow@bjtu.edu.cn"})
    assert response.status_code == 200
    assert 30 <= response.json()["retry_after_seconds"] <= 35
