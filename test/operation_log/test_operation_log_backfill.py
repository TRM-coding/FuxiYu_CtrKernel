"""containers.created_at 存量回填（从 op log create_container 反查，2026-09）。"""

from datetime import timedelta

from ... import _backfill_container_created_at
from ... import extensions
from ...models.operation_log import OperationLog
from ...constant import OperationType
from ..factories import create_container


def test_backfill_takes_max_of_successful_create_logs(db_session):
    """id 复用 N 次 → created_at = 最近一次成功 create 日志（MAX + success=1 过滤）。"""
    from datetime import datetime

    container = create_container(name="bf_c1")

    def _log(op, when, ok):
        db_session.add(OperationLog(
            operator_user_id=1, operation=OperationType[op].value,
            target_type="container", target_id=container.id,
            detail={}, success=ok, created_at=when,
        ))

    # 上一代创建（成功，旧时间）
    _log("CREATE_CONTAINER", datetime.utcnow() - timedelta(days=2), True)
    # 失败尝试（时间最新，但 success=0 → 不取）
    _log("CREATE_CONTAINER", datetime.utcnow() - timedelta(hours=1), False)
    # 当前实体创建（成功，最近）
    latest = datetime.utcnow() - timedelta(minutes=10)
    _log("CREATE_CONTAINER", latest, True)
    db_session.commit()
    assert container.created_at is None

    _backfill_container_created_at(extensions.engine)

    db_session.expire_all()
    c = db_session.get(type(container), container.id)
    assert c.created_at is not None
    # MAX(success=1) = 当前实体创建时刻（失败那条被过滤）
    assert abs((c.created_at - latest).total_seconds()) < 1


def test_backfill_idempotent_and_skips_without_create_logs(db_session):
    """已有 created_at 不动；无 create 日志的容器维持 NULL。"""
    from datetime import datetime

    with_anchor = create_container(name="bf_c2")
    with_anchor.created_at = datetime.utcnow() - timedelta(days=1)
    no_log = create_container(name="bf_c3")
    db_session.commit()

    _backfill_container_created_at(extensions.engine)

    db_session.expire_all()
    assert db_session.get(type(with_anchor), with_anchor.id).created_at is not None
    assert db_session.get(type(no_log), no_log.id).created_at is None
