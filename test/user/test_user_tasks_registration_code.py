from datetime import datetime, timedelta

from ...models.registration_code import RegistrationCode
from ...repositories import registration_code_repo
from ...services import user_tasks


def test_request_register_code_success_creates_code_and_sends_mail(monkeypatch, db_session):
    sent = []
    monkeypatch.setattr(user_tasks, "send_mail", lambda **kwargs: sent.append(kwargs) or {"ok": True})
    monkeypatch.setattr(user_tasks.secrets, "randbelow", lambda _: 12345)

    success, reason = user_tasks.Request_register_code("code_user@bjtu.edu.cn")

    assert success is True
    assert reason == "code_sent"
    assert sent and sent[0]["to"] == "code_user@bjtu.edu.cn"
    record = RegistrationCode.query.filter_by(email="code_user@bjtu.edu.cn").first()
    assert record is not None
    assert registration_code_repo.verify_code("code_user@bjtu.edu.cn", "012345", "bjtu.edu.cn") is True


def test_request_register_code_rejects_unallowed_domain(db_session):
    success, reason = user_tasks.Request_register_code("user@example.com")

    assert success is False
    assert reason == "email_domain_not_allowed"


def test_request_register_code_handles_create_failure(monkeypatch, db_session):
    monkeypatch.setattr(user_tasks.registration_code_repo, "create_code", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db failed")))

    success, reason = user_tasks.Request_register_code("user@bjtu.edu.cn")

    assert success is False
    assert reason == "code_creation_failed"


def test_request_register_code_handles_mail_failure(monkeypatch, db_session):
    monkeypatch.setattr(user_tasks, "send_mail", lambda **kwargs: {"ok": False})

    success, reason = user_tasks.Request_register_code("user@bjtu.edu.cn")

    assert success is False
    assert reason == "mail_send_failed"


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


def test_register_with_code_rejects_invalid_code(db_session):
    success, reason, user = user_tasks.Register_with_code("u", "u@bjtu.edu.cn", "Password_123", "2026", "bad")

    assert success is False
    assert reason == "registration_code_invalid"
    assert user is None


def test_register_with_code_calls_register_after_verify_success(monkeypatch, db_session):
    called = {}
    monkeypatch.setattr(user_tasks.registration_code_repo, "verify_code", lambda **kwargs: True)

    def _register(*args):
        called["args"] = args
        return True, "user", None

    monkeypatch.setattr(user_tasks, "Register", _register)

    success, user, token = user_tasks.Register_with_code("u", "u@bjtu.edu.cn", "Password_123", "2026", "123456")

    assert success is True
    assert user == "user"
    assert token is None
    assert called["args"] == ("u", "u@bjtu.edu.cn", "Password_123", "2026")


def test_registration_code_repo_rejects_expired_code(db_session):
    registration_code_repo.create_code(
        email="expired@bjtu.edu.cn",
        school_domain="bjtu.edu.cn",
        code="123456",
        expires_at=datetime.utcnow() - timedelta(seconds=1),
    )

    assert registration_code_repo.verify_code("expired@bjtu.edu.cn", "123456", "bjtu.edu.cn") is False
