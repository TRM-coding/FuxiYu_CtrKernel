from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

from ..extensions import db
from ..models.email_change_code import EmailChangeCode


def create_code(user_id: int, new_email: str, school_domain: str, code: str, expires_at: datetime) -> EmailChangeCode:
    db.session.query(EmailChangeCode).filter_by(user_id=user_id, new_email=new_email, consumed_at=None).delete()
    record = EmailChangeCode(
        user_id=user_id,
        new_email=new_email,
        school_domain=school_domain,
        code_hash=generate_password_hash(code),
        expires_at=expires_at,
    )
    db.session.add(record)
    db.session.commit()
    return record


def verify_code(user_id: int, new_email: str, code: str, school_domain: str) -> bool:
    record = (
        EmailChangeCode.query
        .filter_by(user_id=user_id, new_email=new_email, school_domain=school_domain, consumed_at=None)
        .order_by(EmailChangeCode.created_at.desc())
        .first()
    )
    if not record:
        return False
    if record.expires_at < datetime.utcnow():
        return False
    if not check_password_hash(record.code_hash, code):
        return False
    record.consumed_at = datetime.utcnow()
    db.session.commit()
    return True
