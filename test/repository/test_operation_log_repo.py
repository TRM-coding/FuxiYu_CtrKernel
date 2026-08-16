"""operation_log repo 读写与筛选/分页测试（真实隔离数据库）。"""

from ...repositories import operation_log_repo
from ...constant import OperationType


def _seed():
    operation_log_repo.write(
        operator_user_id=1, operation=OperationType.CREATE_CONTAINER.value,
        target_type="container", target_id=10, detail={"name": "a"}, success=True,
    )
    operation_log_repo.write(
        operator_user_id=2, operation=OperationType.START_CONTAINER.value,
        target_type="container", target_id=20, detail={"name": "b"}, success=True,
    )
    operation_log_repo.write(
        operator_user_id=None, operation=OperationType.PAUSE_CONTAINER.value,
        target_type="container", target_id=30, detail={}, success=False, error_reason="disk_limit",
    )


def test_write_and_list_desc_order(db_session):
    _seed()
    rows, total_pages = operation_log_repo.list_logs(page=1, page_size=10)
    assert len(rows) == 3
    assert total_pages == 1
    # 新的在前
    assert [r.target_id for r in rows] == [30, 20, 10]


def test_list_filter_by_operator_and_operation(db_session):
    _seed()
    rows, _ = operation_log_repo.list_logs(operator_user_id=2)
    assert [r.operation for r in rows] == ["start_container"]

    rows, _ = operation_log_repo.list_logs(operation=OperationType.PAUSE_CONTAINER.value)
    assert len(rows) == 1
    assert rows[0].operator_user_id is None
    assert rows[0].success is False


def test_list_filter_by_success(db_session):
    _seed()
    rows, _ = operation_log_repo.list_logs(success=False)
    assert len(rows) == 1
    rows, _ = operation_log_repo.list_logs(success=True)
    assert len(rows) == 2


def test_list_pagination(db_session):
    _seed()
    rows, total_pages = operation_log_repo.list_logs(page=1, page_size=2)
    assert len(rows) == 2
    assert total_pages == 2
    rows, total_pages = operation_log_repo.list_logs(page=2, page_size=2)
    assert len(rows) == 1


def test_list_time_range(db_session):
    from datetime import datetime, timedelta

    _seed()
    now = datetime.utcnow()
    rows, _ = operation_log_repo.list_logs(start=(now - timedelta(hours=1)).isoformat(), end=(now + timedelta(hours=1)).isoformat())
    assert len(rows) == 3
    rows, _ = operation_log_repo.list_logs(start=(now + timedelta(hours=1)).isoformat())
    assert len(rows) == 0


def test_serialize_shape(db_session):
    _seed()
    rows, _ = operation_log_repo.list_logs(page=1, page_size=1)
    d = operation_log_repo.serialize(rows[0])
    assert set(d.keys()) == {"id", "operator_user_id", "operation", "target_type",
                             "target_id", "detail", "success", "error_reason", "created_at"}
    assert d["success"] is False
    assert d["created_at"] is not None


def test_stats_aggregation(db_session):
    _seed()
    s = operation_log_repo.stats()
    assert s["total"] == 3
    assert s["succeeded"] == 2
    assert s["failed"] == 1
    assert s["by_operation"]["create_container"] == 1
    assert s["by_operation"]["pause_container"] == 1
    assert s["by_target_type"]["container"] == 3
