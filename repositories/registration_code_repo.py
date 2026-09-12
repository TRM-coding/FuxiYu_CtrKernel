"""注册验证码仓储。"""
from datetime import datetime

from sqlalchemy import delete, select
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


def verify_code(email: str, code: str, school_domain: str, *, session: Session) -> bool:
    """校验验证码，成功后标记为已消费。"""
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
        return False
    if record.expires_at < datetime.utcnow():
        return False
    if not check_password_hash(record.code_hash, code):
        return False
    record.consumed_at = datetime.utcnow()
    session.flush()
    return True
