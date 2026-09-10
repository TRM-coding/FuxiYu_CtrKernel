from __future__ import annotations

import logging
from datetime import datetime

from ...extensions import session_scope
from ...repositories import (
    container_disk_freeze_state_repo,
    container_ssh_login_repo,
    containers_repo,
    long_term_container_repo,
    machine_repo,
    user_repo,
    usercontainer_repo,
)
from .. import settings_tasks
from .utils import build_cleanup_info

logger = logging.getLogger(__name__)

####################################################
# 查询工具族（只读）
# 门户 get_container_detail_information / list_all_container_bref_information /
# get_container_disk_usage / get_container_last_ssh_login_time 在 services/container_tasks.py。
# 约定：全部只读 Ctrl 库中 WSS 推送落库的快照，不打 Node；
# 读失败的处理分两档——详情/列表页用 ignore_errors=True 降级为 None，硬查询（详情主记录）直接抛。
####################################################

def _parse_query_container_id(container_id, query: str) -> int | None:
    """id 归一化：非法返回 None（调用方返回空结果，不抛）；query 只用于日志定位。"""
    try:
        return int(container_id)
    except Exception:
        logger.warning("Invalid container id for %s query: %s", query, container_id)
        return None


def _read_last_ssh_record(container_id: int):
    """读 SSH 登录记录（WSS 落库快照）；读失败返回 None。"""
    try:
        with session_scope(commit=False) as session:
            return container_ssh_login_repo.get_by_container(container_id, session=session)
    except Exception:
        logger.exception("Error querying ssh login record for id=%s", container_id)
        return None


def _read_disk_container(container_id: int):
    """读容器行（磁盘用量查询用）；读失败返回 None。"""
    try:
        with session_scope(commit=False) as session:
            return containers_repo.get_by_id(container_id, session=session)
    except Exception:
        logger.exception("Error querying container info for id=%s", container_id)
        return None


def _load_detail_container(container_id: int):
    """详情主记录：不存在直接 ValueError（详情接口必须 404，不降级）。"""
    with session_scope(commit=False) as session:
        container = containers_repo.get_by_id(container_id, session=session)
    if not container:
        raise ValueError("Container not found")
    return container


def _get_container_bindings(container_id: int) -> list:
    """读容器的全部用户绑定（含角色与容器内用户名）。"""
    with session_scope(commit=False) as session:
        return usercontainer_repo.get_container_bindings(container_id, session=session) or []


def _get_container_machine(machine_id: int):
    """读容器所在机器（取 IP / 上限用）；读失败返回 None。"""
    try:
        with session_scope(commit=False) as session:
            return machine_repo.get_by_id(machine_id, session=session)
    except Exception:
        return None


def _get_container_freeze_state(container_id: int, *, ignore_errors: bool = False) -> dict | None:
    """读磁盘冻结态（首次冻结时间 / 宽限到期 / 已冻结天数 / 升级阈值）。"""
    try:
        with session_scope(commit=False) as session:
            state = container_disk_freeze_state_repo.get(container_id, session=session)
        if state is None:
            return None
        return {
            "is_frozen": True,
            "first_frozen_at": state.first_frozen_at.isoformat() if state.first_frozen_at else None,
            "grace_until": state.grace_until.isoformat() if state.grace_until else None,
            "days_frozen": (datetime.utcnow() - state.first_frozen_at).days if state.first_frozen_at else 0,
            "escalation_days": settings_tasks.get_container_disk_freeze_escalation_days(),
        }
    except Exception as exc:
        if not ignore_errors:
            raise
        logger.warning("failed to read freeze state for container %s: %s", container_id, exc)
        return None


def _get_container_cleanup_state(container, *, ignore_errors: bool = False) -> dict:
    """读清理倒计时：last_ssh + cleanup_after_days + 机器不可用顺延（deferral_seconds）。"""
    try:
        with session_scope(commit=False) as session:
            record = container_ssh_login_repo.get_by_machine_container(
                container.machine_id, container.id, session=session,
            )
    except Exception:
        if not ignore_errors:
            raise
        logger.warning("failed to read ssh login record for container %s", container.id)
        record = None
    last_login = record.last_ssh_login_time if record else None
    return {
        "last_ssh_login_time": last_login,
        **build_cleanup_info(
            last_login, settings_tasks.get_container_cleanup_after_days(),
            (record.deferral_seconds or 0) if record else 0,
        ),
    }


def _get_owner_names(bindings: list) -> list:
    """把绑定里的 user_id 批量换成系统用户名（详情页的 owners 列）。"""
    with session_scope(commit=False) as session:
        return [user_repo.get_name_by_id(binding["user_id"], session=session) for binding in bindings]


def _get_visible_container_ids(viewer_user_id: int | None) -> set[int] | None:
    """列表可见性过滤：返回 None = 不限制（超管 / bypass_resource）；返回集合 = 仅本人绑定。

    无 viewer（内部调用）同样不限制。
    """
    if viewer_user_id is None:
        return None
    from ..rbac_service import _has_entity_direct, _has_resource_manage_direct

    if _has_entity_direct(viewer_user_id, "bypass_resource") or _has_resource_manage_direct(viewer_user_id, "container"):
        return None
    with session_scope(commit=False) as session:
        bindings = usercontainer_repo.get_user_bindings(viewer_user_id, session=session) or []
    return {int(binding["container_id"]) for binding in bindings if binding.get("container_id")}


def _query_container_page(machine_id, user_id, container_search, visible_container_ids, page_number, page_size):
    """列表分页查询：同一组过滤条件跑两次（取当页 + 取总数），保证 total 与页口径一致。"""
    filters = dict(
        machine_id=machine_id, user_id=user_id, container_search=container_search,
        visible_container_ids=visible_container_ids,
    )
    with session_scope(commit=False) as session:
        containers = containers_repo.list_containers(
            limit=page_size, offset=page_number * page_size, **filters, session=session,
        )
        total_count = containers_repo.count_containers(**filters, session=session)
    return containers, total_count


def _get_user_long_term_quota(user_id: int) -> dict:
    """列表尾部附带的长期容器配额（剩余名额 + 全局上限）。"""
    with session_scope(commit=False) as session:
        remaining = long_term_container_repo.get_long_term_container_remaining(user_id, session=session)
    return {
        "long_term_container_remaining": remaining,
        "long_term_container_limit": settings_tasks.get_long_term_container_limit(),
    }
