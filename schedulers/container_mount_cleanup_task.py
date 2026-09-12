"""已删除容器的 mount 目录定期清理任务。

扫描 container_mount_cleanup 表：
- escalation=False 且 removed_at 超过 14 天 → 向 NodeKernel 发清理请求
- escalation=True 的记录已在删除时立刻清理，此处跳过
"""

import time
import threading
import logging
from datetime import datetime, timedelta

from ..extensions import session_scope
from ..repositories import container_mount_cleanup_repo, deleted_container_restore_snapshot_repo
from ..services import settings_tasks
from ..services.machine_tasks import machine_in_scope
from ..services.container_module.deleted_containers import (
    ensure_deleted_record_for_cleanup,
    ensure_mount_cleanup_record,
)
from ..services.container_module.mount_cleanup import clean_mount_path

logger = logging.getLogger(__name__)
_SCHEDULER_STATE: dict[str, object] = {}


def run_mount_cleanup_once() -> None:
    """扫描并清理到期 mount 目录（执行一次）。"""
    after_days = settings_tasks.get_container_mount_cleanup_after_days()

    cutoff = datetime.utcnow() - timedelta(days=after_days)
    with session_scope() as session:
        for legacy in container_mount_cleanup_repo.list_pending(cutoff, session=session):
            ensure_deleted_record_for_cleanup(legacy, session=session)
    with session_scope(commit=False) as session:
        rows = deleted_container_restore_snapshot_repo.list_pending_mount_cleanup(
            cutoff,
            session=session,
        )

    if not rows:
        return

    logger.info(
        "[mount-cleanup] found %s pending deleted container(s) older than %s days",
        len(rows),
        after_days,
    )

    for row in rows:
        try:
            with session_scope() as session:
                deleted, cleanup = ensure_mount_cleanup_record(row.id, session=session)
                if cleanup is None:
                    logger.info("[mount-cleanup] deleted row %s has no mount path", row.id)
                    continue
                cleanup_id = cleanup.id
                machine_id = cleanup.machine_id
                container_name = cleanup.container_name
                mount_path = cleanup.mount_path
            # 管辖范畴：机器可达且非维护才发清理请求（清理动作需要 Node 在场；
            # 否则每轮对不在范畴内的机器重复请求，等回到范畴内的下一轮再清）。
            # 范畴外是职责划分而非门禁——静默跳过，不留审计也不留常规日志。
            if not machine_in_scope(machine_id):
                continue
            # 动作逻辑统一在 container_module.mount_cleanup（幂等 / 请求 / mark_cleaned / op-log）
            result = clean_mount_path(cleanup_id, trigger="auto_mount_cleanup")
            if result.get("cleaned"):
                logger.info(
                    "[mount-cleanup] cleaned deleted row %s: container=%s path=%s",
                    row.id,
                    container_name,
                    mount_path,
                )
        except Exception as e:
            logger.error("[mount-cleanup] failed deleted row %s: %s", row.id, e)


def start_mount_cleanup_scheduler(interval_seconds: int | None = None) -> threading.Thread | None:
    """启动后台定期 mount 清理任务（由 create_app 背景任务统一入口调用）。
    仅在 settings: container.mount_cleanup_enabled=true 时启动。"""
    if not settings_tasks.get_container_mount_cleanup_enabled():
        return None
    if interval_seconds is None:
        interval_seconds = settings_tasks.get_container_mount_cleanup_interval_seconds()

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
