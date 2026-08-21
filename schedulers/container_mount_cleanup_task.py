"""已删除容器的 mount 目录定期清理任务。

扫描 container_mount_cleanup 表：
- escalation=False 且 removed_at 超过 14 天 → 向 NodeKernel 发清理请求
- escalation=True 的记录已在删除时立刻清理，此处跳过
"""

import threading
import time
import logging
from datetime import datetime, timedelta

from ..config import AppConfig
from ..extensions import session_scope
from ..repositories import container_mount_cleanup_repo, machine_repo
from ..services.container_tasks import get_full_url, send

logger = logging.getLogger(__name__)
_SCHEDULER_STATE: dict[str, object] = {}


def run_mount_cleanup_once() -> None:
    """扫描并清理到期 mount 目录（执行一次）。"""
    after_days = int(getattr(AppConfig, "CONTAINER_MOUNT_CLEANUP_AFTER_DAYS", 14) or 14)

    cutoff = datetime.utcnow() - timedelta(days=after_days)
    with session_scope(commit=False) as session:
        rows = container_mount_cleanup_repo.list_pending(cutoff, session=session)

    if not rows:
        return

    logger.info("[mount-cleanup] found %s pending mount(s) older than %s days", len(rows), after_days)

    for row in rows:
        try:
            with session_scope(commit=False) as session:
                machine_ip = machine_repo.get_machine_ip_by_id(row.machine_id, session=session)
            if not machine_ip:
                logger.warning("[mount-cleanup] skip row %s: machine %s not found", row.id, row.machine_id)
                continue

            url = get_full_url(machine_ip, "/clean_mount")
            payload = {"config": {"mount_path": row.mount_path}}
            res = send(url, payload, timeout=10.0)

            if isinstance(res, dict) and res.get("success") == 1:
                with session_scope() as session:
                    container_mount_cleanup_repo.mark_cleaned(row.id, session=session)
                logger.info("[mount-cleanup] cleaned row %s: container=%s path=%s",
                            row.id, row.container_name, row.mount_path)
            else:
                logger.error("[mount-cleanup] node rejected row %s: %s", row.id, res)
        except Exception as e:
            logger.error("[mount-cleanup] failed row %s: %s", row.id, e)


def start_mount_cleanup_scheduler(interval_seconds: int = 86400) -> threading.Thread | None:
    """启动后台定期 mount 清理任务。"""
    if not getattr(AppConfig, "CONTAINER_MOUNT_CLEANUP_ENABLED", False):
        return None

    key = "container_mount_cleanup_scheduler"
    existing = _SCHEDULER_STATE.get(key)
    if existing and isinstance(existing, dict) and existing.get("thread"):
        t = existing["thread"]
        if t.is_alive():
            return t

    stop_event = threading.Event()

    def _worker():
        run_mount_cleanup_once()

        while not stop_event.is_set():
            time.sleep(interval_seconds)
            if stop_event.is_set():
                break
            try:
                run_mount_cleanup_once()
            except Exception as e:
                logger.error("[mount-cleanup] periodic run failed: %s", e)

    t = threading.Thread(target=_worker, daemon=True, name="mount-cleanup")
    t.start()

    _SCHEDULER_STATE[key] = {"thread": t, "stop_event": stop_event}
    return t
