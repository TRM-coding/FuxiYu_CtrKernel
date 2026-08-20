import threading
import time
import logging
from datetime import datetime, timedelta

from ..config import AppConfig
from ..repositories import containers_repo
from ..constant import OperationType
from ..services import container_tasks

logger = logging.getLogger(__name__)
_SCHEDULER_STATE: dict[str, object] = {}


def check_all_containers_disk_usage_once(page_size: int = 200) -> None:
    """遍历容器，基于 DB 已落库的磁盘用量做阈值评估。

    WSS 推送已接管采集（apply_disk_usage_snapshot 落库 disk_* 字段）；
    本调度只读 DB + 评估（阈值/冻结/邮件），不再主动查 Node。
    """
    offset = 0
    while True:
        containers = containers_repo.list_containers(
            limit=page_size,
            offset=offset,
            machine_id=None,
            user_id=None,
        )
        if not containers:
            break

        for c in containers:
            usage = _usage_from_db(c)
            if usage is not None:
                _evaluate_limits(c, usage)

        if len(containers) < page_size:
            break
        offset += page_size


def _usage_from_db(container) -> dict | None:
    """从容器 DB 字段构造 usage dict（WSS apply_disk_usage_snapshot 落库的字段）。

    未采集过（disk_total_bytes 为空）→ None，跳过评估。
    """
    total = getattr(container, 'disk_total_bytes', None)
    if total is None:
        return None
    return {"container": {
        "overlay_rw_bytes": getattr(container, 'disk_overlay_rw_bytes', None),
        "bind_mount_bytes": getattr(container, 'disk_bind_mount_bytes', None),
        "total_bytes": total,
        "bind_mount_path": getattr(container, 'bind_mount_path', None),
    }}


def _evaluate_limits(container, usage: dict) -> None:
    """评估磁盘用量，根据 soft/hard 阈值执行告警/冻结（Phase 3 启用）。"""
    _app = AppConfig
    enabled = bool(getattr(_app, "CONTAINER_DISK_CHECK_ENABLED", False))
    if not enabled:
        return

    container_data = usage.get("container", {})
    total_bytes = container_data.get("total_bytes", 0)
    if total_bytes is None:
        total_bytes = 0

    # 限额：初期均分 machine.disk_size_gb
    try:
        machine = container.machine
        disk_size_gb = getattr(machine, 'disk_size_gb', None) or 0
    except Exception:
        disk_size_gb = 0

    if disk_size_gb <= 0:
        # 无磁盘限额配置，跳过评估
        logger.info("[disk-check] skip container_id=%s: machine disk_size_gb not set", container.id)
        return

    limit_bytes = int(disk_size_gb * 1024**3)
    if limit_bytes <= 0:
        return

    usage_percent = (total_bytes / limit_bytes) * 100

    soft_limit = getattr(_app, "CONTAINER_DISK_SOFT_LIMIT_PERCENT", 80)
    hard_limit = getattr(_app, "CONTAINER_DISK_HARD_LIMIT_PERCENT", 100)

    overlay_rw = container_data.get("overlay_rw_bytes") or 0
    bind_mount = container_data.get("bind_mount_bytes") or 0

    # 持久化磁盘用量到 DB
    try:
        bind_mount_path = container_data.get("bind_mount_path")
        containers_repo.update_container(
            container.id,
            commit=True,
            disk_overlay_rw_bytes=int(overlay_rw),
            disk_bind_mount_bytes=int(bind_mount),
            disk_total_bytes=int(total_bytes),
            disk_limit_bytes=int(limit_bytes),
            disk_checked_at=datetime.utcnow(),
            bind_mount_path=bind_mount_path,
        )
    except Exception as e:
        logger.warning("[disk-check] failed to persist disk usage for container %s: %s", container.id, e)

    log_msg = (
        f"[disk-check] container_id={container.id} name={getattr(container, 'name', '?')} "
        f"total={_fmt_bytes(total_bytes)}/{_fmt_bytes(limit_bytes)} ({usage_percent:.1f}%) "
        f"overlay={_fmt_bytes(overlay_rw)} bind={_fmt_bytes(bind_mount)}"
    )

    response_enabled = getattr(_app, "CONTAINER_DISK_RESPONSE_ENABLED", False)

    # 非持久容器只做检测，不接受容量响应（不 pause / 不发邮件）。
    # 此检查先于全局 CONTAINER_DISK_RESPONSE_ENABLED 判断，
    # 方便在关闭响应的情况下从日志验证行为，无影响上线。
    from ..repositories.long_term_container_repo import is_long_term
    if not is_long_term(container.id):
        logger.info("[disk-check] container %s (%s) is not long-term, skip response",
                    container.id, getattr(container, 'name', '?'))
        response_enabled = False

    # ── 重置检查（所有容器，不区分长期/短期）──
    from ..repositories import container_disk_freeze_state_repo as freeze_state_repo
    reset_pct = getattr(_app, "CONTAINER_DISK_FREEZE_RESET_PERCENT", 95)
    if usage_percent < reset_pct:
        if freeze_state_repo.reset(container.id):
            logger.info("[disk-check] freeze state reset: container %s (%s) usage %.1f%% < %s%%",
                        container.id, getattr(container, 'name', '?'), usage_percent, reset_pct)
            logger.info("[disk-check] OK: %s", log_msg)
            return  # 有冻结记录且容量回落，重置后不进入任何超限判断
        # 无冻结记录 → 继续正常流程（仍可能触发 soft limit）

    if usage_percent >= hard_limit:
        logger.error("[disk-check] HARD LIMIT exceeded: %s", log_msg)
        if response_enabled:
            _handle_hard_limit_with_escalation(container, usage, _app)
        else:
            # 短期容器：不做动作，但检查是否有遗留冻结状态（来自曾是长期的时期）
            _log_freeze_state_if_exists(container)
            logger.info("[disk-check] response disabled, skip action for container %s", container.id)
    elif usage_percent >= soft_limit:
        logger.warning("[disk-check] SOFT LIMIT exceeded: %s", log_msg)
        if response_enabled:
            _handle_soft_limit(container, usage, _app)
        else:
            logger.info("[disk-check] response disabled, skip action for container %s", container.id)
    else:
        logger.info("[disk-check] OK: %s", log_msg)


def _fmt_bytes(b: int) -> str:
    if b >= 1024**3:
        return f"{b/(1024**3):.1f}G"
    if b >= 1024**2:
        return f"{b/(1024**2):.1f}M"
    if b >= 1024:
        return f"{b/1024:.1f}K"
    return f"{b}B"


def _handle_soft_limit(container, usage: dict, app) -> None:
    """快满时发邮件提醒。同一容器 24 小时内不重复。"""
    from ..utils.mail import send as send_mail

    # 冷却: 24 小时
    last_key = f"_soft_limit_last_sent_{container.id}"
    now_ts = time.time()
    last_sent = getattr(app, '_disk_check_cache', {}) if app else {}
    if not isinstance(last_sent, dict):
        last_sent = {}
    if now_ts - last_sent.get(last_key, 0) < 24 * 3600:
        return

    try:
        emails = container_tasks.get_container_root_owner_emails(container.id)
    except Exception:
        emails = []

    if not emails:
        logger.warning("[disk-check] soft limit: no owner email for container %s", container.id)
        return

    container_data = usage.get("container", {})
    total_gb = (container_data.get("total_bytes") or 0) / (1024**3)
    limit_gb = _get_limit_gb(container, app)
    usage_pct = (total_gb / limit_gb * 100) if limit_gb > 0 else 0

    subject = f"伏羲平台 - 容器 {container.name} 磁盘使用接近上限"
    content = (
        f"容器: {container.name}\n"
        f"磁盘用量: {total_gb:.1f}GB / {limit_gb:.1f}GB ({usage_pct:.0f}%)\n"
        f"请及时联系管理员。并清理不必要的文件，避免达到上限后被冻结；\n"
        f"或转为短期容器（取消勾选长期容器）。\n"
    )
    for email in emails:
        try:
            send_mail(to=email, subject=subject, content=content)
            logger.info("[disk-check] soft limit email sent to %s for container %s", email, container.id)
        except Exception as e:
            logger.warning("[disk-check] soft limit email failed to %s: %s", email, e)
    last_sent[last_key] = now_ts
    if app:
        app._disk_check_cache = last_sent


def _handle_hard_limit(container, usage: dict, app) -> None:
    """超限时 docker pause 容器 + 发邮件。"""
    from ..utils.mail import send as send_mail

    try:
        emails = container_tasks.get_container_root_owner_emails(container.id)
    except Exception:
        emails = []

    container_data = usage.get("container", {})
    total_gb = (container_data.get("total_bytes") or 0) / (1024**3)
    limit_gb = _get_limit_gb(container, app)
    usage_pct = (total_gb / limit_gb * 100) if limit_gb > 0 else 0

    # 冷却: 同一容器 6 小时内不重复发邮件
    last_key = f"_hard_limit_last_sent_{container.id}"
    now_ts = time.time()
    last_sent = getattr(app, '_disk_check_cache', {}) if app else {}
    if not isinstance(last_sent, dict):
        last_sent = {}
    if now_ts - last_sent.get(last_key, 0) < 6 * 3600:
        # 仍在冷却中，但容器仍可能需 pause（首次之后的状态检查）
        pass
    else:
        subject = f"伏羲平台 - 容器 {container.name} 磁盘超限已冻结"
        content = (
            f"容器: {container.name}\n"
            f"磁盘用量: {total_gb:.1f}GB / {limit_gb:.1f}GB ({usage_pct:.0f}%)\n"
            f"\n容器已被冻结（docker pause）。\n"
            f"请及时清理不必要的文件；或转为短期容器（取消勾选长期容器）。\n"
        )
        for e in emails:
            try:
                send_mail(to=e, subject=subject, content=content)
                logger.info("[disk-check] hard limit email sent to %s for container %s", e, container.id)
            except Exception as ex:
                logger.warning("[disk-check] hard limit email failed to %s: %s", e, ex)
        last_sent[last_key] = now_ts
        if app:
            app._disk_check_cache = last_sent

    # docker pause — 仅在线容器执行
    try:
        status = getattr(container, 'container_status', None)
        status_val = status.value if hasattr(status, 'value') else str(status)
        if str(status_val).lower() not in ('online',):
            logger.info("[disk-check] pause skipped for container %s: status=%s", container.id, status_val)
            return
        ok = container_tasks.pause_container(
            container.id,
            extra_detail={"reason": "disk_hard_limit", "usage": f"{total_gb:.1f}GB/{limit_gb:.1f}GB"},
        )
        logger.debug("[disk-check] pause result for container %s: %s", container.id, ok)
    except Exception as e:
        logger.error("[disk-check] pause failed for container %s: %s", container.id, e)


def _handle_hard_limit_with_escalation(container, usage: dict, app) -> None:
    """长期容器 hard limit 响应：冻结记录 + 宽限判断 + 升级判断。

    状态追踪（upsert、宽限、升级天数）总是执行；
    动作（pause / remove）仅在 response_enabled 时执行。
    """
    from ..repositories import container_disk_freeze_state_repo as freeze_state_repo

    # 记录/确认冻结状态（首次设 first_frozen_at，后续不动）
    freeze_state = freeze_state_repo.upsert_first_frozen(container.id)

    # ── 宽限期检查 ──
    if freeze_state.grace_until and datetime.utcnow() < freeze_state.grace_until:
        logger.info("[disk-check] in grace period until %s, skip action for container %s (%s)",
                    freeze_state.grace_until, container.id, getattr(container, 'name', '?'))
        return

    # 宽限期已过期，清除
    if freeze_state.grace_until:
        freeze_state_repo.clear_grace(container.id)
        logger.info("[disk-check] grace period expired for container %s (%s)",
                    container.id, getattr(container, 'name', '?'))

    # ── 升级判断 ──
    days_frozen = (datetime.utcnow() - freeze_state.first_frozen_at).days
    escalation_days = getattr(app, "CONTAINER_DISK_FREEZE_ESCALATION_DAYS", 7)
    if days_frozen >= escalation_days:
        _handle_freeze_escalation(container, usage, app, days_frozen)
    else:
        _handle_hard_limit(container, usage, app)


def _log_freeze_state_if_exists(container) -> None:
    """短期容器超 hard limit 时：不做动作，但记录是否存在遗留冻结状态。"""
    from ..repositories import container_disk_freeze_state_repo as freeze_state_repo

    existing = freeze_state_repo.get(container.id)
    if existing is None:
        return

    days_frozen = (datetime.utcnow() - existing.first_frozen_at).days
    grace_info = ""
    if existing.grace_until:
        if datetime.utcnow() < existing.grace_until:
            grace_info = ", grace active"
        else:
            grace_info = ", grace expired"
    logger.warning("[disk-check] container %s (%s) has legacy freeze state (frozen %sd ago%s) but is not long-term, skip action",
                   container.id, getattr(container, 'name', '?'), days_frozen, grace_info)


def _handle_freeze_escalation(container, usage: dict, app, days_frozen: int) -> None:
    """冻结满 N 天仍超限 → remove_container + 通知邮件。"""
    from ..utils.mail import send as send_mail

    container_data = usage.get("container", {})
    total_gb = (container_data.get("total_bytes") or 0) / (1024**3)
    limit_gb = _get_limit_gb(container, app)
    usage_pct = (total_gb / limit_gb * 100) if limit_gb > 0 else 0

    # 冷却: 同一容器 24 小时内不重复发送升级邮件
    last_key = f"_escalation_last_sent_{container.id}"
    now_ts = time.time()
    last_sent = getattr(app, '_disk_check_cache', {}) if app else {}
    if not isinstance(last_sent, dict):
        last_sent = {}

    if now_ts - last_sent.get(last_key, 0) < 24 * 3600:
        pass  # 仍在冷却中，但仍执行 remove
    else:
        try:
            emails = container_tasks.get_container_root_owner_emails(container.id)
        except Exception:
            emails = []

        if emails:
            subject = f"伏羲平台 - 容器 {container.name} 因磁盘超限已被清除"
            content = (
                f"容器: {container.name}\n"
                f"磁盘用量: {total_gb:.1f}GB / {limit_gb:.1f}GB ({usage_pct:.0f}%)\n"
                f"已冻结天数: {days_frozen} 天\n"
                f"\n容器已被清除。如有疑问请联系管理员。\n"
            )
            for e in emails:
                try:
                    send_mail(to=e, subject=subject, content=content)
                    logger.info("[disk-check] escalation email sent to %s for container %s", e, container.id)
                except Exception as ex:
                    logger.warning("[disk-check] escalation email failed to %s: %s", e, ex)
            last_sent[last_key] = now_ts
            if app:
                app._disk_check_cache = last_sent

    # ── 删除容器 ──
    try:
        container_tasks.remove_container(container.id)
        logger.warning("[disk-check] escalation: removed container %s (%s) after %sd frozen",
                       container.id, getattr(container, 'name', '?'), days_frozen)
        from ..services.operation_log_tasks import write_operation_log as write_op_log
        write_op_log(success=True,
            operation=OperationType.REMOVE_CONTAINER,
            target_type="container",
            target_id=container.id,
            detail={
                "reason": "disk_freeze_escalation",
                "days_frozen": days_frozen,
                "usage": f"{total_gb:.1f}GB/{limit_gb:.1f}GB",
            },
        )

        # 升级删除：立刻清理 mount（宽限期已是最后机会）
        _clean_mount_immediately(container)
    except Exception as e:
        logger.error("[disk-check] escalation remove failed for container %s: %s", container.id, e)


def _clean_mount_immediately(container) -> None:
    """冻结升级后立刻清理宿主机 mount 目录。

    记录 MountCleanup（escalation=True, cleaned_at=now），
    并向 NodeKernel 发送清理请求。
    """
    bind_mount = getattr(container, 'bind_mount_path', None)
    if not bind_mount:
        logger.info("[disk-check] escalation: no bind_mount_path for container %s, skip mount cleanup",
                    getattr(container, 'id', '?'))
        return

    try:
        from ..repositories.container_mount_cleanup_repo import insert as insert_mount_cleanup
        from datetime import datetime as dt

        insert_mount_cleanup(
            container_id=container.id,
            container_name=container.name,
            machine_id=container.machine_id,
            mount_path=bind_mount,
            escalation=True,
            removed_at=dt.utcnow(),
            cleaned_at=dt.utcnow(),
        )
    except Exception as e:
        logger.warning("[disk-check] escalation: failed to record mount cleanup for %s: %s", container.id, e)

    try:
        from ..repositories.machine_repo import get_machine_ip_by_id
        machine_ip = get_machine_ip_by_id(container.machine_id)
        url = container_tasks.get_full_url(machine_ip, "/clean_mount")
        payload = {"config": {"mount_path": bind_mount}}
        res = container_tasks.send(url, payload, timeout=10.0)
        logger.debug("[disk-check] escalation mount cleanup for container %s path=%s: %s",
                     container.id, bind_mount, res)
    except Exception as e:
        logger.error("[disk-check] escalation mount cleanup failed for container %s path=%s: %s",
                     container.id, bind_mount, e)


def _get_limit_gb(container, app) -> float:
    try:
        machine = container.machine
        disk_size_gb = getattr(machine, 'disk_size_gb', None) or 0
    except Exception:
        disk_size_gb = 0
    return float(disk_size_gb)


def start_container_disk_check_scheduler(interval_seconds: int = 900) -> threading.Thread | None:
    """
    启动后台定期磁盘检测任务。
    仅在 CONTAINER_DISK_CHECK_ENABLED=true 时启动。
    """
    if not getattr(AppConfig, "CONTAINER_DISK_CHECK_ENABLED", False):
        return None

    key = "container_disk_check_scheduler"
    existing = _SCHEDULER_STATE.get(key)
    if existing and isinstance(existing, dict) and existing.get("thread"):
        t = existing["thread"]
        if t.is_alive():
            return t

    stop_event = threading.Event()

    def _worker():
        check_all_containers_disk_usage_once()

        while not stop_event.is_set():
            time.sleep(interval_seconds)
            if stop_event.is_set():
                break
            try:
                check_all_containers_disk_usage_once()
            except Exception as e:
                logger.error("[disk-check] periodic run failed: %s", e)

    t = threading.Thread(target=_worker, daemon=True, name="container-disk-check")
    t.start()

    _SCHEDULER_STATE[key] = {"thread": t, "stop_event": stop_event}
    return t
