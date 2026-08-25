# services/rbac_service.py
"""RBAC 两层模型 · service 层（判断逻辑与框架无关，FastAPI Depends 只做挂载）。

第一层 权限组判别（方法级）：user ─ auth_group ─ auth_entity
第二层 资源组判别（资源级）：user-m（machine_permissions）/ user-c（user_container）/ user-i（user_images）

过渡兼容：user.permission == OPERATOR 视为拥有全部权限（单字段映射到 operator 组，
正式组挂载后由 seed 的 user_group 替代，判断函数对两者都放行）。
"""
import logging

from ..extensions import session_scope
from ..repositories import auth_repo, machine_permission_repo, usercontainer_repo

logger = logging.getLogger(__name__)

# ── auth_entity 最小集（按现有端点归类；新端点新增一行 + seed 幂等补录） ──
AUTH_ENTITIES: list[tuple[str, str]] = [
    # machine
    ("machine:register", "机器接入（TOFU）"),
    ("machine:manage", "机器管理面 + 机器资源通配"),
    ("machine:view", "机器查看"),
    # container
    ("container:create", "创建容器"),
    ("container:operation", "容器操作（启停删/协作者/暂停）"),
    ("container:manage", "容器管理面 + 容器资源通配"),
    ("container:view", "容器查看"),
    # user（仅资源提权：自己 owner / 被授权管理 / user:manage 通配）
    ("user:manage", "用户管理面 + 用户资源通配"),
    # announcement（发送对象表已有，资源级判定收敛为 view + resource 查询）
    ("announcement:manage", "公告管理"),
    ("announcement:view", "公告查看"),
    # operation_log
    ("operation_log:manage", "操作日志管理"),
    # image（镜像功能落地前预留）
    ("image:edit", "镜像编辑（Dockerfile/脚本）"),
    ("image:manage", "镜像管理面 + 镜像资源通配"),
    ("image:view", "镜像查看"),
    # settings
    ("settings:manage", "系统设置管理"),
    # 通配（显式权限点，不依赖任何组存在；operator 组 = 全部 entity，自动包含）
    ("bypass_resource", "资源判定通配：对所有资源放行"),
    ("bypass_auth_entity", "实体权限通配：对所有权限点放行"), # 不包括bypass_resource
]

# 预设组：user（基础使用）/ operator（通配）
_USER_DEFAULTS = {"machine:view", "container:create", "container:operation", "container:view", "image:view"}
_GROUP_DEFS = {
    "user": ("基础用户组：查看机器 + 容器操作 + 查看镜像", _USER_DEFAULTS),
    "operator": ("运维组：通配权限", {"bypass_resource", "bypass_auth_entity"}),
}


# ── seed（幂等；create_app 建表后调用一次） ─────────────────────────

def bind_user_default_group(user_id: int, permission=None) -> None:
    """建号时按 permission 绑定默认组：operator → operator 组；其余 → user 组。"""
    try:
        with session_scope() as session:
            is_op = (getattr(permission, "value", None) if hasattr(permission, "value") else permission) == "operator"
            group = auth_repo.get_group("operator" if is_op else "user", session=session)
            if group is not None:
                auth_repo.ensure_user_group(user_id, group.id, session=session)
    except Exception as e:
        logger.warning("bind_user_default_group failed: %s", e)


def seed_rbac_defaults() -> None:
    """幂等 seed：auth_entity 全量 + 预设组（user/operator）+ 存量用户过渡映射。

    新 entity/组通过新增常量后再调本函数补录（不覆盖已有行）。
    db 访问收敛在 auth_repo。
    """
    with session_scope() as session:
        created_entities = {}
        for code, name in AUTH_ENTITIES:
            ent = auth_repo.ensure_entity(code, name, session=session)
            created_entities[code] = ent

        groups = {}
        for gname, (desc, codes) in _GROUP_DEFS.items():
            g = auth_repo.ensure_group(gname, desc, session=session)
            groups[gname] = g
            for code in codes:
                auth_repo.ensure_group_entity(g.id, created_entities[code].id, session=session)

        # 存量用户过渡映射：permission=OPERATOR → operator 组；其余 → user 组
        from ..repositories.user_repo import list_all_users
        for u in list_all_users(session=session):
            is_op = (getattr(u.permission, "value", None) if hasattr(u.permission, "value") else u.permission) == "operator"
            auth_repo.ensure_user_group(u.id, groups["operator" if is_op else "user"].id, session=session)
    logger.info("rbac seed done: %d entities, %d groups", len(created_entities), len(groups))


# ── 第一层：方法级判别 ─────────────────────────────────────────

def _has_entity_direct(user_id: int, entity_code: str) -> bool:
    """直接查组-实体关联表（不含通配逻辑），供通配检查使用，避免递归。"""
    try:
        with session_scope(commit=False) as session:
            return auth_repo.user_has_entity(user_id, entity_code, session=session)
    except Exception as e:
        logger.warning("_has_entity_direct check failed: %s", e)
        return False


def list_user_entities(user_id: int) -> list[str]:
    """用户持有的全部权限点（通配用户返回全部；否则逐点判定）。"""
    if _has_entity_direct(user_id, "bypass_auth_entity"):
        return [code for code, _ in AUTH_ENTITIES]
    return [code for code, _ in AUTH_ENTITIES if user_has_entity(user_id, code)]


def user_has_entity(user_id: int, entity_code: str) -> bool:
    """用户是否持有方法级权限点（含 bypass_auth_entity 通配）。

    未加入任何组的用户按默认 user 组兜底（注册/建号流程的组绑定后续补；
    显式加入组后以显式组为准）。db 访问收敛在 auth_repo。
    """
    try:
        # 0) 实体通配：持有 bypass_auth_entity → 对所有权限点放行（不依赖任何组存在）
        if _has_entity_direct(user_id, "bypass_auth_entity"):
            return True
        with session_scope(commit=False) as session:
            # 1) 显式组
            if auth_repo.user_has_entity(user_id, entity_code, session=session):
                return True

            # 2) 默认 user 组兜底：无任何组映射的用户
            if not auth_repo.user_has_any_group(user_id, session=session):
                default = auth_repo.get_group("user", session=session)
                if default is not None:
                    return auth_repo.group_has_entity(default.id, entity_code, session=session)
            return False
    except Exception as e:
        logger.warning("user_has_entity check failed: %s", e)
        return False


# ── 第二层：资源级判别 ─────────────────────────────────────────

_RESOURCE_TYPE_TABLE = {
    "machine": "machine_permissions",
    "container": "user_container",
    "image": "user_images",
}


def _has_resource_manage_direct(user_id: int, resource_type: str) -> bool:
    """用户是否持有指定资源类型的管理实体（{type}:manage → 该类型资源通配）。"""
    base_type = resource_type.split(":", 1)[0]
    return _has_entity_direct(user_id, f"{base_type}:manage")


def user_has_resource(user_id: int, resource_type: str, resource_id: int) -> bool:
    """用户对指定资源是否有访问权（含 operator 过渡兼容）。

    *resource_type*: machine / container / container:<role> / image / user
    - container              → 任意绑定（可见性）
    - container:root         → 角色 ≥ ROOT（仅 ROOT）
    - container:admin        → 角色 ≥ ADMIN（ROOT/ADMIN）
    - container:collaborator → 角色 ≥ COLLABORATOR（任意绑定者）
    （角色层级 ROOT > ADMIN > COLLABORATOR，高角色满足低角色要求；operator 特权由 deps 显式表达）
    """
    try:
        # 0) 资源通配：bypass_resource（全类型）或 {type}:manage（单类型管理面 = 该类型通配）
        if _has_entity_direct(user_id, "bypass_resource") or _has_resource_manage_direct(user_id, resource_type):
            return True
        if resource_type == "machine":
            with session_scope(commit=False) as session:
                user_ids = machine_permission_repo.list_user_ids_by_machine(resource_id, session=session) or []
            return user_id in user_ids
        if resource_type == "container" or resource_type.startswith("container:"):
            with session_scope(commit=False) as session:
                binding = usercontainer_repo.get_binding(
                    user_id=user_id,
                    container_id=resource_id,
                    session=session,
                )
            if binding is None:
                return False
            if resource_type == "container":
                return True
            role_filter = resource_type.split(":", 1)[1].upper()
            role_val = binding.get("role")
            role_val = getattr(role_val, "value", str(role_val)).upper() if role_val else ""
            # 角色层级：ROOT > ADMIN > COLLABORATOR，高角色满足低角色要求（向上兼容）
            rank = {"ROOT": 3, "ADMIN": 2, "COLLABORATOR": 1}
            return rank.get(role_val, 0) >= rank.get(role_filter, 0)
        if resource_type == "image":
            with session_scope(commit=False) as session:
                return auth_repo.user_has_image(user_id, resource_id, session=session)
        if resource_type == "user":
            # 用户资源：自己是天然 owner，或被授权管理（教师/助教 → 学生）
            if user_id == resource_id:
                return True
            from ..repositories import user_managed_user_repo
            with session_scope(commit=False) as session:
                return user_managed_user_repo.is_managed(
                    manager_user_id=user_id,
                    managed_user_id=resource_id,
                    session=session,
                )
        logger.warning("user_has_resource: unknown resource_type %r", resource_type)
        return False
    except Exception as e:
        logger.warning("user_has_resource check failed: %s", e)
        return False
