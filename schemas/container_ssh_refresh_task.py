import threading
import time
import logging
from flask import Flask, current_app

from ..repositories import containers_repo
from ..services import container_tasks
from ..utils.parallel import parallel_node_calls

logger = logging.getLogger(__name__)


def refresh_all_containers_last_ssh_login_time_once(page_size: int = 200) -> None:
    """遍历所有容器，向各节点拉取并落库上次 SSH 登录时间。"""
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
                lambda cid=c.id, a=_app: _ssh_refresh_one(cid, a)
                for c in containers
            ]
            _raw = parallel_node_calls(_callables, timeout_per_call=8.0)
            for c, r in zip(containers, _raw):
                if isinstance(r, Exception):
                    logger.warning("[ssh-refresh] failed for container id=%s name=%s: %s",
                                   getattr(c, 'id', '?'), getattr(c, 'name', '?'), r)
        else:
            for c in containers:
                try:
                    container_tasks.get_container_last_ssh_login_time(c.id)
                except Exception as e:
                    logger.warning("[ssh-refresh] failed for container id=%s name=%s: %s",
                                   getattr(c, 'id', '?'), getattr(c, 'name', '?'), e)

        if len(containers) < page_size:
            break
        offset += page_size


def _ssh_refresh_one(container_id: int, app: Flask) -> None:
    """在 app context 内刷新单个容器的 SSH 登录时间。"""
    with app.app_context():
        container_tasks.get_container_last_ssh_login_time(container_id)


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
        # 启动后先跑一次 SSH，磁盘检测并行
        with app.app_context():
            refresh_all_containers_last_ssh_login_time_once()
            threading.Thread(target=_run_disk_check, args=(app,), daemon=True).start()

        while not stop_event.is_set():
            time.sleep(interval_seconds)
            if stop_event.is_set():
                break
            try:
                with app.app_context():
                    refresh_all_containers_last_ssh_login_time_once()
                # 磁盘检测独立线程并行，不阻塞 SSH 刷新
                threading.Thread(target=_run_disk_check, args=(app,), daemon=True).start()
            except Exception as e:
                logger.error("[ssh-refresh] periodic run failed: %s", e)

    t = threading.Thread(target=_worker, daemon=True, name="container-ssh-refresh")
    t.start()

    app.extensions[key] = {"thread": t, "stop_event": stop_event}
    return t


def _run_disk_check(app):
    """在独立线程内执行一次磁盘检测（只读/评估/响应）。"""
    try:
        with app.app_context():
            from .container_disk_check_task import check_all_containers_disk_usage_once
            check_all_containers_disk_usage_once()
    except Exception as e:
        logger.error("[ssh-refresh] disk check failed: %s", e)
