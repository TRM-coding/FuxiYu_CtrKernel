#限制：注册用户名必须是英文
from models.user import User
from werkzeug.security import check_password_hash, generate_password_hash
from extensions import db
from ..repositories.user_repo import *

#####################################
#登录验证
def Login(username: str, password: str) -> bool:

    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        return True
    return False
#####################################


#####################################
#注册
def Register(username: str, email: str, password_hash: str, graduation_year) -> User | None:
    # 检查用户名或邮箱是否已存在
    if User.query.filter((User.username == username) | (User.email == email)).first():
        return None  # 用户名或邮箱已存在，注册失败

    # 创建新用户
    new_user = User(
        username=username,
        email=email,
        password_hash=password_hash,
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
#忘记密码
#TODO:实现邮件发送功能
#####################################

