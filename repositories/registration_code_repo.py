from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

from ..extensions import db
from ..models.registration_code import RegistrationCode


def create_code(email: str, school_domain: str, code: str, expires_at: datetime) -> RegistrationCode:
    try: 
        db.session.query(RegistrationCode).filter_by(email=email, consumed_at=None).delete()
        record = RegistrationCode(
            email=email,
            school_domain=school_domain,
            code_hash=generate_password_hash(code),
            expires_at=expires_at,
        )
        db.session.add(record)
        db.session.commit()
        return record
    except Exception as exc:
        db.session.rollback()
        print(f"Failed to create registration code for {email}: {exc}")
        raise


def verify_code(email: str, code: str, school_domain: str) -> bool:
    record = (
        RegistrationCode.query
        .filter_by(email=email, school_domain=school_domain, consumed_at=None)
        .order_by(RegistrationCode.created_at.desc())
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
