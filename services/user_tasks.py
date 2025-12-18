#限制：注册用户名必须是英文
from ..models.user import User
from werkzeug.security import check_password_hash, generate_password_hash
from ..extensions import db
from ..repositories.user_repo import *
from ..repositories import authentications_repo
from pydantic import BaseModel
from datetime import datetime, timedelta
import secrets

#####################################
# API Definition

class user_bref_information(BaseModel):
    user_id:int
    username:str
    email:str
    graduation_year:int
#####################################

#####################################
#登录验证
def Login(username: str, password: str):
    """用户登录验证并生成认证 token
    
    Args:
        username: 用户名
        password: 密码
        
    Returns:
        tuple: (是否成功, User对象或错误原因, token或None)
               - 用户不存在: (False, "user_not_found", None)
               - 密码错误: (False, "password_incorrect", None)
               - 登录成功: (True, User对象, token)
    """
    # 检查用户是否存在
    user = User.query.filter_by(username=username).first()
    if not user:
        return False, "user_not_found", None
    
    # 检查密码是否正确
    if not check_password_hash(user.password_hash, password):
        return False, "password_incorrect", None
    
    # 登录成功，生成 token
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=24)
    auth = authentications_repo.create_auth(token, expires_at)
    
    return True, user, auth.token
#####################################


#####################################
#注册
def Register(username: str, email: str, password: str, graduation_year) -> User | None:
    # 检查用户名或邮箱是否已存在
    if User.query.filter((User.username == username) | (User.email == email)).first():
        return None  # 用户名或邮箱已存在，注册失败

    # 创建新用户
    new_user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        graduation_year=graduation_year
    )
    db.session.add(new_user)
    db.session.commit()
    return new_user
#####################################


#####################################
#修改密码
#####################################
def Change_password(user: User, old_password: str, new_password: str) -> bool:
    if check_password_hash(user.password_hash, old_password):
        update_user(user.id, password_hash=generate_password_hash(new_password))
        return True
    return False

#####################################
#注销用户
def Delete_user(user_id: int) -> bool:
    delete_user(user_id=user_id)
    return True
    
#####################################


#####################################
# 分页返回users
def List_all_user_bref_information(page_number:int, page_size:int)->list[user_bref_information]:
    raise NotImplementedError

#####################################
#忘记密码
#TODO:实现邮件发送功能
#####################################

