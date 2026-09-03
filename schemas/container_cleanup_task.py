import threading
import time
import json
from datetime import datetime
from flask import Flask, current_app

from ..models.container_ssh_login import ContainerSSHLogin
from ..constant import OperationType
from ..repositories import long_term_container_repo, container_cleanup_reminder_repo
from ..services import container_tasks
from ..utils.mail import send as send_mail


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


def _send_cleanup_reminders_if_needed(container_id: int, info: dict, app: Flask) -> None:
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

    reminder_hours = _parse_reminder_hours(app.config.get("CONTAINER_CLEANUP_REMINDER_HOURS", "72,24,12"))
    eligible_hours = [hours for hours in reminder_hours if 0 < seconds_left <= hours * 3600]
    if not eligible_hours:
        return

    # 清理旧的提醒记录（用户重新 SSH 后 cleanup_at 已变，旧记录无意义）
    if cleanup_at:
        container_cleanup_reminder_repo.clear_stale(container_id, cleanup_at)

    # If an earlier scan was missed, send the nearest reminder that is still relevant.
    for hours in [min(eligible_hours)]:

        snapshot = container_tasks.build_container_restore_snapshot(
            container_id,
            cleanup_context={**info, "reminder_threshold_hours": hours},
        )
        recipients = container_tasks.get_container_root_owner_emails(container_id)
        if not recipients:
            print(f"[container-cleanup] reminder skipped for container_id={container_id}: no root owner email")
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
            if container_cleanup_reminder_repo.was_sent(container_id, reminder_key, cleanup_at, email):
                continue
            result = send_mail(to=email, subject=subject, content=content)
            if result.get("ok"):
                if container_cleanup_reminder_repo.mark_sent(container_id, reminder_key, cleanup_at, email):
                    print(f"[container-cleanup] reminder sent container_id={container_id} threshold={reminder_key} to={email}")
                    from ..services.operation_log_tasks import write_operation_log as write_op_log
                    write_op_log(success=True,
                        operation=OperationType.SEND_CLEANUP_REMINDER,
                        target_type="container",
                        target_id=container_id,
                        detail={
                            "recipient": email,
                            "threshold": reminder_key,
                            "cleanup_at": cleanup_at.isoformat() if cleanup_at else None,
                        },
                    )
                else:
                    print(f"[container-cleanup] reminder duplicate container_id={container_id} threshold={reminder_key} to={email} (already recorded)")
            else:
                print(f"[container-cleanup] reminder failed container_id={container_id} threshold={reminder_key} to={email}: {result}")


def cleanup_expired_containers_once(cleanup_after_days: int) -> None:
    """
    单次扫描：查找已过期容器并释放。
    注意：这里只调用现有 remove_container，不在此处实现新的清理机制。
    """
    if cleanup_after_days <= 0:
        cleanup_after_days = 1


    records = ContainerSSHLogin.query.all()
    for rec in records:
        try:
            info = container_tasks.build_cleanup_info(rec.last_ssh_login_time, cleanup_after_days)
            cid = int(rec.container_id)
            if long_term_container_repo.is_long_term(cid):
                print(f"[container-cleanup] container_id={cid} is long-term, skipping cleanup")
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
            _send_cleanup_reminders_if_needed(cid, info_with_record, current_app)
            if info.get("cleanup_status") != "due":
                continue
            snapshot = container_tasks.build_container_restore_snapshot(
                cid,
                cleanup_context={
                    "machine_id": getattr(rec, "machine_id", None),
                    **info_with_record,
                },
            )
            print(
                "[container-cleanup] restore_snapshot="
                + json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
            )
            print(f"[container-cleanup] container_id={cid} due for cleanup, removing...")
            ok = container_tasks.remove_container(container_id=cid)
            if ok:
                print(f"[container-cleanup] removed container_id={cid}")
            else:
                print(f"[container-cleanup] remove returned False for container_id={cid}")
        except Exception as e:
            print(
                f"[container-cleanup] failed for machine_id={getattr(rec, 'machine_id', '?')} "
                f"container_id={getattr(rec, 'container_id', '?')}: {e}"
            )


def start_container_cleanup_scheduler(
    app: Flask,
    interval_seconds: int = 1200,  # 20 min
) -> threading.Thread:
    """
    启动容器定时清理任务：
    - 默认每 20 分钟扫描一次
    - 启动后先执行一次，保证历史到期容器可尽快处理
    """
    key = "container_cleanup_scheduler"
    existing = app.extensions.get(key)
    if existing and isinstance(existing, dict) and existing.get("thread"):
        t = existing["thread"]
        if t.is_alive():
            return t

    stop_event = threading.Event()

    def _worker():
        with app.app_context():
            days = int(app.config.get("CONTAINER_CLEANUP_AFTER_DAYS", 7) or 7)
            cleanup_expired_containers_once(days)

        while not stop_event.is_set():
            time.sleep(interval_seconds)
            if stop_event.is_set():
                break
            try:
                with app.app_context():
                    days = int(app.config.get("CONTAINER_CLEANUP_AFTER_DAYS", 7) or 7)
                    cleanup_expired_containers_once(days)
            except Exception as e:
                print(f"[container-cleanup] periodic run failed: {e}")

    t = threading.Thread(target=_worker, daemon=True, name="container-cleanup")
    t.start()
    app.extensions[key] = {"thread": t, "stop_event": stop_event}
    return t
