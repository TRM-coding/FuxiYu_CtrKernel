from __future__ import annotations

from ...constant import ROLE
from ...extensions import session_scope
from ...repositories import user_repo, usercontainer_repo
from ...repositories.containers_repo import _binding_role_value
from ...utils import sanitizer as _sanitizer
from ..operation_log_tasks import log_success
from .exceptions import NodeServiceError, _raise_on_node_error
from . import node_comms
from .node_comms import get_full_url
from .utils import _container_log_detail

####################################################
# 协作者与角色工具族
# 门户 add_collaborator / remove_collaborator / update_role 在 services/container_tasks.py。
# 顺序 = 门户调用顺序：读账号 → 守卫（机器必须在线）→ 组包 → 请求 Node → 落绑定 → 审计。
# 用户名先过 sanitizer：进 Node 前拦住带 shell 元字符的账号名。
####################################################

def _load_collaborator_account(user_id: int, container_id: int):
    """读用户名与现有绑定；用户名不合法（含危险字符）直接 ValueError。"""
    with session_scope(commit=False) as session:
        user_name = user_repo.get_name_by_id(user_id, session=session)
        binding = usercontainer_repo.get_binding(user_id, container_id, session=session)
    try:
        _sanitizer.validate_username(user_name)
    except Exception as exc:
        raise ValueError(f"unsafe user_name: {exc}")
    return user_name, binding


def _is_root_binding(binding) -> bool:
    """该绑定是否为 root：root 不允许被移除（门户据此直接拒绝）。"""
    return bool(binding and _binding_role_value(binding).upper() == ROLE.ROOT.value.upper())


def _build_collaborator_payload(container_name: str, user_name: str, *, role=None, updated_role=None) -> dict:
    """组包：三个动作共用一份载荷骨架，按动作附加 role / updated_role。纯函数。"""
    config = {"container_name": container_name, "user_name": user_name}
    if role is not None:
        config["role"] = role.value
    if updated_role is not None:
        config["updated_role"] = updated_role.value
    return {"config": config}


def _request_collaborator_action(machine_ip: str, action: str, payload: dict) -> None:
    """网络出口：POST /{action}（add_collaborator / remove_collaborator / update_role）。"""
    response = node_comms.send(get_full_url(machine_ip, f"/{action}"), payload)
    _raise_on_node_error(response, action)
    if response.get("success") not in (1, True):
        reason = {
            "add_collaborator": "add_failed",
            "remove_collaborator": "remove_failed",
            "update_role": "update_failed",
        }[action]
        raise NodeServiceError(
            f"NODE {action} returned failure: {response}",
            reason=response.get("error_reason") or reason,
        )


def _add_collaborator_binding(container_id: int, user_id: int, user_name: str, role: ROLE) -> None:
    """落绑定：新增协作者（Node 侧成功后本地才写，保证两边一致）。"""
    with session_scope() as session:
        usercontainer_repo.add_binding(
            user_id=user_id, container_id=container_id, username=user_name,
            public_key=None, role=role, session=session,
        )


def _remove_collaborator_binding(container_id: int, user_id: int) -> None:
    """落绑定：移除协作者绑定。"""
    with session_scope() as session:
        usercontainer_repo.remove_binding(user_id, container_id, session=session)


def _update_collaborator_binding(container_id: int, user_id: int, user_name: str, role: ROLE) -> None:
    """落绑定：改角色；升为 root 时用户名固定写 "root"（与创建时的约定一致）。"""
    with session_scope() as session:
        usercontainer_repo.update_binding(
            user_id, container_id, username="root" if role == ROLE.ROOT else user_name,
            role=role, session=session,
        )


def _collaborator_role_change(old_binding, updated_role) -> dict:
    """改角色时补记新旧角色（进 op-log detail，便于审计对照）。"""
    return {
        "old_role": _binding_role_value(old_binding) if old_binding else None,
        "new_role": updated_role.value if hasattr(updated_role, "value") else str(updated_role),
    }


def _audit_collaborator(container, user_id, user_name, operation, operator_user_id, **detail) -> None:
    """成功审计：三个动作共用（detail 里带 user_id / username，改角色再带 old/new_role）。"""
    log_success(
        operator_user_id=operator_user_id, operation=operation,
        target_type="container", target_id=container.id,
        detail=_container_log_detail(container.name, user_id=user_id, username=user_name, **detail),
    )
