#限制：注册用户名必须是英文
from ..models.user import User
from werkzeug.security import check_password_hash, generate_password_hash
from ..extensions import session_scope
from ..repositories.user_repo import *
from ..repositories import auth_repo, authentications_repo
from ..repositories import registration_code_repo
from ..repositories import usercontainer_repo, containers_repo, long_term_container_repo
from ..utils.container_lock import container_role_lock
from .operation_log_tasks import log_failure, log_success
from ..utils.mail import send as send_mail
from ..constant import ROLE, ContainerStatus, OperationType
from pydantic import BaseModel
from datetime import datetime, timedelta
import secrets

from sqlalchemy.exc import IntegrityError

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
    amount_of_long_term_container:int

class user_detail_information(BaseModel):
    user_id:int
    username:str
    email:str
    graduation_year:int
    containers:list[int]  # 容器id列表
    amount_of_container: int = 0
    amount_of_functional_container: int = 0
    amount_of_managed_container: int = 0
    amount_of_long_term_container: int = 0
    
#####################################

#####################################
#登录验证
def Login(username: str, password: str, *, remember: bool = False):
    """用户登录验证并生成认证 token
    
    Args:
        username: 用户名
        password: 密码
        remember: 是否长期 - 默认False，控制cookeis生命周期
        
    Returns:
        tuple: (是否成功, User对象或错误原因, token或None)
               - 用户不存在: (False, "user_not_found", None)
               - 密码错误: (False, "password_incorrect", None)
               - 登录成功: (True, User对象, token)
    """
    # 检查用户是否存在：用户名优先；用户名规则不含 @，可无歧义地回退按邮箱查
    with session_scope() as session:
        user = get_by_name(username, session=session)
        if not user:
            user = get_by_email(username, session=session)
        if not user:
            return False, "user_not_found", None

        # 检查密码是否正确
        if not check_password_hash(user.password_hash, password):
            return False, "password_incorrect", None

        # 登录成功，生成 token
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(days=30 if remember else 1)
        auth = authentications_repo.create_auth(token, user.id, expires_at, session=session)
        return True, user, auth.token
#####################################


#####################################
#注册
def _validate_registration_fields(username: str, email: str, password: str) -> str | None:
    """校验注册参数，返回错误原因或 None。"""
    # enforce length limits
    if username and len(username) > 75:
        return "username_too_long"
    if email and len(email) > 115:
        return "email_too_long"

    # 禁用非ASCII字符（如中文）以避免数据库异常
    import re

    # username must be strict identifier: letters/digits/underscore only
    def _is_valid_username(s: str) -> bool:
        try:
            if s is None:
                return False
            return bool(re.match(r'^[A-Za-z0-9_]+$', s))
        except Exception:
            return False

    def _is_all_ascii(s: str) -> bool:
        try:
            if s is None:
                return True
            return all(ord(ch) < 128 for ch in s)
        except Exception:
            return False

    # enforce username format first
    if not _is_valid_username(username):
        return 'invalid_username'

    # keep ascii checks for other fields
    if not _is_all_ascii(email) or not _is_all_ascii(password):
        return "no_none_ascii"
    return None


def _registration_conflict_reason(session, username: str, email: str) -> str | None:
    """重名预检：只用于给出既有 error_reason；唯一性最终由 users 唯一约束兜底。"""

    if get_by_name(username, session=session):
        return "username_exists"
    if get_by_email(email, session=session):
        return "email_exists"
    return None


def _create_user_row(session, username: str, email: str, password: str, graduation_year):
    """在调用方事务内建用户；事务结束后再由调用方记录审计。"""
    reason = _registration_conflict_reason(session, username=username, email=email)
    if reason:
        return reason, None
    new_user = create_user(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        graduation_year=graduation_year,
        session=session,
    )
    return None, new_user


def _bind_default_group_in_session(session, user_id: int) -> None:
    """在注册事务内绑定默认组，绑定失败时交由调用方整体回滚。"""

    group = auth_repo.get_group("user", session=session)
    if group is not None:
        auth_repo.ensure_user_group(user_id, group.id, session=session)


def Register(username: str, email: str, password: str, graduation_year):
    """普通建号，保留既有校验、默认组绑定与返回元组。"""
    reason = _validate_registration_fields(username, email, password)
    if reason:
        return False, reason, None

    try:
        with session_scope() as session:
            reason, new_user = _create_user_row(
                session, username=username, email=email, password=password,
                graduation_year=graduation_year,
            )
            if reason:
                return False, reason, None
    except Exception as e:
        log_failure(operation=OperationType.REGISTER_USER, target_type="user", target_id=0,
                     detail={"username": username, "email": email}, error_reason=str(e))
        raise
    # RBAC 建号组绑定：新用户默认 user 组（operator 建号由 seed 显式绑 operator 组）
    from .rbac_service import bind_user_default_group
    bind_user_default_group(new_user.id)
    log_success(operation=OperationType.REGISTER_USER, target_type="user", target_id=new_user.id,
                 detail={"username": username, "email": email})
    return True, new_user, None
#####################################


#####################################
#修改密码
#####################################
def Change_password(user: User, old_password: str, new_password: str) -> bool:
    # disallow non-ASCII characters in passwords
    # def _is_all_ascii(s: str) -> bool:
    #     try:
    #         if s is None:
    #             return True
    #         return all(ord(ch) < 128 for ch in s)
    #     except Exception:
    #         print(f"Error checking ASCII for password: {s}")
    #         return False
    print(f"Attempting to change password for user_id={user.id}")

    try:
        if not check_password_hash(user.password_hash, old_password):
            print("Old password does not match.")
            log_failure(operator_user_id=user.id, operation=OperationType.CHANGE_PASSWORD,
                         target_type="user", target_id=user.id,
                         detail={"username": user.username}, error_reason="old_password_incorrect")
            return False
    except Exception as e:
        print(f"Error checking old password hash: {e}")
        log_failure(operator_user_id=user.id, operation=OperationType.CHANGE_PASSWORD,
                     target_type="user", target_id=user.id,
                     detail={"username": user.username}, error_reason=str(e))
        return False
    try:
        with session_scope() as session:
            update_user(user.id, password_hash=generate_password_hash(new_password), session=session)
    except Exception as e:
        print(f"Error updating password in database: {e}")
        log_failure(operator_user_id=user.id, operation=OperationType.CHANGE_PASSWORD,
                     target_type="user", target_id=user.id,
                     detail={"username": user.username}, error_reason=str(e))
        return False
    print("Password changed successfully.")
    log_success(operator_user_id=user.id, operation=OperationType.CHANGE_PASSWORD,
                 target_type="user", target_id=user.id,
                 detail={"username": user.username})
    return True

#####################################
#注销用户
def Delete_user(user_id: int, operator_user_id: int | None = None) -> bool:
    username = None
    try:
        with session_scope(commit=False) as session:
            user = get_by_id(user_id, session=session)
            username = getattr(user, "username", None)

        # 先移除用户与所有容器的绑定关系
        with session_scope(commit=False) as session:
            res = usercontainer_repo.remove_user_from_all_containers(user_id, session=session)

        if not res.get('ok', False):
            wild = res.get('wild_containers')
            if wild:
                e = Exception("Wild container NOT allowed. Must remove all affected containers first.")
                setattr(e, 'wild_containers', wild)
                raise e
            log_failure(operator_user_id=operator_user_id,
                operation=OperationType.DELETE_USER,
                target_type="user",
                target_id=user_id,
                detail={"username": username},
                error_reason="remove_bindings_failed",
            )
            return False

        from . import container_tasks

        def _role_step_failed(reason: str) -> bool:
            log_failure(operator_user_id=operator_user_id,
                operation=OperationType.DELETE_USER,
                target_type="user",
                target_id=user_id,
                detail={"username": username},
                error_reason=reason,
            )
            return False

        for item in res.get("transfer_required", []) or []:
            cid = item.get("container_id")
            new_root_uid = item.get("new_root_user_id")
            with container_role_lock(cid):
                if container_tasks.get_container_binding_role(cid, user_id) != ROLE.ROOT.value:
                    return _role_step_failed(f"old_root_changed:container:{cid}")
                if not container_tasks.promote_root_sync(
                    container_id=cid,
                    user_id=new_root_uid,
                    operator_user_id=operator_user_id,
                ):
                    return _role_step_failed(f"transfer_root_role_failed:container:{cid}")
                if not container_tasks.update_role(
                    container_id=cid,
                    user_id=user_id,
                    updated_role=ROLE.COLLABORATOR,
                    operator_user_id=operator_user_id,
                ):
                    return _role_step_failed(f"demote_user_failed:container:{cid}")
                if not container_tasks.remove_collaborator(
                    container_id=cid,
                    user_id=user_id,
                    operator_user_id=operator_user_id,
                ):
                    return _role_step_failed(f"remove_user_binding_failed:container:{cid}")

        for cid in res.get("removable", []) or []:
            if not container_tasks.remove_collaborator(
                container_id=cid,
                user_id=user_id,
                operator_user_id=operator_user_id,
            ):
                return _role_step_failed(f"remove_user_binding_failed:container:{cid}")

        # 最终删除用户：认证 Token 与用户行在同一事务内删除。
        # authentications 只外键关联 users（不关联容器）。若先删用户，外键约束会让整个
        # 事务回滚，API 层再把这个异常说成「野容器阻止删除」——归因完全错。放在同一
        # session_scope 里，两者要么都删掉，要么都保留（token 删除失败则整体回滚，用户仍在）。
        with session_scope() as session:
            user = get_by_id(user_id, session=session)
            username = getattr(user, "username", username)
            authentications_repo.delete_tokens_by_user_id(user_id, session=session)
            ok = delete_user(user_id=user_id, session=session)
        if ok:
            log_success(operator_user_id=operator_user_id,
                operation=OperationType.DELETE_USER,
                target_type="user",
                target_id=user_id,
                detail={"username": username},
            )
            return True

        log_failure(operator_user_id=operator_user_id,
            operation=OperationType.DELETE_USER,
            target_type="user",
            target_id=user_id,
            detail={"username": username},
            error_reason="delete_failed",
        )
        return False
    except Exception as exc:
        log_failure(operator_user_id=operator_user_id,
            operation=OperationType.DELETE_USER,
            target_type="user",
            target_id=user_id,
            detail={"username": username},
            error_reason=getattr(exc, "error_reason", None) or str(exc),
        )
        raise
    
#####################################

#####################################
# 返回users_detail
def Get_user_detail_information(user_id: int)->user_detail_information:
    if not user_id:
        return None
    try:
        with session_scope(commit=False) as session:
            user = get_by_id(int(user_id), session=session)
    except Exception:
        return None

    if not user:
        return None

    # get container bindings for this user
    # compute container ids and counts using centralized helper
    with session_scope(commit=False) as session:
        counts = usercontainer_repo.compute_user_container_counts(user.id, session=session)
    container_ids = counts.get('container_ids', [])
    with session_scope(commit=False) as session:
        long_term_count = long_term_container_repo.count_by_user(user.id, session=session)
    return user_detail_information(
        user_id=user.id,
        username=user.username,
        email=user.email,
        graduation_year=user.graduation_year,
        containers=container_ids,
        amount_of_container=counts.get('total', 0),
        amount_of_functional_container=counts.get('functional', 0),
        amount_of_managed_container=counts.get('managed', 0),
        amount_of_long_term_container=long_term_count,
    )
#####################################

#####################################
# 分页返回users
def List_all_user_bref_information(page_number:int, page_size:int, user_search: str | None = None, viewer_user_id: int | None = None)->list[user_bref_information]:
    try:
        pn = int(page_number) if page_number and int(page_number) > 0 else 1
    except Exception:
        pn = 1
    try:
        ps = int(page_size) if page_size and int(page_size) > 0 else 10
    except Exception:
        ps = 10

    offset = (pn - 1) * ps
    user_search = (user_search or "").strip() or None
    # 资源级集合过滤：无通配（bypass_resource / user:manage）的查看者只看自己 + 被授权管理的学生
    visible_ids = None
    if viewer_user_id is not None:
        from .rbac_service import _has_entity_direct, _has_resource_manage_direct
        if not (_has_entity_direct(viewer_user_id, "bypass_resource") or _has_resource_manage_direct(viewer_user_id, "user")):
            from ..repositories import user_managed_user_repo
            with session_scope(commit=False) as session:
                managed = user_managed_user_repo.list_managed_ids(manager_user_id=viewer_user_id, session=session)
            visible_ids = {int(viewer_user_id)} | managed
    with session_scope(commit=False) as session:
        users = list_users(limit=ps, offset=offset, user_search=user_search, visible_ids=visible_ids, session=session)
    result: list[user_bref_information] = []
    for u in users:
        # Use centralized helper to compute container counts for this user
        with session_scope(commit=False) as session:
            counts = usercontainer_repo.compute_user_container_counts(u.id, session=session)
        container_ids = counts.get('container_ids', [])
        total = counts.get('total', 0)
        functional = counts.get('functional', 0)
        managed = counts.get('managed', 0)

        # Optionally use containers_repo to validate container ids or fetch additional info
        with session_scope(commit=False) as session:
            long_term_count = long_term_container_repo.count_by_user(u.id, session=session)
        result.append(user_bref_information(
            user_id=u.id,
            username=u.username,
            email=u.email,
            graduation_year=u.graduation_year,
            containers=container_ids,
            amount_of_container=total,
            amount_of_functional_container=functional,
            amount_of_managed_container=managed,
            amount_of_long_term_container=long_term_count,
        ))
    return result
#####################################

#####################################
def Update_user(user_id:int,**fields)->User|None:
    # 此方法不能修改 password_hash、email（RBAC 归属走组绑定管理，不走用户字段）

    if 'password_hash' in fields:
        del fields['password_hash']
    if 'email' in fields:
        del fields['email']

    # 毕业年份不允许清空：请求层已把空串归一为 None，这里再拦内部调用传入的
    # None/空串，避免把已保存的年份改成 NULL 或空字符串（列本身保持 NOT NULL）。
    if 'graduation_year' in fields:
        graduation_year = fields['graduation_year']
        if graduation_year is None or (
            isinstance(graduation_year, str) and not graduation_year.strip()
        ):
            del fields['graduation_year']

    # 防御性检查：限制字段长度，防止过长输入导致数据库异常
    if 'username' in fields and fields['username'] and len(fields['username']) > 75:
        raise ValueError(f"username too long (max 75): length={len(fields['username'])}")
    if 'email' in fields and fields['email'] and len(fields['email']) > 115:
        raise ValueError(f"email too long (max 115): length={len(fields['email'])}")

    # disallow non-ASCII characters in any provided string field
    def _is_all_ascii(s: str) -> bool:
        try:
            if s is None:
                return True
            return all(ord(ch) < 128 for ch in s)
        except Exception:
            return False

    # username has stricter validation (letters/digits/underscore)
    import re
    def _is_valid_username(s: str) -> bool:
        try:
            if s is None:
                return False
            return bool(re.match(r'^[A-Za-z0-9_]+$', s))
        except Exception:
            return False

    for k, v in fields.items():
        if k == 'username':
            if not _is_valid_username(v):
                raise ValueError('invalid_username')
            continue
        if isinstance(v, str) and not _is_all_ascii(v):
            raise ValueError('no_none_ascii')

    with session_scope() as session:
        user = update_user(user_id, **fields, session=session)
        return user
#####################################

#####################################
#忘记密码
# 重置为随机密码，明文仅在本次响应中返回（管理员转交本人后应由其改密）
def Reset_password(user_id: int, operator_user_id: int | None = None) -> str | None:
    with session_scope() as session:
        user = get_by_id(user_id, session=session)
        if not user:
            log_failure(operator_user_id=operator_user_id,
                operation=OperationType.RESET_PASSWORD,
                target_type="user",
                target_id=user_id,
                detail={"username": None},
                error_reason="user_not_found",
            )
            return None
        new_password = secrets.token_urlsafe(12)
        try:
            update_user(user_id,password_hash=generate_password_hash(new_password), session=session)
        except Exception as e:
            log_failure(operator_user_id=operator_user_id,
                         operation=OperationType.RESET_PASSWORD, target_type="user", target_id=user_id,
                         detail={"username": user.username}, error_reason=str(e))
            raise
    log_success(operator_user_id=operator_user_id,
                 operation=OperationType.RESET_PASSWORD, target_type="user", target_id=user_id,
                 detail={"username": user.username})
    return new_password
#####################################


ALLOWED_REGISTRATION_EMAIL_DOMAINS = {'bjtu.edu.cn', 'tsinghua.edu.cn', 'bupt.edu.cn', 'mails.tsinghua.edu.cn', 'mail.tsinghua.edu.cn'}


def _get_email_domain(email: str) -> str | None:
    if not email or '@' not in email:
        return None
    return email.rsplit('@', 1)[-1].lower().strip()


def Request_register_code(email: str):
    '''给指定学校邮箱发送注册验证码。'''
    domain = _get_email_domain(email)
    if domain not in ALLOWED_REGISTRATION_EMAIL_DOMAINS:
        return False, 'email_domain_not_allowed'

    code = f'{secrets.randbelow(1000000):06d}'
    expires_at = datetime.utcnow() + timedelta(minutes=3)
    try:
        with session_scope() as session:
            registration_code_repo.create_code(
                email=email,
                school_domain=domain,
                code=code,
                expires_at=expires_at,
                session=session,
            )
    except Exception as exc:
        print(f"Failed to create registration code for {email}: {exc}")
        return False, 'code_creation_failed'
    result = send_mail(
        to=email, subject='伏羲系统注册验证码',
        content=f'你的注册验证码是：{code}\n验证码有效期为3分钟。请勿泄露给他人。',
        detail={"mail_type": "registration_code", "name": email},
    )
    if not result.get('ok'):
        return False, 'mail_send_failed'
    return True, 'code_sent'


class _RegistrationRejected(Exception):
    """注册业务性拒绝：让 session_scope 回滚验证码消费，再由调用方转成既有返回元组。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _conflict_reason_after_rollback(username: str, email: str) -> str | None:
    """唯一约束兜底失败后，在全新只读事务里复核冲突字段，归类为既有 error_reason。"""

    try:
        with session_scope(commit=False) as session:
            return _registration_conflict_reason(session, username=username, email=email)
    except Exception:
        return None


def Register_with_code(username: str, email: str, password: str, graduation_year, registration_code: str):
    '''同一事务提交用户、默认组和验证码消费，失败时保留有效验证码。'''
    if not registration_code:
        return False, 'registration_code_required', None

    domain = _get_email_domain(email)
    if domain not in ALLOWED_REGISTRATION_EMAIL_DOMAINS:
        return False, 'email_domain_not_allowed', None

    # 参数校验前置：非法输入不消费验证码（原实现先消费、后由 Register 拒绝）
    reason = _validate_registration_fields(username, email, password)
    if reason:
        return False, reason, None

    try:
        with session_scope() as session:
            # 消费与建档共用同一 session：以下任何 raise 都会让 session_scope 整体回滚
            if not registration_code_repo.verify_and_consume_code(
                email=email,
                code=registration_code,
                school_domain=domain,
                session=session,
            ):
                raise _RegistrationRejected('registration_code_invalid')

            reason, new_user = _create_user_row(
                session, username=username, email=email, password=password,
                graduation_year=graduation_year,
            )
            if reason:
                raise _RegistrationRejected(reason)
            # 必要身份关联与用户创建、验证码消费同一次提交：绑定失败则整体回滚
            _bind_default_group_in_session(session, new_user.id)
    except _RegistrationRejected as rejected:
        return False, rejected.reason, None
    except IntegrityError as exc:
        # 并发下双方预检都可能通过，users 唯一约束才是最终闸门；消费已随事务回滚。
        fallback = _conflict_reason_after_rollback(username, email)
        if fallback:
            return False, fallback, None
        log_failure(operation=OperationType.REGISTER_USER, target_type="user", target_id=0,
                     detail={"username": username, "email": email}, error_reason=str(exc))
        raise
    except Exception as e:
        log_failure(operation=OperationType.REGISTER_USER, target_type="user", target_id=0,
                     detail={"username": username, "email": email}, error_reason=str(e))
        raise

    log_success(operation=OperationType.REGISTER_USER, target_type="user", target_id=new_user.id,
                 detail={"username": username, "email": email})
    return True, new_user, None


