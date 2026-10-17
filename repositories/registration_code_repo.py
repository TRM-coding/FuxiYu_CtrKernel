"""注册验证码仓储。"""
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from ..models.registration_code import RegistrationCode


def create_code(
    email: str,
    school_domain: str,
    code: str,
    expires_at: datetime,
    *,
    session: Session,
) -> RegistrationCode:
    """创建验证码，并清除该邮箱未消费的旧验证码。"""
    session.execute(
        delete(RegistrationCode).where(
            RegistrationCode.email == email,
            RegistrationCode.consumed_at.is_(None),
        )
    )
    record = RegistrationCode(
        email=email,
        school_domain=school_domain,
        code_hash=generate_password_hash(code),
        expires_at=expires_at,
    )
    session.add(record)
    session.flush()
    return record


def find_valid_code(
    email: str,
    code: str,
    school_domain: str,
    *,
    session: Session,
    now: datetime | None = None,
) -> RegistrationCode | None:
    """读取该邮箱最新一条未消费、未过期且哈希匹配的验证码；只读，不改任何状态。"""

    now = now or datetime.utcnow()
    stmt = (
        select(RegistrationCode)
        .where(
            RegistrationCode.email == email,
            RegistrationCode.school_domain == school_domain,
            RegistrationCode.consumed_at.is_(None),
        )
        .order_by(RegistrationCode.created_at.desc())
    )
    record = session.scalars(stmt).first()
    if not record:
        return None
    if record.expires_at < now:
        return None
    if not check_password_hash(record.code_hash, code):
        return None
    return record


def consume_code(
    record_id: int,
    *,
    session: Session,
    now: datetime | None = None,
) -> bool:
    """条件消费未使用的验证码，以实际更新行数确认本次是否成功。"""

    now = now or datetime.utcnow()
    result = session.execute(
        update(RegistrationCode)
        .where(
            RegistrationCode.id == record_id,
            RegistrationCode.consumed_at.is_(None),
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def verify_and_consume_code(
    email: str,
    code: str,
    school_domain: str,
    *,
    session: Session,
    now: datetime | None = None,
) -> bool:
    """在调用方注册事务内校验并消费验证码，不自行提交。"""

    record = find_valid_code(email, code, school_domain, session=session, now=now)
    if record is None:
        return False
    return consume_code(record.id, session=session, now=now)


def verify_code(
    email: str,
    code: str,
    school_domain: str,
    *,
    session: Session,
    now: datetime | None = None,
) -> bool:
    """只校验、不消费。会改变状态的一律走 verify_and_consume_code。"""

    return find_valid_code(email, code, school_domain, session=session, now=now) is not None
