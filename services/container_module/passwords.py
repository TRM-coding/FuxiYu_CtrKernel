"""容器账号密码生成、重置与后台执行工具。

密码只存在于进程内局部变量、后台线程参数与一次性响应中；本模块不提供持久化。
"""

from __future__ import annotations

import logging
import secrets
import threading

from ...constant import OperationType, ROLE
from ...extensions import session_scope
from ...repositories import usercontainer_repo
from ...repositories.containers_repo import _binding_role_value
from ...utils import sanitizer as _sanitizer
from ..operation_log_tasks import log_failure, log_success
from .exceptions import NodeServiceError, safe_reason
from . import node_comms
from .lifecycle import _ensure_container_action, _load_container_target
from .node_comms import get_full_url
from .node_comms import _ensure_machine_online_for_operation
from .utils import _container_log_detail

logger = logging.getLogger(__name__)


def generate_container_password() -> str:
    """生成容器账号密码（128 bit 熵，URL-safe ASCII）。"""

    return secrets.token_urlsafe(16)


def spawn_background(name: str, target, *args) -> threading.Thread:
    """启动 daemon 后台线程；返回线程便于测试 join。"""

    thread = threading.Thread(target=target, args=args, name=name, daemon=True)
    thread.start()
    return thread


def _password_failure_reason(exc: Exception, default: str) -> str:
    """只暴露稳定 reason，绝不把异常文本（可能含 secret）写入审计。"""

    return safe_reason(exc, default)


def _reset_login_name(binding: dict) -> str:
    role = _binding_role_value(binding).upper()
    if role == ROLE.ROOT.value.upper():
        return "root"
    login_name = binding.get("username")
    if not login_name or login_name == "root":
        raise NodeServiceError("target account has no usable login name", reason="invalid_target_account")
    try:
        _sanitizer.validate_username(login_name)
    except Exception as exc:
        raise NodeServiceError("target account login name is unsafe", reason="invalid_target_account") from exc
    return login_name


def _load_reset_target(container_id: int, user_id: int):
    try:
        container, host, port = _load_container_target(container_id)
    except ValueError as exc:
        raise NodeServiceError("container not found", reason="container_not_found") from exc
    with session_scope(commit=False) as session:
        binding = usercontainer_repo.get_binding(int(user_id), int(container_id), session=session)
    if not binding:
        raise NodeServiceError("target user is not bound to this container", reason="target_not_bound")
    login_name = _reset_login_name(binding)
    role = _binding_role_value(binding).upper()
    # 先报机器不可用，再报容器状态；与三层 guard 的既有语义一致。
    _ensure_machine_online_for_operation(container.machine_id, "reset_container_password")
    _ensure_container_action(container, "reset_container_password", require_online=True)
    return container, host, port, login_name, role


def _request_node_reset(host: str, port: int, container_name: str, user_name: str, password: str) -> None:
    response = node_comms.send(
        get_full_url(host, "/reset_container_password", port),
        {"config": {"container_name": container_name, "user_name": user_name, "password": password}},
    )
    if not isinstance(response, dict):
        raise NodeServiceError("NODE reset_container_password unexpected response", reason="unexpected_response")
    reason = safe_reason(response.get("error_reason"), "reset_failed")
    if response.get("error") or response.get("success") not in (1, True):
        raise NodeServiceError(
            f"NODE reset_container_password failed reason={reason}",
            reason=reason,
        )


def _run_reset(
    container_id: int, user_id: int, accepted_login_name: str, accepted_role: str,
    password: str, operator_user_id: int | None,
) -> None:
    try:
        container, host, port = _load_container_target(container_id)
        _ensure_machine_online_for_operation(container.machine_id, "reset_container_password")
        _ensure_container_action(container, "reset_container_password", require_online=True)
        with session_scope(commit=False) as session:
            binding = usercontainer_repo.get_binding(int(user_id), int(container_id), session=session)
        if not binding:
            raise NodeServiceError("target binding disappeared", reason="target_not_bound")
        current_login = _reset_login_name(binding)
        current_role = _binding_role_value(binding).upper()
        if current_login != accepted_login_name or current_role != accepted_role:
            raise NodeServiceError("target binding changed after acceptance", reason="target_changed")
        _request_node_reset(host, port, container.name, current_login, password)
    except Exception as exc:
        log_failure(
            operator_user_id=operator_user_id,
            operation=OperationType.RESET_CONTAINER_PASSWORD,
            target_type="container",
            target_id=container_id,
            error_reason=_password_failure_reason(exc, "reset_failed"),
            detail={"user_id": user_id, "login_name": accepted_login_name},
        )
        return
    log_success(
        operator_user_id=operator_user_id,
        operation=OperationType.RESET_CONTAINER_PASSWORD,
        target_type="container",
        target_id=container_id,
        detail={"user_id": user_id, "login_name": accepted_login_name},
    )


def start_reset_container_password(container_id: int, user_id: int, operator_user_id: int | None = None) -> dict:
    """预检后立即返回随机密码；Node 请求在 daemon 线程执行。"""

    container, host, port, login_name, role = _load_reset_target(container_id, user_id)
    password = generate_container_password()
    try:
        spawn_background(
            "container-password-reset", _run_reset,
            container.id, int(user_id), login_name, role, password, operator_user_id,
        )
    except Exception as exc:
        raise NodeServiceError("reset background task was not started", reason="reset_not_accepted") from exc
    return {"login_name": login_name, "password": password}
