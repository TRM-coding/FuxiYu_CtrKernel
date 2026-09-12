import time
import json
import threading
import logging
from datetime import datetime

from ..constant import OperationType
from ..extensions import session_scope
from ..repositories import containers_repo, long_term_container_repo, container_cleanup_reminder_repo
from ..repositories import container_ssh_login_repo
from ..services import container_tasks, settings_tasks
from ..services.machine_tasks import machine_in_scope
from ..utils.mail import send as send_mail

logger = logging.getLogger(__name__)
_SCHEDULER_STATE: dict[str, object] = {}


def _parse_reminder_hours(raw: str | None) -> list[int]:
    values = []
    for item in str(raw or "72,24,12").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            hours = int(item)
        except Exception:
            continue
        if hours > 0 and hours not in values:
            values.append(hours)
    return sorted(values, reverse=True)


def _parse_cleanup_at(cleanup_at: str | None) -> datetime | None:
    if not cleanup_at:
        return None
    try:
        return datetime.fromisoformat(str(cleanup_at).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _format_hours(hours: int) -> str:
    if hours % 24 == 0:
        days = hours // 24
        return f"{days}天"
    return f"{hours}小时"


def _send_cleanup_reminders_if_needed(container_id: int, info: dict, reminder_hours_raw: str | None = None) -> None:
    if info.get("cleanup_status") != "countdown":
        return

    seconds_left = info.get("seconds_until_cleanup")
    cleanup_at = _parse_cleanup_at(info.get("cleanup_at"))
    if seconds_left is None or cleanup_at is None:
        return

    try:
        seconds_left = int(seconds_left)
    except Exception:
        return

    if reminder_hours_raw is None:
        reminder_hours_raw = settings_tasks.get_container_cleanup_reminder_hours()
    reminder_hours = _parse_reminder_hours(reminder_hours_raw)
    eligible_hours = [hours for hours in reminder_hours if 0 < seconds_left <= hours * 3600]
    if not eligible_hours:
        return

    # 清理旧的提醒记录（用户重新 SSH 后 cleanup_at 已变，旧记录无意义）
    if cleanup_at:
        with session_scope() as session:
            container_cleanup_reminder_repo.clear_stale(container_id, cleanup_at, session=session)

    # If an earlier scan was missed, send the nearest reminder that is still relevant.
    for hours in [min(eligible_hours)]:

        snapshot = container_tasks.build_container_restore_snapshot(
            container_id,
            cleanup_context={**info, "reminder_threshold_hours": hours},
        )
        with session_scope(commit=False) as session:
            recipients = containers_repo.get_container_root_owner_emails(container_id, session=session)
        if not recipients:
            logger.info("[container-cleanup] reminder skipped for container_id=%s: no root owner email", container_id)
            return

        label = _format_hours(hours)
        subject = f"伏羲平台 - 容器清理提醒：{snapshot.get('container_name')} 剩余约{label}"
        content = (
            f"你的容器即将因 SSH 长时间未登录被自动清理。\n\n"
            f"容器ID：{container_id}\n"
            f"容器名称：{snapshot.get('container_name')}\n"
            f"宿主机：{snapshot.get('machine_name') or '-'} ({snapshot.get('machine_ip') or '-'})\n"
            f"预计清理时间：{info.get('cleanup_at')}\n"
            f"上次 SSH 登录：{info.get('last_ssh_login_time') or '从未登录'}\n\n"
            f"如需保留，请及时 SSH 登录该容器，或联系管理员设置为长期容器。"
        )

        reminder_key = f"{hours}h"
        for email in recipients:
            with session_scope(commit=False) as session:
                sent = container_cleanup_reminder_repo.was_sent(
                    container_id,
                    reminder_key,
                    cleanup_at,
                    email,
                    session=session,
                )
            if sent:
                continue
            result = send_mail(
                to=email, subject=subject, content=content,
                operation=OperationType.SEND_CLEANUP_REMINDER,
                target_type="container", target_id=container_id,
                detail={
                    "mail_type": "cleanup_reminder",
                    "name": snapshot.get("container_name"),
                    "original_container_name": snapshot.get("container_name"),
                    "threshold": reminder_key,
                    "cleanup_at": cleanup_at.isoformat(),
                },
            )
            if not result.get("ok"):
                continue
            try:
                with session_scope() as session:
                    marked = container_cleanup_reminder_repo.mark_sent(
                        container_id, reminder_key, cleanup_at, email, session=session,
                    )
                if not marked:
                    logger.warning("[container-cleanup] reminder already recorded container_id=%s to=%s",
                                   container_id, email)
            except Exception as exc:
                logger.warning("[container-cleanup] reminder sent but recording failed container_id=%s to=%s: %s",
                               container_id, email, exc)


def cleanup_expired_containers_once(cleanup_after_days: int) -> None:
    """
    单次扫描：查找已过期容器并释放。
    注意：这里只调用现有 remove_container，不在此处实现新的清理机制。
    """
    if cleanup_after_days <= 0:
        cleanup_after_days = 1


    with session_scope(commit=False) as session:
        records = container_ssh_login_repo.list_all(session=session)
    for rec in records:
        try:
            # 顺延口径与详情/提醒一致：有效最后登录 = last_ssh + 机器不可用顺延(deferral)
            info = container_tasks.build_cleanup_info(
                rec.last_ssh_login_time,
                cleanup_after_days,
                getattr(rec, "deferral_seconds", 0) or 0,
            )
            cid = int(rec.container_id)
            with session_scope(commit=False) as session:
                is_long_term = long_term_container_repo.is_long_term(cid, session=session)
            if is_long_term:
                logger.info("[container-cleanup] container_id=%s is long-term, skipping cleanup", cid)
                continue
            info_with_record = {
                **info,
                "last_ssh_login_time": rec.last_ssh_login_time,
                "ssh_record_updated_at": (
                    rec.updated_at.isoformat()
                    if getattr(rec, "updated_at", None) is not None
                    else None
                ),
            }
            _send_cleanup_reminders_if_needed(cid, info_with_record)
            if info.get("cleanup_status") != "due":
                continue
            # 管辖范畴：机器可达且非维护才发起清理。
            # 范畴外是职责划分而非门禁——这次动作本就不该发生，静默跳过：
            # 不留审计、不留常规日志（没有动作被尝试，就没有失败可言）。
            # 缺此判定时，动作层抛出的异常会在 _audit_removal 落库后才冒泡，
            # 每轮为每个到期容器写一条 delete_container 失败记录。
            if not machine_in_scope(getattr(rec, "machine_id", None)):
                continue
            snapshot = container_tasks.build_container_restore_snapshot(
                cid,
                cleanup_context={
                    "machine_id": getattr(rec, "machine_id", None),
                    **info_with_record,
                },
            )
            logger.debug("[container-cleanup] restore_snapshot=%s",
                         json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
            logger.info("[container-cleanup] container_id=%s due for cleanup, removing...", cid)
            ok = container_tasks.remove_container(container_id=cid)
            if ok:
                logger.info("[container-cleanup] removed container_id=%s", cid)
            else:
                logger.warning("[container-cleanup] remove returned False for container_id=%s", cid)
        except Exception as e:
            logger.error("[container-cleanup] failed for machine_id=%s container_id=%s: %s",
                         getattr(rec, 'machine_id', '?'), getattr(rec, 'container_id', '?'), e)


def start_container_cleanup_scheduler(interval_seconds: int | None = None) -> threading.Thread:
    """启动容器定时清理任务（由 create_app 背景任务统一入口调用）：
    - 默认每 20 分钟扫描一次
    - 启动后先执行一次，保证历史到期容器可尽快处理
    - 清理动作只面向到期集合（提醒邮件 / 到期移除），不做逐容器探测请求
    """
    key = "container_cleanup_scheduler"
    existing = _SCHEDULER_STATE.get(key)
    if existing and isinstance(existing, dict) and existing.get("thread"):
        t = existing["thread"]
        if t.is_alive():
            return t

    if interval_seconds is None:
        interval_seconds = settings_tasks.get_container_cleanup_interval_seconds()

    stop_event = threading.Event()

    def _worker():
        days = settings_tasks.get_container_cleanup_after_days()
        cleanup_expired_containers_once(days)

        while not stop_event.is_set():
            time.sleep(interval_seconds)
            if stop_event.is_set():
                break
            try:
                days = settings_tasks.get_container_cleanup_after_days()
                cleanup_expired_containers_once(days)
            except Exception as e:
                logger.error("[container-cleanup] periodic run failed: %s", e)

    t = threading.Thread(target=_worker, daemon=True, name="container-cleanup")
    t.start()
    _SCHEDULER_STATE[key] = {"thread": t, "stop_event": stop_event}
    return t
