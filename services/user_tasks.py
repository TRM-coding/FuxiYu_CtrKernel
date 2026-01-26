#限制：注册用户名必须是英文
from ..models.user import User
from werkzeug.security import check_password_hash, generate_password_hash
from ..extensions import db
from ..repositories.user_repo import *
from ..repositories import authentications_repo
from ..repositories import usercontainer_repo, containers_repo
from ..constant import ROLE, ContainerStatus
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
    containers:list[int]
    amount_of_container: int
    amount_of_functional_container:int
    amount_of_managed_container:int

class user_detail_information(BaseModel):
    user_id:int
    username:str
    email:str
    graduation_year:int
    containers:list[int]  # 容器id列表
    
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
def Register(username: str, email: str, password: str, graduation_year):
    """用户注册
    
    Args:
        username: 用户名
        email: 邮箱
        password: 密码
        graduation_year: 毕业年份
        
    Returns:
        tuple: (是否成功, User对象或错误原因, None)
               - 用户名已存在: (False, "username_exists", None)
               - 邮箱已存在: (False, "email_exists", None)
               - 注册成功: (True, User对象, None)
    """
    # 检查用户名是否已存在
    if User.query.filter_by(username=username).first():
        return False, "username_exists", None
    
    # 检查邮箱是否已存在
    if User.query.filter_by(email=email).first():
        return False, "email_exists", None
    
    # 创建新用户
    new_user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        graduation_year=graduation_year
    )
    db.session.add(new_user)
    db.session.commit()
    return True, new_user, None
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
# 返回users_detail
def Get_user_detail_information(user_id: int)->user_detail_information:
    if not user_id:
        return None
    try:
        user = User.query.get(int(user_id))
    except Exception:
        return None

    if not user:
        return None

    # get container bindings for this user
    bindings = usercontainer_repo.get_user_bindings(user.id) or []
    container_ids = [b.get('container_id') for b in bindings]

    # compute counts based on role values stored in bindings
    return user_detail_information(
        user_id=user.id,
        username=user.username,
        email=user.email,
        graduation_year=user.graduation_year,
        containers=container_ids,
    )
#####################################

#####################################
# 分页返回users
def List_all_user_bref_information(page_number:int, page_size:int)->list[user_bref_information]:
    try:
        pn = int(page_number) if page_number and int(page_number) > 0 else 1
    except Exception:
        pn = 1
    try:
        ps = int(page_size) if page_size and int(page_size) > 0 else 10
    except Exception:
        ps = 10

    offset = (pn - 1) * ps
    users = list_users(limit=ps, offset=offset)
    result: list[user_bref_information] = []
    for u in users:
        bindings = usercontainer_repo.get_user_bindings(u.id) or []
        container_ids = [b.get('container_id') for b in bindings]
        total = len(container_ids)
        # count functional containers as bindings where role is COLLABORATOR and the container is ONLINE
        functional = 0
        managed = 0
        for b in bindings:
            try:
                role_val = b.get('role')
                cid = b.get('container_id')
                if cid is None:
                    continue
                # fetch container to check status
                container = containers_repo.get_by_id(int(cid))
                is_online = False
                if container and getattr(container, 'container_status', None) is not None:
                    # container.container_status may be an Enum
                    try:
                        is_online = (container.container_status == ContainerStatus.ONLINE or getattr(container.container_status, 'value', None) == ContainerStatus.ONLINE.value)
                    except Exception:
                        is_online = (str(container.container_status).lower() == ContainerStatus.ONLINE.value)

                # functional now counts any bound container that is ONLINE (regardless of role)
                if is_online:
                    functional += 1

                # manage counts ADMIN and ROOT roles
                # role_val from DB can be either an Enum or a raw string depending on DB driver; normalize to string
                try:
                    if isinstance(role_val, ROLE):
                        role_name = role_val.value
                    else:
                        role_name = str(role_val)
                except Exception:
                    role_name = str(role_val)

                if role_name == ROLE.ADMIN.value or role_name == ROLE.ROOT.value:
                    managed += 1
            except Exception:
                # ignore binding errors and continue
                continue

        # Optionally use containers_repo to validate container ids or fetch additional info
        result.append(user_bref_information(
            user_id=u.id,
            username=u.username,
            email=u.email,
            graduation_year=u.graduation_year,
            containers=container_ids,
            amount_of_container=total,
            amount_of_functional_container=functional,
            amount_of_managed_container=managed,
        ))
    return result
#####################################

#####################################
#忘记密码
#TODO:实现邮件发送功能
#####################################

