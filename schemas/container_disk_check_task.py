import json
import threading
import time
from flask import Flask, current_app

from ..repositories import containers_repo
from ..services import container_tasks
from ..utils.parallel import parallel_node_calls


def check_all_containers_disk_usage_once(page_size: int = 200) -> None:
    """遍历所有容器，向各 Node 拉取磁盘使用数据（只读、只记日志）。"""
    try:
        _app = current_app._get_current_object()
        use_parallel = current_app.config.get("NODE_PARALLEL_ENABLED_SSH_REFRESH", True)
    except RuntimeError:
        _app = None
        use_parallel = True

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

        if use_parallel and _app is not None:
            _callables = [
                lambda cid=c.id, a=_app: _disk_check_one(cid, a)
                for c in containers
            ]
            _raw = parallel_node_calls(_callables, timeout_per_call=22.0)
            for c, r in zip(containers, _raw):
                if isinstance(r, Exception):
                    print(
                        f"[disk-check] failed for container id={getattr(c, 'id', '?')} "
                        f"name={getattr(c, 'name', '?')}: {r}"
                    )
                elif isinstance(r, dict):
                    _evaluate_limits(c, r)
        else:
            for c in containers:
                try:
                    usage = container_tasks.get_container_disk_usage(c.id)
                    if isinstance(usage, dict):
                        _evaluate_limits(c, usage)
                except Exception as e:
                    print(
                        f"[disk-check] failed for container id={getattr(c, 'id', '?')} "
                        f"name={getattr(c, 'name', '?')}: {e}"
                    )

        if len(containers) < page_size:
            break
        offset += page_size


def _disk_check_one(container_id: int, app: Flask) -> None:
    """在 app context 内查询单个容器的磁盘使用。"""
    with app.app_context():
        usage = container_tasks.get_container_disk_usage(container_id)
        if isinstance(usage, dict):
            # fetch container obj within app context for limit evaluation
            container = containers_repo.get_by_id(container_id)
            if container:
                _evaluate_limits(container, usage)
        return usage


def _evaluate_limits(container, usage: dict) -> None:
    """评估磁盘用量，根据 soft/hard 阈值执行告警/冻结（Phase 3 启用）。"""
    try:
        _app = current_app._get_current_object()
    except RuntimeError:
        _app = None

    enabled = (_app and _app.config.get("CONTAINER_DISK_CHECK_ENABLED", False))
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
        print(f"[disk-check] skip container_id={container.id}: machine disk_size_gb not set")
        return

    limit_bytes = int(disk_size_gb * 1024**3)
    if limit_bytes <= 0:
        return

    usage_percent = (total_bytes / limit_bytes) * 100

    soft_limit = _app.config.get("CONTAINER_DISK_SOFT_LIMIT_PERCENT", 80)
    hard_limit = _app.config.get("CONTAINER_DISK_HARD_LIMIT_PERCENT", 100)

    overlay_rw = container_data.get("overlay_rw_bytes") or 0
    bind_mount = container_data.get("bind_mount_bytes") or 0

    # 持久化磁盘用量到 DB
    try:
        from datetime import datetime
        containers_repo.update_container(
            container.id,
            commit=True,
            disk_overlay_rw_bytes=int(overlay_rw),
            disk_bind_mount_bytes=int(bind_mount),
            disk_total_bytes=int(total_bytes),
            disk_limit_bytes=int(limit_bytes),
            disk_checked_at=datetime.utcnow(),
        )
    except Exception as e:
        print(f"[disk-check] failed to persist disk usage for container {container.id}: {e}")

    log_msg = (
        f"[disk-check] container_id={container.id} name={getattr(container, 'name', '?')} "
        f"total={_fmt_bytes(total_bytes)}/{_fmt_bytes(limit_bytes)} ({usage_percent:.1f}%) "
        f"overlay={_fmt_bytes(overlay_rw)} bind={_fmt_bytes(bind_mount)}"
    )

    response_enabled = _app.config.get("CONTAINER_DISK_RESPONSE_ENABLED", False) if _app else False

    # 非持久容器只做检测，不接受容量响应（不 pause / 不发邮件）。
    # 此检查先于全局 CONTAINER_DISK_RESPONSE_ENABLED 判断，
    # 方便在关闭响应的情况下从日志验证行为，无影响上线。
    from ..repositories.long_term_container_repo import is_long_term
    if not is_long_term(container.id):
        print(
            f"[disk-check] container {container.id} "
            f"({getattr(container, 'name', '?')}) is not long-term, skip response"
        )
        response_enabled = False

    if usage_percent >= hard_limit:
        print(f"[disk-check] HARD LIMIT exceeded: {log_msg}")
        if response_enabled:
            _handle_hard_limit(container, usage, _app)
        else:
            print(f"[disk-check] response disabled, skip action for container {container.id}")
    elif usage_percent >= soft_limit:
        print(f"[disk-check] SOFT LIMIT exceeded: {log_msg}")
        if response_enabled:
            _handle_soft_limit(container, usage, _app)
        else:
            print(f"[disk-check] response disabled, skip action for container {container.id}")
    else:
        print(f"[disk-check] OK: {log_msg}")


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
        print(f"[disk-check] soft limit: no owner email for container {container.id}")
        return

    container_data = usage.get("container", {})
    total_gb = (container_data.get("total_bytes") or 0) / (1024**3)
    limit_gb = _get_limit_gb(container, app)
    usage_pct = (total_gb / limit_gb * 100) if limit_gb > 0 else 0

    subject = f"伏羲平台 - 容器 {container.name} 磁盘使用接近上限"
    content = (
        f"容器: {container.name}\n"
        f"磁盘用量: {total_gb:.1f}GB / {limit_gb:.1f}GB ({usage_pct:.0f}%)\n"
        f"请及时清理不必要的文件，避免达到上限后被冻结。\n"
    )
    for email in emails:
        try:
            send_mail(to=email, subject=subject, content=content)
            print(f"[disk-check] soft limit email sent to {email} for container {container.id}")
        except Exception as e:
            print(f"[disk-check] soft limit email failed to {email}: {e}")
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
            f"\n容器已被冻结（docker pause），请联系管理员清理后恢复。\n"
        )
        for e in emails:
            try:
                send_mail(to=e, subject=subject, content=content)
                print(f"[disk-check] hard limit email sent to {e} for container {container.id}")
            except Exception as ex:
                print(f"[disk-check] hard limit email failed to {e}: {ex}")
        last_sent[last_key] = now_ts
        if app:
            app._disk_check_cache = last_sent

    # docker pause — 仅在线容器执行
    try:
        status = getattr(container, 'container_status', None)
        status_val = status.value if hasattr(status, 'value') else str(status)
        if str(status_val).lower() not in ('online',):
            print(f"[disk-check] pause skipped for container {container.id}: status={status_val}")
            return
        from ..repositories.machine_repo import get_machine_ip_by_id
        from ..constant import ContainerStatus
        machine_ip = get_machine_ip_by_id(container.machine_id)
        url = container_tasks.get_full_url(machine_ip, "/pause_container")
        payload = json.dumps({"config": {"container_name": container.name, "action": "pause"}})
        sig = container_tasks.signature(payload)
        enc = container_tasks.encryption(payload)
        res = container_tasks.send(enc, sig, url, timeout=10.0)
        print(f"[disk-check] pause result for container {container.id}: {res}")
        # 更新 DB 状态为 paused，防止并行检查重复 pause
        if isinstance(res, dict) and res.get("success") == 1:
            containers_repo.update_container(container.id, commit=True,
                container_status=ContainerStatus.PAUSED)
        from ..repositories.operation_log_repo import write as write_op_log
        write_op_log(operation="pause_container", target_type="container",
                     target_id=container.id,
                     detail={"reason": "disk_hard_limit", "usage": f"{total_gb:.1f}GB/{limit_gb:.1f}GB"})
    except Exception as e:
        print(f"[disk-check] pause failed for container {container.id}: {e}")


def _get_limit_gb(container, app) -> float:
    try:
        machine = container.machine
        disk_size_gb = getattr(machine, 'disk_size_gb', None) or 0
    except Exception:
        disk_size_gb = 0
    return float(disk_size_gb)


def start_container_disk_check_scheduler(
    app: Flask,
    interval_seconds: int = 900,
) -> threading.Thread | None:
    """
    启动后台定期磁盘检测任务。
    仅在 CONTAINER_DISK_CHECK_ENABLED=true 时启动。
    """
    if not app.config.get("CONTAINER_DISK_CHECK_ENABLED", False):
        return None

    key = "container_disk_check_scheduler"
    existing = app.extensions.get(key)
    if existing and isinstance(existing, dict) and existing.get("thread"):
        t = existing["thread"]
        if t.is_alive():
            return t

    stop_event = threading.Event()

    def _worker():
        with app.app_context():
            check_all_containers_disk_usage_once()

        while not stop_event.is_set():
            time.sleep(interval_seconds)
            if stop_event.is_set():
                break
            try:
                with app.app_context():
                    check_all_containers_disk_usage_once()
            except Exception as e:
                print(f"[disk-check] periodic run failed: {e}")

    t = threading.Thread(target=_worker, daemon=True, name="container-disk-check")
    t.start()

    app.extensions[key] = {"thread": t, "stop_event": stop_event}
    return t
