from datetime import datetime, timedelta

from sqlalchemy import select, func

from ...models.registration_code import RegistrationCode
from ...repositories import registration_code_repo


def test_registration_code_repo_verify_success(db_session):
    registration_code_repo.create_code("u@bjtu.edu.cn", "bjtu.edu.cn", "123456", datetime.utcnow() + timedelta(minutes=3), session=db_session)

    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn", session=db_session) is True
    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn", session=db_session) is False


def test_registration_code_repo_rejects_wrong_code(db_session):
    registration_code_repo.create_code("u@bjtu.edu.cn", "bjtu.edu.cn", "123456", datetime.utcnow() + timedelta(minutes=3), session=db_session)

    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "000000", "bjtu.edu.cn", session=db_session) is False


def test_registration_code_repo_rejects_expired_code(db_session):
    # 过期判据是"expires_at < utcnow()"，这里留足余量：1 秒的边界会被宿主机时钟回拨（WSL 时钟同步）打穿
    registration_code_repo.create_code("u@bjtu.edu.cn", "bjtu.edu.cn", "123456", datetime.utcnow() - timedelta(minutes=5), session=db_session)

    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn", session=db_session) is False


def test_registration_code_repo_replaces_active_code_for_same_email(db_session):
    registration_code_repo.create_code("u@bjtu.edu.cn", "bjtu.edu.cn", "111111", datetime.utcnow() + timedelta(minutes=3), session=db_session)
    registration_code_repo.create_code("u@bjtu.edu.cn", "bjtu.edu.cn", "222222", datetime.utcnow() + timedelta(minutes=3), session=db_session)

    count = db_session.scalar(
        select(func.count()).select_from(RegistrationCode).where(
            RegistrationCode.email == "u@bjtu.edu.cn",
            RegistrationCode.consumed_at.is_(None),
        )
    )
    assert count == 1
    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "222222", "bjtu.edu.cn", session=db_session) is True
