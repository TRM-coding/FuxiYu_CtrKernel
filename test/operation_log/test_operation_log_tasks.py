"""operation_log 服务层：目标关联（target_name / root_owner）测试。"""

from datetime import datetime

from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from ...repositories import operation_log_repo
from ...services import operation_log_tasks
from ...services.operation_log_tasks import list_operation_logs, operation_log_stats
from ...constant import OperationType, ROLE
from ..factories import create_user, create_machine, create_container, bind_user_container
from ...models.auth_group import AuthGroup
from ...models.image import Image
from ...models.operation_log import OperationLog
from ...services.operation_log_tasks import log_failure, log_success


def test_deleted_container_keeps_owner_without_navigation(db_session):
    user = create_user(username="retained_owner")
    container = create_container(machine=create_machine(), name="retained")
    bind_user_container(user, container, role="ROOT")
    container.is_valid = False
    db_session.commit()
    log_success(operation=OperationType.DELETE_CONTAINER, target_type="container", target_id=container.id)
    log = list_operation_logs()["logs"][0]
    assert log["target_name"] is None
    assert log["target_display_name"] == "retained"
    assert log["root_owner"] == "retained_owner"


def test_each_repeated_failure_is_audited(db_session, monkeypatch, caplog):
    from ...services import operation_log_tasks

    alerts = []
    monkeypatch.setattr(operation_log_tasks, "_maybe_raise_alert", lambda **kwargs: alerts.append(kwargs))
    args = dict(operation=OperationType.SEND_CLEANUP_REMINDER, target_type="container", target_id=999)
    detail = {"recipient": "owner@example.test", "cleanup_at": "2026-09-12T00:00:00"}
    for _ in range(3):
        log_failure(**args, detail=detail, error_reason="smtp")
    logs = db_session.scalars(select(OperationLog).order_by(OperationLog.id)).all()
    assert len(logs) == 3
    assert all(not log.success and log.error_reason == "smtp" for log in logs)
    assert len(alerts) == 3
    assert sum("op failed:" in record.message for record in caplog.records) == 3


def test_manual_failures_are_not_suppressed(db_session):
    for _ in range(2):
        log_failure(operation=OperationType.DELETE_CONTAINER, target_type="container_mount_cleanup",
                    target_id=999, error_reason="not_found")
    assert len(db_session.scalars(select(OperationLog)).all()) == 2


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
    # 目标已删除：查不到也不报错，优先使用日志中保存的资源名称
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
    assert by_target_id["999999"]["target_display_name"] == "ghost"


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


def test_list_enriches_every_supported_target_type(db_session):
    """批量化必须保持各 target_type 的旧有回填口径。"""

    machine = create_machine(machine_name="batch-machine")
    owner = create_user(username="batch-owner")
    container = create_container(machine=machine, name="batch-container")
    bind_user_container(owner, container, role=ROLE.ROOT)
    image = Image(name="batch-image", base_image="ubuntu:24.04", dockerfile_body="")
    group = AuthGroup(name="batch-group", description="")
    db_session.add_all([image, group])
    db_session.commit()

    entries = [
        ("machine", machine.id, {}),
        ("container", container.id, {}),
        ("user", owner.id, {}),
        ("image", image.id, {}),
        ("rbac_group", group.id, {}),
        ("system_setting", 0, {"setting_keys": ["container.cleanup_after_days", "announcement.mail_interval_seconds"]}),
        ("container_mount_cleanup", 0, {"name": "mount-history"}),
    ]
    for target_type, target_id, detail in entries:
        operation_log_repo.write(
            session=db_session,
            operator_user_id=None,
            operation=OperationType.UPDATE_SETTING.value,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            success=True,
        )
    db_session.commit()

    result = list_operation_logs(page=1, page_size=10)
    by_type = {row["target_type"]: row for row in result["logs"]}

    assert by_type["machine"]["target_name"] == "batch-machine"
    assert by_type["container"]["target_name"] == "batch-container"
    assert by_type["container"]["root_owner"] == "batch-owner"
    assert by_type["user"]["target_name"] == "batch-owner"
    assert by_type["image"]["target_name"] == "batch-image"
    assert by_type["rbac_group"]["target_name"] == "batch-group"
    assert by_type["system_setting"]["target_name"] == (
        "container.cleanup_after_days, announcement.mail_interval_seconds"
    )
    assert by_type["container_mount_cleanup"]["target_name"] == "mount-history"


def test_target_enrichment_query_count_does_not_grow_per_row(db_session):
    """25 行容器日志的关联查询必须批量预取，而不是每行开 session 查三次。"""

    machine = create_machine(machine_name="batch-query-machine")
    for index in range(25):
        owner = create_user(username=f"batch-query-owner-{index}")
        container = create_container(machine=machine, name=f"batch-query-container-{index}")
        bind_user_container(owner, container, role=ROLE.ROOT)
        operation_log_repo.write(
            session=db_session,
            operator_user_id=None,
            operation=OperationType.CREATE_CONTAINER.value,
            target_type="container",
            target_id=container.id,
            detail={"name": container.name},
            success=True,
        )
    db_session.commit()

    statements: list[str] = []

    def _record_select(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", _record_select)
    try:
        result = list_operation_logs(page=1, page_size=100)
    finally:
        event.remove(engine, "before_cursor_execute", _record_select)

    assert len(result["logs"]) == 25
    assert all(row["target_name"].startswith("batch-query-container-") for row in result["logs"])
    assert all(row["root_owner"].startswith("batch-query-owner-") for row in result["logs"])
    # count + 分页 + containers + bindings + users：不随 25 行增长。
    assert len(statements) <= 8, statements


def test_target_type_query_failure_only_blanks_that_type(db_session, monkeypatch):
    """单类批量预取失败时主日志仍返回，其它目标类型照常回填。"""

    machine = create_machine(machine_name="failed-machine")
    owner = create_user(username="surviving-owner")
    container = create_container(machine=machine, name="surviving-container")
    bind_user_container(owner, container, role=ROLE.ROOT)
    for target_type, target_id in (("machine", machine.id), ("container", container.id)):
        operation_log_repo.write(
            session=db_session,
            operator_user_id=None,
            operation=OperationType.UPDATE_SETTING.value,
            target_type=target_type,
            target_id=target_id,
            detail={},
            success=True,
        )
    db_session.commit()

    original_select = operation_log_tasks.select

    def failing_select(model):
        if model is operation_log_tasks.Machine:
            raise RuntimeError("machine query failed")
        return original_select(model)

    monkeypatch.setattr(operation_log_tasks, "select", failing_select)

    result = list_operation_logs(page=1, page_size=10)
    by_type = {row["target_type"]: row for row in result["logs"]}

    assert by_type["machine"]["target_name"] is None
    assert by_type["container"]["target_name"] == "surviving-container"
    assert by_type["container"]["root_owner"] == "surviving-owner"


def test_user_query_failure_blanks_root_owner_only(db_session, monkeypatch):
    """root_owner 依赖 User；User 批量读取失败时仅该联合字段和用户目标名称为空。"""

    owner = create_user(username="failed-user-owner")
    machine = create_machine(machine_name="user-failure-machine")
    container = create_container(machine=machine, name="user-failure-container")
    bind_user_container(owner, container, role=ROLE.ROOT)
    image = Image(name="user-failure-image", base_image="ubuntu:24.04", dockerfile_body="")
    db_session.add(image)
    db_session.commit()

    for target_type, target_id in (
        ("container", container.id),
        ("user", owner.id),
        ("image", image.id),
    ):
        operation_log_repo.write(
            session=db_session,
            operator_user_id=None,
            operation=OperationType.UPDATE_SETTING.value,
            target_type=target_type,
            target_id=target_id,
            detail={},
            success=True,
        )
    db_session.commit()

    original_select = operation_log_tasks.select

    def failing_select(model):
        if model is operation_log_tasks.User:
            raise RuntimeError("user query failed")
        return original_select(model)

    monkeypatch.setattr(operation_log_tasks, "select", failing_select)

    result = list_operation_logs(page=1, page_size=10)
    by_type = {row["target_type"]: row for row in result["logs"]}

    assert by_type["container"]["target_name"] == "user-failure-container"
    assert by_type["container"]["root_owner"] is None
    assert by_type["user"]["target_name"] is None
    # User 之后的类型仍使用独立 session 正常回填。
    assert by_type["image"]["target_name"] == "user-failure-image"


def test_user_dbapi_failure_does_not_poison_later_type_sessions(db_session):
    """User 查询触发 DBAPI/事务级异常后，后续类型仍能独立查询并回填。"""

    owner = create_user(username="dbapi-owner")
    machine = create_machine(machine_name="dbapi-machine")
    container = create_container(machine=machine, name="dbapi-container")
    bind_user_container(owner, container, role=ROLE.ROOT)
    image = Image(name="dbapi-image", base_image="ubuntu:24.04", dockerfile_body="")
    db_session.add(image)
    db_session.commit()

    for target_type, target_id in (("container", container.id), ("image", image.id)):
        operation_log_repo.write(
            session=db_session,
            operator_user_id=None,
            operation=OperationType.UPDATE_SETTING.value,
            target_type=target_type,
            target_id=target_id,
            detail={},
            success=True,
        )
    db_session.commit()

    engine = db_session.get_bind()

    def _fail_user_select(conn, cursor, statement, parameters, context, executemany):
        if "FROM USERS" in statement.upper():
            raise OperationalError(statement, parameters, RuntimeError("simulated DB failure"))

    event.listen(engine, "before_cursor_execute", _fail_user_select)
    try:
        result = list_operation_logs(page=1, page_size=10)
    finally:
        event.remove(engine, "before_cursor_execute", _fail_user_select)

    by_type = {row["target_type"]: row for row in result["logs"]}

    assert by_type["container"]["target_name"] == "dbapi-container"
    assert by_type["container"]["root_owner"] is None
    # User 失败后仍能新开 session 读取镜像，证明失败事务没有毒化后续类型。
    assert by_type["image"]["target_name"] == "dbapi-image"
