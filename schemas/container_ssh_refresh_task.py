import threading
import time
from flask import Flask

from ..repositories import containers_repo
from ..services import container_tasks


def refresh_all_containers_last_ssh_login_time_once(page_size: int = 200) -> None:
    """
    单次刷新：遍历所有容器，向各节点拉取并落库“上次 SSH 登录时间”。
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
            try:
                # 该函数内部会把结果（含 None）写入 container_ssh_login_records
                container_tasks.get_container_last_ssh_login_time(c.name)
            except Exception as e:
                print(
                    f"[ssh-refresh] failed for container id={getattr(c, 'id', '?')} "
                    f"name={getattr(c, 'name', '?')}: {e}"
                )

        if len(containers) < page_size:
            break
        offset += page_size


def start_container_ssh_refresh_scheduler(
    app: Flask,
    interval_seconds: int = 300,
) -> threading.Thread:
    """
    启动后台定时任务：
    - 首次启动立即执行一次
    - 之后每 interval_seconds（默认 300s = 5min）执行一次
    """
    key = "container_ssh_refresh_scheduler"
    existing = app.extensions.get(key)
    if existing and isinstance(existing, dict) and existing.get("thread"):
        t = existing["thread"]
        if t.is_alive():
            return t

    stop_event = threading.Event()

    def _worker():
        # 启动后先跑一次，避免冷启动后长时间没有数据
        with app.app_context():
            refresh_all_containers_last_ssh_login_time_once()

        while not stop_event.is_set():
            time.sleep(interval_seconds)
            if stop_event.is_set():
                break
            try:
                with app.app_context():
                    refresh_all_containers_last_ssh_login_time_once()
            except Exception as e:
                print(f"[ssh-refresh] periodic run failed: {e}")

    t = threading.Thread(target=_worker, daemon=True, name="container-ssh-refresh")
    t.start()

    app.extensions[key] = {"thread": t, "stop_event": stop_event}
    return t

