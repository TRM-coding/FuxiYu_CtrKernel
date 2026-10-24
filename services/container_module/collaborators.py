from __future__ import annotations

from ...constant import OperationType, ROLE
from ...extensions import session_scope
from ...repositories import user_repo, usercontainer_repo
from ...repositories.containers_repo import _binding_role_value
from ...utils import sanitizer as _sanitizer
from ...utils.container_lock import container_role_lock
from ..operation_log_tasks import log_failure, log_success
from .exceptions import NodeServiceError, safe_reason
from . import node_comms
from .lifecycle import _ensure_container_action, _load_container_target
from .node_comms import get_full_url
from .node_comms import _ensure_machine_online_for_operation
from .passwords import generate_container_password, spawn_background
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


def _build_collaborator_payload(
    container_name: str, user_name: str, *, role=None, updated_role=None, password: str | None = None,
) -> dict:
    """组包：三个动作共用一份载荷骨架，按动作附加 role / updated_role / password。纯函数。"""
    config = {"container_name": container_name, "user_name": user_name}
    if role is not None:
        config["role"] = role.value.lower()
    if updated_role is not None:
        config["updated_role"] = updated_role.value.lower()
    if password is not None:
        config["password"] = password
    return {"config": config}


def _request_collaborator_action(host: str, port: int, action: str, payload: dict) -> None:
    """网络出口：POST /{action}（add_collaborator / remove_collaborator / update_role）。

    错误只保留 reason，不把原始请求/响应体拼进异常。
    """
    response = node_comms.send(get_full_url(host, f"/{action}", port), payload)
    if not isinstance(response, dict):
        raise NodeServiceError(f"NODE {action} unexpected response", reason="unexpected_response")
    reason = safe_reason(response.get("error_reason"), {
        "add_collaborator": "add_failed",
        "remove_collaborator": "remove_failed",
        "update_role": "update_failed",
    }[action])
    if response.get("error") or response.get("success") not in (1, True):
        raise NodeServiceError(
            f"NODE {action} failed reason={reason}",
            reason=reason,
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


def _update_collaborator_binding(container_id: int, user_id: int, user_name: str, role: ROLE) -> bool:
    """落绑定：改角色；升为 root 时用户名固定写 "root"（与创建时的约定一致）。"""
    with session_scope() as session:
        return usercontainer_repo.update_binding(
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


def _password_failure_reason(exc: Exception, default: str) -> str:
    return safe_reason(exc, default)


def _run_add_collaborator(
    container_id: int, user_id: int, user_name: str, role: ROLE,
    operator_user_id: int | None, password: str,
) -> None:
    """后台：最小在线复核 → Node add_collaborator(password) → 绑定 + 既有审计。"""

    try:
        container, host, port = _load_container_target(container_id)
        _ensure_container_action(container, "add_collaborator", require_online=True)
    except Exception as exc:
        log_failure(
            operator_user_id=operator_user_id, operation=OperationType.ADD_COLLABORATOR,
            target_type="container", target_id=container_id,
            error_reason=_password_failure_reason(exc, "add_collaborator_failed"),
            detail={"user_id": user_id, "username": user_name, "stage": "guard"},
        )
        return

    try:
        payload = _build_collaborator_payload(
            container.name, user_name, role=role, password=password,
        )
        _request_collaborator_action(host, port, "add_collaborator", payload)
        _add_collaborator_binding(container_id, user_id, user_name, role)
        _audit_collaborator(
            container, user_id, user_name, OperationType.ADD_COLLABORATOR, operator_user_id,
            role=role.value if hasattr(role, "value") else str(role),
        )
    except Exception as exc:
        log_failure(
            operator_user_id=operator_user_id, operation=OperationType.ADD_COLLABORATOR,
            target_type="container", target_id=container_id,
            error_reason=_password_failure_reason(exc, "add_collaborator_failed"),
            detail={"user_id": user_id, "username": user_name, "stage": "node_or_binding"},
        )


def start_add_collaborator(
    container_id: int, user_id: int, role: ROLE, operator_user_id: int | None = None,
) -> dict:
    """受理式新增协作者：返回一次性密码，Node/绑定在后台完成。"""

    container, _host, _port = _load_container_target(container_id)
    _ensure_container_action(container, "add_collaborator", require_online=True)
    user_name, _binding = _load_collaborator_account(user_id, container_id)
    if role == ROLE.ROOT:
        raise NodeServiceError("root role is not allowed by add_collaborator", reason="invalid_payload")
    password = generate_container_password()
    try:
        spawn_background(
            "container-add-collaborator", _run_add_collaborator,
            container_id, user_id, user_name, role, operator_user_id, password,
        )
    except Exception as exc:
        raise NodeServiceError(
            "add collaborator background task was not started", reason="add_not_accepted",
        ) from exc
    return {"login_name": user_name, "password": password}


def _binding_role(binding: dict) -> str:
    return _binding_role_value(binding).upper()


def get_container_binding_role(container_id: int, user_id: int) -> str | None:
    with session_scope(commit=False) as session:
        binding = usercontainer_repo.get_binding(int(user_id), int(container_id), session=session)
    return _binding_role(binding) if binding else None


def _load_role_target(container_id: int, user_id: int):
    try:
        container, host, port = _load_container_target(container_id)
    except ValueError as exc:
        raise NodeServiceError("container not found", reason="container_not_found") from exc
    _ensure_machine_online_for_operation(container.machine_id, "update_role")
    _ensure_container_action(container, "update_role", require_online=True)
    user_name, binding = _load_collaborator_account(user_id, container_id)
    if not binding:
        raise NodeServiceError("target user is not bound to this container", reason="target_not_bound")
    return container, host, port, user_name, binding


def _role_payload(
    container_name: str, user_name: str, updated_role: ROLE,
    *, password: str | None = None, root_password: str | None = None,
) -> dict:
    config = {
        "container_name": container_name,
        "user_name": user_name,
        "updated_role": updated_role.value.lower(),
    }
    if password is not None:
        config["password"] = password
    if root_password is not None:
        config["root_password"] = root_password
    return {"config": config}


def _perform_role_step(
    container_id: int, user_id: int, user_name: str, updated_role: ROLE,
    operator_user_id: int | None, *, password: str | None = None, root_password: str | None = None,
) -> bool:
    """同步单目标 role primitive；可在后台线程或删除用户内部路径复用。"""

    container = None
    try:
        container, host, port = _load_container_target(container_id)
        _ensure_machine_online_for_operation(container.machine_id, "update_role")
        _ensure_container_action(container, "update_role", require_online=True)
        old_role = get_container_binding_role(container_id, user_id)
        _request_collaborator_action(
            host, port, "update_role",
            _role_payload(
                container.name, user_name, updated_role,
                password=password, root_password=root_password,
            ),
        )
        if not _update_collaborator_binding(container_id, user_id, user_name, updated_role):
            raise NodeServiceError("binding update failed", reason="role_binding_failed")
        log_success(
            operator_user_id=operator_user_id, operation=OperationType.UPDATE_COLLABORATOR_ROLE,
            target_type="container", target_id=container_id,
            detail=_container_log_detail(
                container.name, user_id=user_id, username=user_name,
                old_role=old_role, new_role=updated_role.value,
            ),
        )
        return True
    except Exception as exc:
        log_failure(
            operator_user_id=operator_user_id, operation=OperationType.UPDATE_COLLABORATOR_ROLE,
            target_type="container", target_id=container_id,
            error_reason=_password_failure_reason(exc, "update_role_failed"),
            detail={"user_id": user_id, "username": user_name, "new_role": updated_role.value},
        )
        return False


def _root_owner_names(container_id: int, target_user_id: int) -> list[tuple[int, str]]:
    with session_scope(commit=False) as session:
        bindings = usercontainer_repo.get_container_bindings(container_id, session=session) or []
        owners = []
        for binding in bindings:
            if int(binding["user_id"]) == int(target_user_id):
                continue
            if _binding_role(binding) != ROLE.ROOT.value:
                continue
            user_name = user_repo.get_name_by_id(int(binding["user_id"]), session=session)
            if not user_name:
                raise NodeServiceError(
                    "existing root user has no usable system username",
                    reason="invalid_root_owner_account",
                )
            try:
                _sanitizer.validate_username(user_name)
            except Exception as exc:
                raise NodeServiceError(
                    "existing root system username is unsafe",
                    reason="invalid_root_owner_account",
                ) from exc
            if user_name == "root" or user_name.startswith("-"):
                raise NodeServiceError(
                    "existing root user cannot use reserved or option-like username",
                    reason="invalid_root_owner_account",
                )
            owners.append((int(binding["user_id"]), user_name))
    return owners


def _root_target_name_invalid(user_name: str | None) -> bool:
    return not user_name or user_name == "root" or str(user_name).startswith("-")


def _ensure_root_target_name(user_name: str) -> None:
    if _root_target_name_invalid(user_name):
        raise NodeServiceError(
            "target system username is not usable for root role",
            reason="invalid_target_account",
        )


def _read_handover_state(container_id: int, target_user_id: int):
    """独立只读 session 读取当前 ROOT 身份与目标角色，不参与任何长事务。"""

    with session_scope(commit=False) as session:
        bindings = usercontainer_repo.get_container_bindings(container_id, session=session) or []
        roots = []
        for binding in bindings:
            if _binding_role(binding) != ROLE.ROOT.value:
                continue
            user_id = int(binding["user_id"])
            roots.append((user_id, user_repo.get_name_by_id(user_id, session=session)))
        target_binding = usercontainer_repo.get_binding(
            int(target_user_id), int(container_id), session=session,
        )
        target_role = _binding_role(target_binding) if target_binding else None
        target_name = user_repo.get_name_by_id(int(target_user_id), session=session)
    return roots, target_role, target_name


def _log_root_handover_stale(
    container_id: int, target_user_id: int, operator_user_id: int | None, *,
    expected_root_ids: list[int], current_root_ids: list[int] | None,
    expected_target_role: str, current_target_role: str | None,
) -> None:
    """固定 stale 失败：只含角色/ID 快照，不含密码。"""

    log_failure(
        operator_user_id=operator_user_id,
        operation=OperationType.UPDATE_COLLABORATOR_ROLE,
        target_type="container",
        target_id=container_id,
        error_reason="root_handover_stale",
        detail={
            "user_id": target_user_id,
            "expected_root_ids": list(expected_root_ids),
            "current_root_ids": current_root_ids,
            "expected_target_role": expected_target_role,
            "current_target_role": current_target_role,
        },
    )


def _run_root_handover(
    container_id: int, target_user_id: int, target_user_name: str,
    old_roots: list[tuple[int, str, str]], root_password: str,
    operator_user_id: int | None, expected_root_ids: list[int], expected_target_role: str,
) -> None:
    # 同一容器整个交接 job 持同一把同机锁；每步仍独立 repo/session 提交。
    with container_role_lock(container_id):
        try:
            current_roots, current_target_role, current_target_name = _read_handover_state(
                container_id, target_user_id,
            )
            expected_root_names = {user_id: name for user_id, name, _ in old_roots}
            if expected_target_role == ROLE.ROOT.value:
                expected_root_names[int(target_user_id)] = target_user_name
            current_root_names = {user_id: name for user_id, name in current_roots}
            if (
                sorted(current_root_names) != sorted(expected_root_names)
                or current_root_names != expected_root_names
                or current_target_role != expected_target_role
                or current_target_name != target_user_name
            ):
                _log_root_handover_stale(
                    container_id, target_user_id, operator_user_id,
                    expected_root_ids=expected_root_ids,
                    current_root_ids=sorted(current_root_names),
                    expected_target_role=expected_target_role,
                    current_target_role=current_target_role,
                )
                return

            # 先降级全部旧 ROOT；任一步失败立即返回，绝不继续提拔目标。
            for old_user_id, old_user_name, old_password in old_roots:
                if not _perform_role_step(
                    container_id, old_user_id, old_user_name, ROLE.ADMIN,
                    operator_user_id, password=old_password,
                ):
                    return
            _perform_role_step(
                container_id, target_user_id, target_user_name, ROLE.ROOT,
                operator_user_id, root_password=root_password,
            )
        except Exception as exc:
            log_failure(
                operator_user_id=operator_user_id,
                operation=OperationType.UPDATE_COLLABORATOR_ROLE,
                target_type="container",
                target_id=container_id,
                error_reason=_password_failure_reason(exc, "root_handover_failed"),
                detail={"user_id": target_user_id, "stage": "handover"},
            )


def start_root_handover(
    container_id: int, user_id: int, operator_user_id: int | None = None,
) -> dict:
    """外部 ROOT 请求唯一入口：旧 ROOT 逐个降 ADMIN，成功后再升目标。"""

    container, _host, _port, user_name, binding = _load_role_target(container_id, user_id)
    _ensure_root_target_name(user_name)
    target_role = _binding_role(binding)
    old_owner_names = _root_owner_names(container.id, user_id)
    expected_root_ids = [old_user_id for old_user_id, _ in old_owner_names]
    if target_role == ROLE.ROOT.value:
        expected_root_ids.append(int(user_id))
    expected_root_ids = sorted(expected_root_ids)
    root_password = generate_container_password()
    old_roots = []
    credentials = [{"login_name": "root", "password": root_password}]
    for old_user_id, old_user_name in old_owner_names:
        old_password = generate_container_password()
        old_roots.append((old_user_id, old_user_name, old_password))
        credentials.append({"login_name": old_user_name, "password": old_password})
    try:
        spawn_background(
            "container-root-handover", _run_root_handover,
            container.id, int(user_id), user_name, old_roots, root_password, operator_user_id,
            expected_root_ids, target_role,
        )
    except Exception as exc:
        raise NodeServiceError("root handover task was not started", reason="role_change_not_accepted") from exc
    return {"credentials": credentials}


def _run_root_demotion(
    container_id: int, user_id: int, user_name: str, operator_user_id: int | None, password: str,
) -> None:
    with container_role_lock(container_id):
        _perform_role_step(
            container_id, user_id, user_name, ROLE.ADMIN, operator_user_id, password=password,
        )


def start_root_demotion(
    container_id: int, user_id: int, operator_user_id: int | None = None,
) -> dict:
    container, _host, _port, user_name, binding = _load_role_target(container_id, user_id)
    if _binding_role(binding) != ROLE.ROOT.value:
        raise NodeServiceError("target is not a root binding", reason="invalid_target_account")
    password = generate_container_password()
    try:
        spawn_background(
            "container-root-demote", _run_root_demotion,
            container.id, int(user_id), user_name, operator_user_id, password,
        )
    except Exception as exc:
        raise NodeServiceError("root demotion task was not started", reason="role_change_not_accepted") from exc
    return {"credentials": [{"login_name": user_name, "password": password}]}


def promote_root_sync(
    container_id: int, user_id: int, operator_user_id: int | None = None,
) -> bool:
    """删除用户内部路径：单目标同步提升，不使用 Web 交接编排。"""

    with container_role_lock(container_id):
        _container, _host, _port, user_name, _binding = _load_role_target(container_id, user_id)
        if _root_target_name_invalid(user_name):
            return False
        root_password = generate_container_password()
        return _perform_role_step(
            container_id, int(user_id), user_name, ROLE.ROOT,
            operator_user_id, root_password=root_password,
        )
