from datetime import datetime, timedelta

from ...models.registration_code import RegistrationCode
from ...repositories import registration_code_repo


def test_registration_code_repo_verify_success(db_session):
    registration_code_repo.create_code("u@bjtu.edu.cn", "bjtu.edu.cn", "123456", datetime.utcnow() + timedelta(minutes=3))

    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn") is True
    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn") is False


def test_registration_code_repo_rejects_wrong_code(db_session):
    registration_code_repo.create_code("u@bjtu.edu.cn", "bjtu.edu.cn", "123456", datetime.utcnow() + timedelta(minutes=3))

    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "000000", "bjtu.edu.cn") is False


def test_registration_code_repo_rejects_expired_code(db_session):
    registration_code_repo.create_code("u@bjtu.edu.cn", "bjtu.edu.cn", "123456", datetime.utcnow() - timedelta(seconds=1))

    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn") is False


def test_registration_code_repo_replaces_active_code_for_same_email(db_session):
    registration_code_repo.create_code("u@bjtu.edu.cn", "bjtu.edu.cn", "111111", datetime.utcnow() + timedelta(minutes=3))
    registration_code_repo.create_code("u@bjtu.edu.cn", "bjtu.edu.cn", "222222", datetime.utcnow() + timedelta(minutes=3))

    assert RegistrationCode.query.filter_by(email="u@bjtu.edu.cn", consumed_at=None).count() == 1
    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "222222", "bjtu.edu.cn") is True
