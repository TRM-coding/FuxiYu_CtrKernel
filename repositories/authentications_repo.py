"""认证 Token 数据访问仓库

封装 authentications 表的数据库操作逻辑。
"""

from datetime import datetime
from typing import Optional
from ..extensions import db
from ..models.authentications import Authentication


def get_by_token(token: str) -> Optional[Authentication]:
    """根据 token 查询认证记录
    
    Args:
        token: 认证 token 字符串
        
    Returns:
        Authentication 对象或 None
    """
    return Authentication.query.filter_by(token=token).first()


def create_auth(token: str, expires_at: datetime, *, commit: bool = True) -> Authentication:
    """创建新的认证记录
    
    Args:
        token: 认证 token 字符串
        expires_at: 过期时间
        commit: 是否立即提交事务
        
    Returns:
        创建的 Authentication 对象
    """
    auth = Authentication(
        token=token,
        expires_at=expires_at
    )
    db.session.add(auth)
    if commit:
        db.session.commit()
    return auth


def delete_auth(token: str, *, commit: bool = True) -> bool:
    """删除认证记录
    
    Args:
        token: 认证 token 字符串
        commit: 是否立即提交事务
        
    Returns:
        是否成功删除
    """
    auth = get_by_token(token)
    if auth:
        db.session.delete(auth)
        if commit:
            db.session.commit()
        return True
    return False


def is_token_valid(token: str) -> bool:
    """检查 token 是否有效（存在且未过期）
    
    Args:
        token: 认证 token 字符串
        
    Returns:
        是否有效
    """
    auth = get_by_token(token)
    if auth and auth.expires_at > datetime.utcnow():
        return True
    return False


def cleanup_expired_tokens(*, commit: bool = True) -> int:
    """清理所有过期的 token
    
    Args:
        commit: 是否立即提交事务
        
    Returns:
        清理的记录数量
    """
    count = Authentication.query.filter(
        Authentication.expires_at <= datetime.utcnow()
    ).delete()
    if commit:
        db.session.commit()
    return count
