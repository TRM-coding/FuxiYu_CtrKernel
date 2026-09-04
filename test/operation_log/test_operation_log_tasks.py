"""operation_log 服务层：目标关联（target_name / root_owner）测试。"""

from datetime import datetime

from ...repositories import operation_log_repo
from ...services.operation_log_tasks import list_operation_logs, operation_log_stats
from ...constant import OperationType
from ..factories import create_user, create_machine, create_container, bind_user_container


def test_list_enriches_container_name_and_root_owner(db_session):
    user = create_user(username="alice")
    machine = create_machine(machine_name="gpu-01")
    container = create_container(machine=machine, name="c1")
    bind_user_container(user, container, role="ROOT")

    operation_log_repo.write(
        session=db_session,
        operator_user_id=user.id,
        operation=OperationType.CREATE_CONTAINER.value,
        target_type="container",
        target_id=container.id,
        detail={"name": "c1"},
        success=True,
    )
    db_session.commit()

    result = list_operation_logs(page=1, page_size=10)
    log = result["logs"][0]
    assert log["target_name"] == "c1"
    assert log["root_owner"] == "alice"


def test_list_enriches_machine_name(db_session):
    machine = create_machine(machine_name="gpu-01")
    operation_log_repo.write(
        session=db_session,
        operator_user_id=None,
        operation=OperationType.UPDATE_MACHINE.value,
        target_type="machine",
        target_id=machine.id,
        detail={"before": {"machine_status": "online"}, "after": {"machine_status": "offline"}},
        success=True,
    )
    db_session.commit()

    result = list_operation_logs(page=1, page_size=10)
    log = result["logs"][0]
    assert log["target_name"] == "gpu-01"
    assert log["root_owner"] is None


def test_list_enriches_user_name_and_tolerates_deleted_target(db_session):
    user = create_user(username="bob")
    operation_log_repo.write(
        session=db_session,
        operator_user_id=user.id,
        operation=OperationType.CHANGE_PASSWORD.value,
        target_type="user",
        target_id=user.id,
        detail={},
        success=True,
    )
    # 目标已删除：查不到也不报错，target_name 保持 None
    operation_log_repo.write(
        session=db_session,
        operator_user_id=None,
        operation=OperationType.START_CONTAINER.value,
        target_type="container",
        target_id=999999,
        detail={"name": "ghost"},
        success=True,
    )
    db_session.commit()

    result = list_operation_logs(page=1, page_size=10)
    by_target_id = {str(r["target_id"]): r for r in result["logs"]}
    assert by_target_id[str(user.id)]["target_name"] == "bob"
    assert by_target_id["999999"]["target_name"] is None


def test_list_window_accepts_local_times_with_offset(db_session):
    """前端按本地（北京时间）所见即所得传窗口 + 偏移量：后端解析成 UTC 过滤。

    北京时间周日 00:03 创建 → 库内 naive UTC 为前一天 16:03。
    不传偏移时窗口按 naive UTC 理解，查不到；传 +480 后落入窗口。
    """
    machine = create_machine(machine_name="gpu-01")
    container = create_container(machine=machine, name="testingcontainer")
    row = operation_log_repo.write(
        session=db_session,
        operator_user_id=None,
        operation=OperationType.CREATE_CONTAINER.value,
        target_type="container",
        target_id=container.id,
        detail={"name": "testingcontainer"},
        success=True,
    )
    row.created_at = datetime(2026, 8, 16, 16, 3, 33)
    db_session.commit()

    without = list_operation_logs(
        page=1, page_size=10,
        start="2026-08-17T00:00:00", end="2026-08-23T23:59:59",
    )
    assert len(without["logs"]) == 0

    with_offset = list_operation_logs(
        page=1, page_size=10,
        start="2026-08-17T00:00:00", end="2026-08-23T23:59:59",
        tz_offset_minutes=480,
    )
    assert len(with_offset["logs"]) == 1
    assert with_offset["logs"][0]["target_name"] == "testingcontainer"


def test_stats_buckets_day_by_offset(db_session):
    """by_day 分桶日随偏移量：北京时间 8/17 00:03 的事件应计入 8/17 的桶（绿墙当天格子）。"""
    row = operation_log_repo.write(
        session=db_session,
        operator_user_id=None,
        operation=OperationType.START_CONTAINER.value,
        target_type="container",
        target_id=1,
        detail={},
        success=True,
    )
    row.created_at = datetime(2026, 8, 16, 16, 3, 33)
    db_session.commit()

    utc_buckets = operation_log_stats(
        start="2026-08-16T00:00:00", end="2026-08-18T00:00:00",
    )
    assert utc_buckets["by_day"]["2026-08-16"]["success"] == 1
    assert "2026-08-17" not in utc_buckets["by_day"]

    bj_buckets = operation_log_stats(
        start="2026-08-16T00:00:00", end="2026-08-18T00:00:00",
        tz_offset_minutes=480,
    )
    assert bj_buckets["by_day"]["2026-08-17"]["success"] == 1


def test_list_skips_identity_mapping_for_previous_generation_log(db_session):
    """id 复用（2026-09）：日志早于容器 created_at = 上一代容器日志 → 不映射名称/超管。"""
    from datetime import timedelta

    from ...models.operation_log import OperationLog

    user = create_user(username="alice")
    machine = create_machine(machine_name="gpu-01")
    container = create_container(machine=machine, name="c2")
    bind_user_container(user, container, role="ROOT")
    container.created_at = datetime.utcnow() - timedelta(minutes=5)
    db_session.commit()

    def _log(op, when, name):
        db_session.add(OperationLog(
            operator_user_id=user.id, operation=OperationType[op].value,
            target_type="container", target_id=container.id,
            detail={"name": name}, success=True, created_at=when,
        ))

    # 上一代容器（同 id）的日志：早于当前容器创建
    _log("DELETE_CONTAINER", datetime.utcnow() - timedelta(hours=1), "old_c2")
    # 当前容器自己的日志：晚于创建
    _log("START_CONTAINER", datetime.utcnow(), "c2")
    db_session.commit()

    result = list_operation_logs(page=1, page_size=10)
    by_op = {log["operation"]: log for log in result["logs"]}

    old = by_op[OperationType.DELETE_CONTAINER.value]
    assert old["target_name"] is None
    assert old["root_owner"] is None

    cur = by_op[OperationType.START_CONTAINER.value]
    assert cur["target_name"] == "c2"
    assert cur["root_owner"] == "alice"
