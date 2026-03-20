import threading
import time
from flask import Flask

from ..models.container_ssh_login import ContainerSSHLogin
from ..services import container_tasks


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
            if info.get("cleanup_status") != "due":
                continue

            cid = int(rec.container_id)
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

