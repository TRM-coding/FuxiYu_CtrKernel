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


def _container_log_detail(container_name: str | None, **extra) -> dict:
    """op-log detail 标准骨架：name/container_name/original_container_name 三键统一。"""

    name = container_name or "?"
    detail = {
        "name": name,
        "container_name": name,
        "original_container_name": name,
    }
    detail.update(extra)
    return detail


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


def build_cleanup_info(
    last_ssh_login_time: str | None,
    cleanup_after_days: int,
    deferral_seconds: int = 0,
    unavailable_since: datetime | None = None,
) -> dict:
    """
    基于上次 SSH 登录时间计算清理时间信息（仅计算，不执行清理）。

    deferral_seconds：机器不可用窗口**已结算**的累计顺延（Ctrl 自有列维护，不随 Node 帧回写）。
    有效最后登录 = 真实 last_ssh + deferral——宕机/维护期用户无法交互，不计入责任，
    到期时刻（cleanup_at / 倒计时）相应顺延；展示与执行使用同一口径。

    unavailable_since：**正在进行**的不可用窗口起点（unavailable_since IS NOT NULL 即窗口开着）。
    顺延只在窗口关闭时一次性结算，所以窗口期若只看 deferral_seconds，倒计时会照走、
    甚至走到"到期"——而它其实会在窗口关闭时被整体拨回。把窗口已持续的时长折进来，
    "不可用期间时钟不走"才在**读的这一刻**也成立，而不只是终态成立。

    这样做的收益是**读数准确**，不是加一道拦截：提醒邮件与界面倒计时都读同一份 info，
    算对了它们自然不会再提前报"即将清理"。窗口继续开着时，每次现算得到的都是
    「若此刻恢复可用」的正确值——这正是"时钟暂停"应有的表现。
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

    effective_deferral = int(deferral_seconds or 0)
    if unavailable_since is not None:
        # 窗口已持续的时长。负值只在时钟回拨时出现，夹到 0 以免倒扣。
        elapsed = int((datetime.utcnow() - unavailable_since).total_seconds())
        effective_deferral += max(0, elapsed)
    if effective_deferral:
        last_dt = last_dt + timedelta(seconds=effective_deferral)
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


def is_version_behind(image_version_at, template_updated_at) -> bool:
    """容器是否落后于模板：其构建版本戳早于模板的当前版本。

    **刻意不看容器的 `created_at`**：恢复路径不更新创建时间，用它会把一个刚按最新模板
    重建的容器误判为"落后"，从而展示错误的运行基底。

    展示出口与恢复判定共用这一个比较——两处对"是否落后"必须是同一口径，否则会出现
    「详情页说它是最新的、恢复却按落后的分支问你」这种自相矛盾。
    """
    if template_updated_at is None:
        return False
    if image_version_at is None:
        # 没有留痕 = 无法证明它是当前版本 → 按落后处理（展示快照更诚实）。
        return True
    return image_version_at < template_updated_at


def container_dockerfile_parts(container):
    """读容器行上的配方留痕，补上当下的平台注入，凑成一份完整的渲染输入；没有留痕返回 None。

    容器行上只有**模板侧的两项**（FROM 与业务片段）；平台注入不落库，这里现取当下的
    系统设置——它不是用户的内容而是平台设施，容器该带的是现在这一版，不是当年那版。

    判"有没有留痕"看 `base_image`：FROM 是 Dockerfile 的结构必需项，业务片段可以合法为空
    （内置模板就是空的）——所以不能拿"整段文本非空"当判据。

    **不回落模板。** 恢复链路靠这个 None 走"没有配方可还原"的拒绝分支；回落等于把当前
    模板冒充成该容器跑过的那份。展示出口要的回落是另一回事，见 container_image_dockerfile。
    """
    base_image = getattr(container, "base_image", None)
    if not base_image:
        return None
    from .. import settings_tasks
    from ..image_tasks import DockerfileParts

    return DockerfileParts(
        base_image=base_image,
        platform_injection=settings_tasks.get_image_platform_injection_content() or "",
        dockerfile_body=getattr(container, "dockerfile_body", None),
    )


def container_image_dockerfile(container) -> str | None:
    """容器运行基底的**唯一展示出口**（design D8）。

    **一律展示容器侧的留痕**——该容器实际使用的那份配方，现渲染成文本。

    为什么不做"没落后就展示当前模板渲染"：平台注入是**独立于 `images.updated_at`** 的
    系统设置。注入变了而模板版本没变时，判据会说"不落后"，于是展示的是**新注入**，
    而容器跑的是**旧注入**——展示就此撒谎。留痕是容器实际跑的那一份，不存在这个问题，
    规则也因此从三支收成一支。

    无归属与存量容器（本次变更上线前的，没有留痕）回落为当前模板渲染——那是有损的：
    它展示模板**现在**的样子。可接受的退化，只影响这批容器。

    取模板走 `get_by_id` 原语，**不受停用过滤影响**：停用只挡"用于新建"，不该让历史
    容器的运行基底变空——那会把停用变成一个破坏历史可读性的操作。
    """
    parts = container_dockerfile_parts(container)
    if parts is not None:
        return parts.render()
    image_id = getattr(container, "image_id", None)
    if not image_id:
        return None
    return _render_template_dockerfile(image_id)


def _render_template_dockerfile(image_id: int) -> str | None:
    try:
        from ..image_tasks import resolve_image_build

        build = resolve_image_build(int(image_id))
        return None if build is None else build.dockerfile_parts.render()
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
