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
    ("machine:manage", "机器管理（增删改/权限/资源限制）"),
    ("machine:view", "机器查看"),
    # container
    ("container:create", "创建容器"),
    ("container:manage", "容器管理（启停删/协作者/暂停）"),
    ("container:view", "容器查看"),
    # user
    ("user:manage", "用户管理"),
    ("user:view", "用户查看"),
    # announcement
    ("announcement:manage", "公告管理"),
    ("announcement:view", "公告查看"),
    # operation_log
    ("operation_log:view", "操作日志查看"),
    # image（镜像功能落地前预留）
    ("image:edit", "镜像编辑（Dockerfile/脚本）"),
    ("image:view", "镜像查看"),
]

# 预设组：user（基础只读）/ operator（全量）
_VIEW_ONLY = {"machine:view", "container:view", "user:view", "announcement:view",
              "operation_log:view", "image:view"}
_GROUP_DEFS = {
    "user": ("基础用户组：只读 + 查看", _VIEW_ONLY),
    "operator": ("运维组：全部权限", set()),
}


def _is_legacy_operator(user_id: int) -> bool:
    """过渡兼容：单字段 operator 视为全量权限。"""
    try:
        from ..repositories.user_repo import get_by_id as get_user_by_id
        with session_scope(commit=False) as session:
            u = get_user_by_id(user_id, session=session)
            if u is None:
                return False
            perm = getattr(u, "permission", None)
            val = perm.value if hasattr(perm, "value") else str(perm) if perm is not None else ""
            return str(val).lower() == "operator"
    except Exception:
        return False


# ── seed（幂等；create_app 建表后调用一次） ─────────────────────────

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

        # operator 组 = 全部 entity（全量组，随 entity 增长自动补）
        all_codes = {c for c, _ in AUTH_ENTITIES}
        _GROUP_DEFS["operator"] = ("运维组：全部权限", all_codes)

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

def user_has_entity(user_id: int, entity_code: str) -> bool:
    """用户是否持有方法级权限点（含 operator 过渡兼容）。

    未加入任何组的用户按默认 user 组兜底（注册/建号流程的组绑定后续补；
    显式加入组后以显式组为准）。db 访问收敛在 auth_repo。
    """
    if _is_legacy_operator(user_id):
        return True
    try:
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


def user_has_resource(user_id: int, resource_type: str, resource_id: int) -> bool:
    """用户对指定资源是否有访问权（含 operator 过渡兼容）。

    *resource_type*: machine / container / image
    """
    if _is_legacy_operator(user_id):
        return True
    try:
        if resource_type == "machine":
            with session_scope(commit=False) as session:
                user_ids = machine_permission_repo.list_user_ids_by_machine(resource_id, session=session) or []
            return user_id in user_ids
        if resource_type == "container":
            with session_scope(commit=False) as session:
                return usercontainer_repo.get_binding(
                    user_id=user_id,
                    container_id=resource_id,
                    session=session,
                ) is not None
        if resource_type == "image":
            with session_scope(commit=False) as session:
                return auth_repo.user_has_image(user_id, resource_id, session=session)
        logger.warning("user_has_resource: unknown resource_type %r", resource_type)
        return False
    except Exception as e:
        logger.warning("user_has_resource check failed: %s", e)
        return False
