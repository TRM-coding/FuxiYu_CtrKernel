from datetime import datetime, timedelta
from ..extensions import db
import secrets

class Authentication(db.Model):
    __tablename__ = "authentications"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    
    # 关系
    user = db.relationship('User', backref='authentications')
    
    @staticmethod
    def generate_token():
        """生成唯一的token"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def create_token(user_id, expires_in_hours=24):
        """为用户创建新的认证token
        
        Args:
            user_id: 用户ID
            expires_in_hours: token过期时间（小时数）
            
        Returns:
            Authentication对象
        """
        token = Authentication.generate_token()
        expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
        
        auth = Authentication(
            user_id=user_id,
            token=token,
            expires_at=expires_at
        )
        db.session.add(auth)
        db.session.commit()
        return auth
    
    @staticmethod
    def verify_token(token):
        """验证token是否有效
        
        Args:
            token: token字符串
            
        Returns:
            Authentication对象如果有效，否则None
        """
        auth = Authentication.query.filter_by(token=token).first()
        if auth and auth.expires_at > datetime.utcnow():
            return auth
        return None
    
    @staticmethod
    def revoke_token(token):
        """撤销token"""
        auth = Authentication.query.filter_by(token=token).first()
        if auth:
            db.session.delete(auth)
            db.session.commit()
            return True
        return False
    
    def is_expired(self):
        """检查token是否已过期"""
        return datetime.utcnow() > self.expires_at
