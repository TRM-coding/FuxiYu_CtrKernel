# services/rbac_service.py
"""RBAC 两层模型 · service 层（判断逻辑与框架无关，FastAPI Depends 只做挂载）。

第一层 权限组判别（方法级）：user ─ auth_group ─ auth_entity(code)
第二层 资源组判别（资源级）：user-m（machine_permissions）/ user-c（user_container）/ user-i（user_images）

权限判定只认组绑定（auth_group_entities），历史 user.permission 单字段已清退（2026-09）。
"""
import logging
import re

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
    # rbac
    ("rbac:manage", "权限矩阵管理"),
    # 通配（显式权限点，不依赖任何组存在；operator 组 = 全部 entity，自动包含）
    ("bypass_resource", "资源判定通配：对所有资源放行"),
    ("bypass_auth_entity", "实体权限通配：对非资源通配权限点放行"), # 不包括bypass_resource
]

# 预设组：user（基础使用）/ operator（通配）
_USER_DEFAULTS = {"machine:view", "container:create", "container:operation", "container:view", "image:view"}
_GROUP_DEFS = {
    "user": ("基础用户组：查看机器 + 容器操作 + 查看镜像", _USER_DEFAULTS),
    "operator": ("运维组：通配权限", {"bypass_resource", "bypass_auth_entity"}),
}

_OPERATOR_LOCKED_ENTITIES = {"bypass_resource", "bypass_auth_entity"}
_GROUP_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{1,63}$")


def _manage_entity_for(entity_code: str) -> str | None:
    """返回实体权限所属域的 manage 权限；bypass 与 manage 自身不派生。"""
    normalized = str(entity_code or "").strip()
    if not normalized or normalized.startswith("bypass_") or ":" not in normalized:
        return None
    domain, action = normalized.split(":", 1)
    if action == "manage":
        return None
    manage_code = f"{domain}:manage"
    valid_codes = {code for code, _ in AUTH_ENTITIES}
    return manage_code if manage_code in valid_codes else None


# ── seed（幂等；create_app 建表后调用一次） ─────────────────────────

def bind_user_default_group(user_id: int) -> None:
    """建号默认组绑定：普通注册用户一律进 user 组（operator 建号由 seed 显式绑 operator 组）。"""
    try:
        with session_scope() as session:
            group = auth_repo.get_group("user", session=session)
            if group is not None:
                auth_repo.ensure_user_group(user_id, group.id, session=session)
    except Exception as e:
        logger.warning("bind_user_default_group failed: %s", e)


def get_user_group_ids(user_id: int) -> list[int]:
    """用户当前绑定的权限组 id 列表。"""
    with session_scope(commit=False) as session:
        return auth_repo.list_user_group_ids(user_id, session=session)


def set_user_groups(user_id: int, group_ids: list[int], operator_user_id: int | None = None) -> list[int]:
    """整组替换用户绑定的权限组（set 语义）；生效权限 = 所绑各组 entities 并集。

    ValueError: user_not_found / unknown_group:<ids> / cannot_remove_own_manage
    （护栏：operator 不能把自己移出所有持有 rbac:manage 的组，防止自锁死。）
    """
    user_id = int(user_id)
    wanted = sorted({int(g) for g in (group_ids or [])})

    with session_scope(commit=False) as session:
        from ..repositories import user_repo

        if user_repo.get_by_id(user_id, session=session) is None:
            raise ValueError("user_not_found")
        known_ids = {g.id for g in auth_repo.list_groups(session=session)}
        unknown = [gid for gid in wanted if gid not in known_ids]
        if unknown:
            raise ValueError(f"unknown_group:{','.join(map(str, unknown))}")
        group_entity_codes = auth_repo.list_group_entity_codes(session=session)

    if operator_user_id is not None and int(operator_user_id) == user_id:
        holds_manage = any("rbac:manage" in group_entity_codes.get(gid, set()) for gid in wanted)
        if not holds_manage:
            raise ValueError("cannot_remove_own_manage")

    with session_scope() as session:
        auth_repo.replace_user_groups(user_id, wanted, session=session)
    return wanted


def seed_rbac_defaults() -> None:
    """幂等 seed：auth_entity 全量 + 预设组（user/operator）+ 存量用户过渡映射。

    新 entity/组通过新增常量后再调本函数补录（不覆盖已有行）；
    常量是权威：代码已从 AUTH_ENTITIES 移除的历史实体在此清退（DB 与常量收敛，
    避免 matrix 读 DB / 建组校验读常量两套分叉）。db 访问收敛在 auth_repo。
    """
    with session_scope() as session:
        groups = {}
        for gname, (desc, codes) in _GROUP_DEFS.items():
            g = auth_repo.ensure_group(gname, desc, session=session)
            groups[gname] = g
            for code in codes:
                auth_repo.ensure_group_entity(g.id, code, session=session)
        pruned = auth_repo.prune_group_entity_codes({code for code, _ in AUTH_ENTITIES}, session=session)
    if pruned:
        logger.warning("rbac seed pruned stale group bindings: %s", pruned)
    logger.info("rbac seed done: %d entities, %d groups", len(AUTH_ENTITIES), len(groups))


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
    return [code for code, _ in AUTH_ENTITIES if user_has_entity(user_id, code)]


def list_rbac_matrix() -> dict:
    """返回权限组 × 权限点矩阵，供管理页面展示。

    权限点枚举直接来自 AUTH_ENTITIES 常量（不再落库）；id 用序数占位
    （稳定顺序 = 常量声明顺序），前端以 code 为键。
    """

    entity_order = {code: index for index, (code, _) in enumerate(AUTH_ENTITIES)}
    with session_scope(commit=False) as session:
        groups = auth_repo.list_groups(session=session)
        group_entities = auth_repo.list_group_entity_codes(session=session)

    entities_data = [
        {
            "id": index + 1,
            "code": code,
            "name": name,
            "description": None,
        }
        for index, (code, name) in enumerate(AUTH_ENTITIES)
    ]
    groups_data = []
    for group in groups:
        codes = sorted(group_entities.get(group.id, set()), key=lambda code: (entity_order.get(code, 9999), code))
        groups_data.append(
            {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "entity_codes": codes,
                "locked_entity_codes": sorted(_OPERATOR_LOCKED_ENTITIES) if group.name == "operator" else [],
            }
        )
    return {"entities": entities_data, "groups": groups_data}


def _invalid(reason: str, why: str) -> ValueError:
    """带诊断上下文的校验错误：reason 保持稳定（api 映射用），why 解释差在哪。"""
    err = ValueError(reason)
    err.detail = why
    return err


def update_group_entities(group_id: int, entity_codes: list[str]) -> dict:
    """替换某个权限组持有的权限点。"""

    requested = {str(code).strip() for code in entity_codes if str(code).strip()}
    valid_codes = {code for code, _ in AUTH_ENTITIES}
    unknown = sorted(requested - valid_codes)
    if unknown:
        raise _invalid(
            f"unknown_auth_entities:{','.join(unknown)}",
            f"unknown entity codes: {unknown} (valid={len(valid_codes)})",
        )

    entity_order = {code: index for index, (code, _) in enumerate(AUTH_ENTITIES)}
    with session_scope() as session:
        group = auth_repo.get_group_by_id(group_id, session=session)
        if group is None:
            raise _invalid("group_not_found", f"rbac group id={group_id} not found")
        if group.name == "operator":
            requested.update(_OPERATOR_LOCKED_ENTITIES)
        auth_repo.replace_group_entities(group.id, requested, session=session)
        session.flush()
        group_entities = auth_repo.list_group_entity_codes(session=session).get(group.id, set())

    return {
        "id": group_id,
        "name": group.name,
        "description": group.description,
        "entity_codes": sorted(group_entities, key=lambda code: (entity_order.get(code, 9999), code)),
        "locked_entity_codes": sorted(_OPERATOR_LOCKED_ENTITIES) if group.name == "operator" else [],
    }


def create_group(name: str, description: str | None, entity_codes: list[str]) -> dict:
    """创建权限组，并写入初始权限点集合。"""

    group_name = str(name or "").strip()
    if not _GROUP_NAME_RE.match(group_name):
        raise _invalid(
            "invalid_group_name",
            f"name={group_name!r} 不满足组名规则：英文字母开头，2-64 位 [A-Za-z0-9_-]（长度 {len(group_name)}）",
        )

    requested = {str(code).strip() for code in entity_codes if str(code).strip()}
    valid_codes = {code for code, _ in AUTH_ENTITIES}
    unknown = sorted(requested - valid_codes)
    if unknown:
        raise _invalid(
            f"unknown_auth_entities:{','.join(unknown)}",
            f"unknown entity codes: {unknown} (valid={len(valid_codes)})",
        )

    entity_order = {code: index for index, (code, _) in enumerate(AUTH_ENTITIES)}
    with session_scope() as session:
        if auth_repo.get_group(group_name, session=session) is not None:
            raise _invalid("group_exists", f"name={group_name!r} already exists")
        group = auth_repo.create_group(group_name, str(description or "").strip(), session=session)
        auth_repo.replace_group_entities(group.id, requested, session=session)
        group_entities = auth_repo.list_group_entity_codes(session=session).get(group.id, set())
        result = {
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "entity_codes": sorted(group_entities, key=lambda code: (entity_order.get(code, 9999), code)),
            "locked_entity_codes": [],
        }
    return result


def user_has_entity(user_id: int, entity_code: str) -> bool:
    """用户是否持有方法级权限点（含 bypass_auth_entity 通配）。

    未加入任何组的用户按默认 user 组兜底（注册/建号流程的组绑定后续补；
    显式加入组后以显式组为准）。db 访问收敛在 auth_repo。
    """
    try:
        normalized_code = str(entity_code or "").strip()
        # 0) 实体通配：持有 bypass_auth_entity → 对非资源通配权限点放行（不依赖任何组存在）
        if normalized_code != "bypass_resource" and _has_entity_direct(user_id, "bypass_auth_entity"):
            return True
        with session_scope(commit=False) as session:
            # 1) 显式组
            if auth_repo.user_has_entity(user_id, normalized_code, session=session):
                return True

            # 2) 同域 manage 高阶拥有：{type}:manage → {type}:*
            manage_code = _manage_entity_for(normalized_code)
            if manage_code and auth_repo.user_has_entity(user_id, manage_code, session=session):
                return True

            # 3) 默认 user 组兜底：无任何组映射的用户
            if not auth_repo.user_has_any_group(user_id, session=session):
                default = auth_repo.get_group("user", session=session)
                if default is not None:
                    if auth_repo.group_has_entity(default.id, normalized_code, session=session):
                        return True
                    if manage_code and auth_repo.group_has_entity(default.id, manage_code, session=session):
                        return True
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
