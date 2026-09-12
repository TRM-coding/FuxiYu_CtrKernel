"""认证 Token 仓储。"""
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models.authentications import Authentication


def get_by_token(token: str, *, session: Session) -> Authentication | None:
    """根据 token 查询认证记录。"""
    stmt = select(Authentication).where(Authentication.token == token)
    return session.scalars(stmt).first()


def get_user_id_by_token(token: str, *, session: Session) -> int | None:
    """根据 token 查询关联 user_id。"""
    auth = get_by_token(token, session=session)
    return auth.user_id if auth else None


def create_auth(
    token: str,
    user_id: int,
    expires_at: datetime,
    *,
    session: Session,
) -> Authentication:
    """创建认证记录。"""
    cleanup_expired_tokens(session=session)
    auth = Authentication(token=token, expires_at=expires_at, user_id=user_id)
    session.add(auth)
    session.flush()
    return auth


def delete_auth(token: str, *, session: Session) -> bool:
    """删除认证记录。"""
    auth = get_by_token(token, session=session)
    if not auth:
        return False
    session.delete(auth)
    session.flush()
    return True


def is_token_valid(token: str, *, session: Session) -> bool:
    """检查 token 是否存在且未过期。"""
    auth = get_by_token(token, session=session)
    return bool(auth and auth.expires_at > datetime.utcnow())


def cleanup_expired_tokens(*, session: Session) -> int:
    """清理过期 token。"""
    result = session.execute(
        delete(Authentication).where(Authentication.expires_at <= datetime.utcnow())
    )
    session.flush()
    return int(result.rowcount or 0)
