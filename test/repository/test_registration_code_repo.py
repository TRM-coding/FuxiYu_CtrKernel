from datetime import datetime, timedelta

from sqlalchemy import select, func

from ...models.registration_code import RegistrationCode
from ...repositories import registration_code_repo


def _create(email, code, *, minutes=3, session):
    return registration_code_repo.create_code(
        email, "bjtu.edu.cn", code, datetime.utcnow() + timedelta(minutes=minutes), session=session,
    )


def test_verify_code_is_read_only(db_session):
    _create("u@bjtu.edu.cn", "123456", session=db_session)

    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn", session=db_session) is True
    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn", session=db_session) is True

    record = db_session.scalars(select(RegistrationCode).where(RegistrationCode.email == "u@bjtu.edu.cn")).one()
    assert record.consumed_at is None, "只校验不得写 consumed_at"


def test_verify_and_consume_code_success_is_not_reusable(db_session):
    _create("u@bjtu.edu.cn", "123456", session=db_session)

    assert registration_code_repo.verify_and_consume_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn", session=db_session) is True
    assert registration_code_repo.verify_and_consume_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn", session=db_session) is False

    record = db_session.scalars(select(RegistrationCode).where(RegistrationCode.email == "u@bjtu.edu.cn")).one()
    assert record.consumed_at is not None


def test_consume_code_rejects_stale_reader(db_session):
    """并发同码至多成功一次：两次读都看到有效记录，条件 UPDATE 只放行一条。"""

    _create("u@bjtu.edu.cn", "123456", session=db_session)

    first_read = registration_code_repo.find_valid_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn", session=db_session)
    second_read = registration_code_repo.find_valid_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn", session=db_session)
    assert first_read is not None and second_read is not None

    assert registration_code_repo.consume_code(first_read.id, session=db_session) is True
    db_session.commit()

    assert registration_code_repo.consume_code(second_read.id, session=db_session) is False


def test_consume_code_missing_record_returns_false(db_session):
    assert registration_code_repo.consume_code(999999, session=db_session) is False


def test_registration_code_repo_rejects_wrong_code(db_session):
    _create("u@bjtu.edu.cn", "123456", session=db_session)

    assert registration_code_repo.verify_code("u@bjtu.edu.cn", "000000", "bjtu.edu.cn", session=db_session) is False
    assert registration_code_repo.verify_and_consume_code("u@bjtu.edu.cn", "000000", "bjtu.edu.cn", session=db_session) is False

    record = db_session.scalars(select(RegistrationCode).where(RegistrationCode.email == "u@bjtu.edu.cn")).one()
    assert record.consumed_at is None, "错误码不得消费有效验证码"


def test_registration_code_repo_rejects_expired_code(db_session):
    # 过期判据是"expires_at < utcnow()"，这里留足余量：1 秒的边界会被宿主机时钟回拨（WSL 时钟同步）打穿
    registration_code_repo.create_code("u@bjtu.edu.cn", "bjtu.edu.cn", "123456", datetime.utcnow() - timedelta(minutes=5), session=db_session)

    assert registration_code_repo.verify_and_consume_code("u@bjtu.edu.cn", "123456", "bjtu.edu.cn", session=db_session) is False


def test_registration_code_repo_replaces_active_code_for_same_email(db_session):
    _create("u@bjtu.edu.cn", "111111", session=db_session)
    _create("u@bjtu.edu.cn", "222222", session=db_session)

    count = db_session.scalar(
        select(func.count()).select_from(RegistrationCode).where(
            RegistrationCode.email == "u@bjtu.edu.cn",
            RegistrationCode.consumed_at.is_(None),
        )
    )
    assert count == 1
    assert registration_code_repo.verify_and_consume_code("u@bjtu.edu.cn", "222222", "bjtu.edu.cn", session=db_session) is True
    assert registration_code_repo.verify_and_consume_code("u@bjtu.edu.cn", "111111", "bjtu.edu.cn", session=db_session) is False
