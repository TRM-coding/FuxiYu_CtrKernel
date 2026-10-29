"""operation_log repo 读写与筛选/分页测试（真实隔离数据库）。"""

from ...repositories import operation_log_repo
from ...constant import OperationType


def _seed(db_session):
    operation_log_repo.write(
        operator_user_id=1, operation=OperationType.CREATE_CONTAINER.value,
        target_type="container", target_id=10, detail={"name": "a"}, success=True,
        session=db_session,
    )
    operation_log_repo.write(
        operator_user_id=2, operation=OperationType.START_CONTAINER.value,
        target_type="container", target_id=20, detail={"name": "b"}, success=True,
        session=db_session,
    )
    operation_log_repo.write(
        operator_user_id=None, operation=OperationType.PAUSE_CONTAINER.value,
        target_type="container", target_id=30, detail={}, success=False, error_reason="disk_limit",
        session=db_session,
    )


def test_write_and_list_desc_order(db_session):
    _seed(db_session)
    rows, total_pages = operation_log_repo.list_logs(page=1, page_size=10, session=db_session)
    assert len(rows) == 3
    assert total_pages == 1
    # 新的在前
    assert [r.target_id for r in rows] == [30, 20, 10]


def test_list_filter_by_operator_and_operation(db_session):
    _seed(db_session)
    rows, _ = operation_log_repo.list_logs(operator_user_id=2, session=db_session)
    assert [r.operation for r in rows] == ["start_container"]

    rows, _ = operation_log_repo.list_logs(operation=OperationType.PAUSE_CONTAINER.value, session=db_session)
    assert len(rows) == 1
    assert rows[0].operator_user_id is None
    assert rows[0].success is False


def test_list_filter_by_success(db_session):
    _seed(db_session)
    rows, _ = operation_log_repo.list_logs(success=False, session=db_session)
    assert len(rows) == 1
    rows, _ = operation_log_repo.list_logs(success=True, session=db_session)
    assert len(rows) == 2


def _seed_mixed(db_session):
    operation_log_repo.write(
        operator_user_id=1, operation=OperationType.CREATE_CONTAINER.value,
        target_type="container", target_id=10, detail={"name": "a"}, success=True,
        session=db_session,
    )
    operation_log_repo.write(
        operator_user_id=2, operation=OperationType.UPDATE_MACHINE.value,
        target_type="machine", target_id=20, detail={"name": "m"}, success=True,
        session=db_session,
    )
    operation_log_repo.write(
        operator_user_id=1, operation=OperationType.CHANGE_PASSWORD.value,
        target_type="user", target_id=30, detail={"username": "u"}, success=False,
        error_reason="old_password_incorrect", session=db_session,
    )
    operation_log_repo.write(
        operator_user_id=None, operation=OperationType.PAUSE_CONTAINER.value,
        target_type="container", target_id=40, detail={}, success=False,
        error_reason="disk_limit", session=db_session,
    )


def test_list_filter_by_multiple_target_types_is_or(db_session):
    _seed_mixed(db_session)

    rows, _ = operation_log_repo.list_logs(
        target_type=["container", "machine"], page_size=10, session=db_session,
    )

    assert {row.target_type for row in rows} == {"container", "machine"}
    assert [row.target_id for row in rows] == [40, 20, 10]
    assert all(row.target_type != "user" for row in rows)


def test_list_multiple_target_types_combine_with_other_filters_as_and(db_session):
    _seed_mixed(db_session)

    rows, total_pages = operation_log_repo.list_logs(
        target_type=["container", "machine"],
        operator_user_id=1,
        success=True,
        page_size=10,
        session=db_session,
    )

    assert [row.target_id for row in rows] == [10]
    assert total_pages == 1


def test_list_single_string_target_type_remains_compatible(db_session):
    _seed_mixed(db_session)

    rows, _ = operation_log_repo.list_logs(
        target_type="machine", page_size=10, session=db_session,
    )

    assert [row.target_id for row in rows] == [20]


def test_list_empty_target_type_values_do_not_filter(db_session):
    _seed_mixed(db_session)

    for empty in (None, "", [], ["", None]):
        rows, _ = operation_log_repo.list_logs(
            target_type=empty, page_size=10, session=db_session,
        )
        assert len(rows) == 4


def test_list_pagination_uses_multi_target_type_filtered_total(db_session):
    _seed_mixed(db_session)

    first, total_pages = operation_log_repo.list_logs(
        target_type=["container", "machine"], page=1, page_size=2, session=db_session,
    )
    second, second_total_pages = operation_log_repo.list_logs(
        target_type=["container", "machine"], page=2, page_size=2, session=db_session,
    )

    assert total_pages == 2
    assert second_total_pages == 2
    assert [row.target_id for row in first] == [40, 20]
    assert [row.target_id for row in second] == [10]


def test_list_pagination(db_session):
    _seed(db_session)
    rows, total_pages = operation_log_repo.list_logs(page=1, page_size=2, session=db_session)
    assert len(rows) == 2
    assert total_pages == 2
    rows, total_pages = operation_log_repo.list_logs(page=2, page_size=2, session=db_session)
    assert len(rows) == 1


def test_list_time_range(db_session):
    from datetime import datetime, timedelta

    _seed(db_session)
    now = datetime.utcnow()
    rows, _ = operation_log_repo.list_logs(start=(now - timedelta(hours=1)).isoformat(), end=(now + timedelta(hours=1)).isoformat(), session=db_session)
    assert len(rows) == 3
    rows, _ = operation_log_repo.list_logs(start=(now + timedelta(hours=1)).isoformat(), session=db_session)
    assert len(rows) == 0


def test_serialize_shape(db_session):
    _seed(db_session)
    rows, _ = operation_log_repo.list_logs(page=1, page_size=1, session=db_session)
    d = operation_log_repo.serialize(rows[0])
    assert set(d.keys()) == {"id", "operator_user_id", "operation", "target_type",
                             "target_id", "detail", "success", "error_reason", "created_at"}
    assert d["success"] is False
    assert d["created_at"] is not None


def test_stats_aggregation(db_session):
    from datetime import datetime

    _seed(db_session)
    s = operation_log_repo.stats(session=db_session)
    assert s["total"] == 3
    assert s["succeeded"] == 2
    assert s["failed"] == 1
    assert s["by_operation"]["create_container"] == 1
    assert s["by_operation"]["pause_container"] == 1
    assert s["by_target_type"]["container"] == 3

    # 按天聚合（时间轴用）
    today = datetime.utcnow().strftime("%Y-%m-%d")
    assert s["by_day"][today]["success"] == 2
    assert s["by_day"][today]["failed"] == 1
