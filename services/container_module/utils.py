####################################################
# 辅助工具

import re
import logging
from datetime import datetime, timedelta

from ...extensions import session_scope
from ...repositories import containers_repo, long_term_container_repo, usercontainer_repo
from ...repositories.containers_repo import _root_user_ids_from_bindings

logger = logging.getLogger(__name__)

_MONTH_ABBR_TO_NUM = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_last_ssh_time(raw: str | None) -> datetime | None:
    """
    尝试把 Node 返回的 last ssh 时间解析为 datetime。
    支持：
    - ISO/常见 datetime 字符串
    - syslog 风格：`Mar 20 12:34:56 ...`
    - `last` 输出中的日期片段：`Fri Mar 20 12:34 ...`
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # 1) 直接尝试 fromisoformat / 通用格式
    try:
        v = s.replace("Z", "+00:00")
        return datetime.fromisoformat(v)
    except Exception:
        pass

    # 2) 提取 "Mon DD HH:MM[:SS]" 片段（无年份时使用当前年）
    m = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}:\d{2}(?::\d{2})?)\b", s)
    if not m:
        return None
    mon = _MONTH_ABBR_TO_NUM.get(m.group(1))
    if not mon:
        return None
    day = int(m.group(2))
    hhmmss = m.group(3)
    parts = hhmmss.split(":")
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(parts[2]) if len(parts) > 2 else 0
    now = datetime.utcnow()
    try:
        return datetime(now.year, mon, day, hour, minute, second)
    except Exception:
        return None


def build_cleanup_info(last_ssh_login_time: str | None, cleanup_after_days: int) -> dict:
    """
    基于上次 SSH 登录时间计算清理时间信息（仅计算，不执行清理）。
    """
    # logger.debug("DEBUG: build_cleanup_info called with last_ssh_login_time='%s' and cleanup_after_days=%s", last_ssh_login_time, cleanup_after_days)
    if cleanup_after_days <= 0:
        cleanup_after_days = 1

    last_dt = _parse_last_ssh_time(last_ssh_login_time)
    if last_dt is None:
        return {
            "cleanup_after_days": cleanup_after_days,
            "cleanup_at": None,
            "seconds_until_cleanup": None,
            "cleanup_status": "unknown",
        }

    cleanup_at = last_dt + timedelta(days=cleanup_after_days)
    seconds_left = int((cleanup_at - datetime.utcnow()).total_seconds())
    if seconds_left <= 0:
        status = "due"
        seconds_left = 0
    else:
        status = "countdown"

    return {
        "cleanup_after_days": cleanup_after_days,
        "cleanup_at": cleanup_at.isoformat(),
        "seconds_until_cleanup": seconds_left,
        "cleanup_status": status,
    }


def select_gpu_allowance(machine, count: int) -> list[int]:
    """allow_list 内轮转选卡。"""

    allow = machine.gpu_allow_list or []
    if not allow:
        allow = list(range(machine.gpu_number or 0))
    allow = [int(x) for x in allow]
    if count <= 0 or not allow:
        return []
    usage = {g: 0 for g in allow}
    try:
        with session_scope(commit=False) as session:
            existing = containers_repo.list_containers(
                limit=1000000, offset=0, machine_id=machine.id, session=session
            )
        for c in existing:
            for g in (c.gpu_chosen_list or []):
                try:
                    g = int(g)
                except (TypeError, ValueError):
                    continue
                if g in usage:
                    usage[g] += 1
    except Exception:
        pass
    return sorted(allow, key=lambda g: (usage.get(g, 0), g))[:count]


def build_long_term_container_state(container_id: int, bindings: list | None = None) -> dict:
    if bindings is None:
        with session_scope(commit=False) as session:
            bindings = usercontainer_repo.get_container_bindings(container_id, session=session) or []
    with session_scope(commit=False) as session:
        is_long_term = long_term_container_repo.is_long_term(container_id, session=session)
    user_ids = _root_user_ids_from_bindings(bindings)
    remaining_by_user = {}
    with session_scope(commit=False) as session:
        for uid in user_ids:
            remaining_by_user[uid] = long_term_container_repo.get_long_term_container_remaining(uid, session=session)
    blocked_user_ids = [] if is_long_term else [
        uid for uid, remaining in remaining_by_user.items() if remaining <= 0
    ]
    return {
        "is_long_term": is_long_term,
        "long_term_container_can_enable": len(blocked_user_ids) == 0,
        "long_term_container_blocked_user_ids": blocked_user_ids,
        "long_term_container_remaining_by_user": remaining_by_user,
    }


def container_image_dockerfile(container) -> str | None:
    """按平台 image tag 反查镜像模板，render 完整 Dockerfile。"""

    if not getattr(container, "image", None):
        return None
    m = re.match(r"^fuxi/image-(\d+):", container.image)
    if not m:
        return None
    try:
        from ...repositories import image_repo
        from ..image_tasks import render_final_dockerfile
        from .. import settings_tasks

        with session_scope(commit=False) as session:
            image = image_repo.get_by_id(int(m.group(1)), session=session)
        if image is None:
            return None
        platform_injection = settings_tasks.get_image_platform_injection_content()
        return render_final_dockerfile(
            base_image=image.base_image,
            platform_injection=platform_injection,
            dockerfile_body=image.dockerfile_body,
        )
    except Exception as e:
        logger.warning("container image dockerfile render failed: %s", e)
        return None


def derive_allocated_limits(container, machine) -> dict:
    """机器上限 vs 容器申请的展示派生值；不改容器 DB。"""

    alloc = {
        "alloc_cpu_number": getattr(container, "cpu_number", 0) or 0,
        "alloc_memory_gb": getattr(container, "memory_gb", 0) or 0,
        "alloc_gpu_number": getattr(container, "gpu_number", 0) or 0,
        "alloc_degraded": False,
    }
    if machine is None:
        return alloc

    max_cpu = machine.max_cpu_core_number or 0
    max_memory = machine.max_memory_gb or 0
    allow = machine.gpu_allow_list or []
    max_gpu = len(allow) or (getattr(machine, "gpu_number", 0) or 0)

    if max_cpu > 0 and alloc["alloc_cpu_number"] > max_cpu:
        alloc["alloc_cpu_number"] = max_cpu
        alloc["alloc_degraded"] = True
    if max_memory > 0 and alloc["alloc_memory_gb"] > max_memory:
        alloc["alloc_memory_gb"] = max_memory
        alloc["alloc_degraded"] = True
    if max_gpu > 0 and alloc["alloc_gpu_number"] > max_gpu:
        alloc["alloc_gpu_number"] = max_gpu
        alloc["alloc_degraded"] = True

    chosen = getattr(container, "gpu_chosen_list", None) or []
    if allow:
        allowed = set()
        for item in allow:
            try:
                allowed.add(int(item))
            except (TypeError, ValueError):
                continue
        chosen_set = set()
        for item in chosen:
            try:
                chosen_set.add(int(item))
            except (TypeError, ValueError):
                continue
        if chosen_set - allowed:
            alloc["alloc_degraded"] = True
        alloc["alloc_gpu_number"] = len(chosen_set & allowed)
    return alloc
