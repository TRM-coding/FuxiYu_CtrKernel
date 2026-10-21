from __future__ import annotations

import datetime
import logging
import time

from ....extensions import session_scope
from ....repositories import containers_repo

logger = logging.getLogger(__name__)

# 名称线索只能表达“无法确认”，不能表达“确认已删除”。两条入口共用本函数：
# - delete_frame：Node 显式 delete 帧（只带名字，没有 Docker 对象 ID）
# - snapshot_missing：非空状态快照中缺少某个有效记录
SOURCE_DELETE_FRAME = "delete_frame"
SOURCE_SNAPSHOT_MISSING = "snapshot_missing"
_VANISH_SOURCES = {SOURCE_DELETE_FRAME, SOURCE_SNAPSHOT_MISSING}

# 同一机器/容器/来源的线索在快照心跳下每 5 秒就会出现一次；诊断日志节流到
# 60 秒一条，DB 标记本身仍按现状幂等更新。
_VANISH_LOG_INTERVAL_SECONDS = 60.0
_last_vanish_log: dict[tuple[int, int, str], float] = {}


def _should_log_vanish(machine_id: int, container_id: int, source: str) -> bool:
    key = (int(machine_id), int(container_id), source)
    now = time.monotonic()
    last = _last_vanish_log.get(key, 0.0)
    if now - last < _VANISH_LOG_INTERVAL_SECONDS:
        return False
    _last_vanish_log[key] = now
    return True


def _clear_vanish_log_state() -> None:
    """测试用：清空进程内节流状态；生产路径不调用。"""

    _last_vanish_log.clear()


def _handle_container_vanish(
    container_name: str,
    machine_id: int | None = None,
    *,
    source: str = SOURCE_DELETE_FRAME,
) -> bool:
    """把名称消失线索标成待核实，不软删、不清绑定、不写成功删除审计。

    容器名在单机内才唯一，查找必须限定在发送机器内。历史已软删行（is_valid=false）
    不会被本函数找到或修改：迟到线索不能复活/改写已失效记录，也不能给同名新代
    贴旧代身份。返回是否实际更新了待核实标记。
    """

    if source not in _VANISH_SOURCES:
        logger.warning(
            "container vanish clue: unknown source %r machine_id=%s container=%r (skip)",
            source, machine_id, container_name,
        )
        return False
    if machine_id is None:
        logger.warning(
            "container vanish clue: machine_id missing source=%s container=%r (refuse)",
            source, container_name,
        )
        return False
    if not container_name:
        logger.warning("container vanish clue: empty container name machine_id=%s (skip)", machine_id)
        return False

    try:
        with session_scope() as session:
            container_id = containers_repo.get_id_by_name_machine(
                container_name, machine_id, session=session,
            )
            if container_id is None:
                logger.debug(
                    "container vanish clue: no active record source=%s machine_id=%s container=%r (skip)",
                    source, machine_id, container_name,
                )
                return False
            container = containers_repo.get_by_id(container_id, session=session)
            if container is None:
                return False

            observed_at = datetime.datetime.utcnow()
            previous_source = container.status_source
            previous_since = container.status_unknown_since
            since = previous_since or observed_at
            changed = previous_source != source or previous_since is None
            if changed:
                containers_repo.update_container(
                    container.id,
                    status_unknown_since=since,
                    status_source=source,
                    session=session,
                )
            container_id = container.id
            container_name = container.name
    except Exception as exc:
        logger.warning(
            "container vanish clue failed: source=%s machine_id=%s container=%r error=%s",
            source, machine_id, container_name, exc,
        )
        return False

    if _should_log_vanish(machine_id, container_id, source):
        logger.warning(
            "container vanish clue: source=%s machine_id=%s container_id=%s container=%s "
            "observed_at=%s status_unknown_since=%s previous_source=%s changed=%s",
            source, machine_id, container_id, container_name,
            observed_at.isoformat(), since.isoformat(), previous_source, changed,
        )
    return changed
