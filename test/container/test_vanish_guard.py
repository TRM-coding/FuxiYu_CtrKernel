"""名称消失线索的保守处理：只标待核实，不软删有效记录。

覆盖：快照缺席 / delete 帧、创建与运行态、同机多容器、跨机同名、旧代删帧
晚于同名新建、主动删除/cleanup 与迟到线索的两种交错、正向恢复与过渡态保留、
结构化诊断与节流、有效状态展示。所有用例只使用隔离 SQLite 与 mock Node。
"""

import logging

import pytest
from sqlalchemy import select

from ...constant import ContainerStatus, OperationType
from ...models.containers import Container
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...models.operation_log import OperationLog
from ...repositories import (
    containers_repo,
    long_term_container_repo,
    usercontainer_repo,
)
from ...services import container_tasks
from ...services.container_module import node_comms
from ...services.container_module.node_comms_modules import deletion as vanish
from ..factories import (
    create_container,
    create_container_graph,
    create_machine,
)
from .conftest import NODE_REMOVE_SUCCESS


@pytest.fixture(autouse=True)
def _reset_vanish_throttle():
    vanish._clear_vanish_log_state()
    yield
    vanish._clear_vanish_log_state()


def _row(db_session, container_id: int):
    db_session.expire_all()
    return containers_repo.get_by_id(container_id, session=db_session, include_invalid=True)


def _delete_logs(db_session, container_id: int):
    return db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == OperationType.DELETE_CONTAINER,
            OperationLog.target_id == container_id,
        )
    ).all()


def _snapshots(db_session, container_id: int):
    return db_session.scalars(
        select(DeletedContainerRestoreSnapshot).where(
            DeletedContainerRestoreSnapshot.original_container_id == container_id,
        )
    ).all()


@pytest.mark.parametrize("status", [ContainerStatus.CREATING, ContainerStatus.ONLINE])
def test_snapshot_missing_marks_pending_and_keeps_record_binding_and_long_term(
    app, db_session, status,
):
    root, machine, container = create_container_graph()
    container.container_status = status
    long_term_container_repo.add(container.id, created_by_user_id=root.id, session=db_session)
    other = create_container(machine=machine, name="still_there", status=ContainerStatus.ONLINE)
    db_session.commit()

    result = node_comms.apply_container_status_snapshot(
        {other.name: {"status": "online"}}, machine.id,
    )

    db_session.expire_all()
    row = _row(db_session, container.id)
    assert result["vanished"] == 1
    assert row is not None and row.is_valid is True
    assert row.id == container.id
    assert row.status_source == "snapshot_missing"
    assert row.status_unknown_since is not None
    assert row.deleted_trigger is None
    bindings = usercontainer_repo.get_container_bindings(container.id, session=db_session)
    assert [b["user_id"] for b in bindings] == [root.id]
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True
    assert _delete_logs(db_session, container.id) == []
    assert _snapshots(db_session, container.id) == []


def test_snapshot_missing_only_marks_absent_container_same_machine(app, db_session):
    _root, machine, present = create_container_graph()
    _r2, _m2, absent = create_container_graph(root_user=_root, machine=machine)

    node_comms.apply_container_status_snapshot(
        {present.name: {"status": "online"}}, machine.id,
    )

    assert _row(db_session, present.id).status_source is None
    assert _row(db_session, absent.id).status_source == "snapshot_missing"


def test_snapshot_missing_does_not_cross_machine_same_name(app, db_session):
    machine_a = create_machine(machine_name="scope-a")
    machine_b = create_machine(machine_name="scope-b")
    ca = create_container(machine=machine_a, name="same_name")
    cb = create_container(machine=machine_b, name="same_name")
    keep_b = create_container(machine=machine_b, name="keep_b")
    db_session.commit()

    node_comms.apply_container_status_snapshot(
        {keep_b.name: {"status": "online"}}, machine_a.id,
    )

    assert _row(db_session, ca.id).status_source == "snapshot_missing"
    assert _row(db_session, cb.id).status_source is None
    assert _row(db_session, ca.id).is_valid is True
    assert _row(db_session, cb.id).is_valid is True


def test_delete_frame_marks_current_record_without_soft_delete(app, db_session):
    _root, machine, container = create_container_graph()

    changed = node_comms._handle_container_vanish(container.name, machine.id)

    row = _row(db_session, container.id)
    assert changed is True
    assert row.is_valid is True
    assert row.status_source == "delete_frame"
    assert row.status_unknown_since is not None
    assert _delete_logs(db_session, container.id) == []
    assert _snapshots(db_session, container.id) == []


def test_old_delete_frame_after_same_name_recreate_marks_new_record_only(
    app, db_session, mock_node_send,
):
    root, machine, old = create_container_graph()
    old_id = old.id
    mock_node_send(NODE_REMOVE_SUCCESS)
    container_tasks.remove_container(old_id, operator_user_id=root.id)
    new = create_container(machine=machine, name=old.name, status=ContainerStatus.ONLINE)
    db_session.commit()

    node_comms._handle_container_vanish(old.name, machine.id)

    db_session.expire_all()
    old_row = _row(db_session, old_id)
    new_row = _row(db_session, new.id)
    assert old_row.is_valid is False
    assert old_row.deleted_trigger == "api"
    assert new_row.is_valid is True
    assert new_row.status_source == "delete_frame"
    assert len(_snapshots(db_session, old_id)) == 1
    assert _snapshots(db_session, new.id) == []
    assert len(_delete_logs(db_session, old_id)) == 1
    assert _delete_logs(db_session, new.id) == []


def test_late_vanish_clue_after_api_delete_does_not_touch_invalid_row(
    app, db_session, mock_node_send,
):
    root, machine, container = create_container_graph()
    mock_node_send(NODE_REMOVE_SUCCESS)
    container_tasks.remove_container(container.id, operator_user_id=root.id)
    db_session.expire_all()
    before = _row(db_session, container.id)
    deleted_at = before.deleted_at
    trigger = before.deleted_trigger
    snapshot_ids = [row.id for row in _snapshots(db_session, container.id)]
    log_count = len(_delete_logs(db_session, container.id))

    node_comms._handle_container_vanish(container.name, machine.id, source="delete_frame")
    node_comms._handle_container_vanish(container.name, machine.id, source="snapshot_missing")
    db_session.expire_all()

    after = _row(db_session, container.id)
    assert after.is_valid is False
    assert after.deleted_at == deleted_at
    assert after.deleted_trigger == trigger
    assert after.status_source is None
    assert [row.id for row in _snapshots(db_session, container.id)] == snapshot_ids
    assert len(_delete_logs(db_session, container.id)) == log_count


def test_pending_clue_exposes_existing_remove_denial_without_mutation(
    app, db_session, mock_node_send,
):
    """记录现有缺口：待核实派生为 status_unknown 后，既有 remove 矩阵会拒绝。

    本变更不暗中放宽 unknown 删除，也不新增接口；这里只锁定“拒绝发生在动作前、
    不改记录、不写成功审计”。若产品要求待核实容器仍可主动删除，需要单独决策。
    """
    _root, machine, container = create_container_graph()
    node_comms._handle_container_vanish(container.name, machine.id, source="snapshot_missing")
    sent = mock_node_send(NODE_REMOVE_SUCCESS)

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.remove_container(container.id)

    assert excinfo.value.reason == "container_status_unknown"
    assert sent == []
    row = _row(db_session, container.id)
    assert row.is_valid is True
    assert row.status_source == "snapshot_missing"
    logs = _delete_logs(db_session, container.id)
    assert logs
    assert all(log.success is False for log in logs)
    assert logs[-1].error_reason == "container_status_unknown"


def test_cleanup_chain_still_deletes_unmarked_record(app, db_session, mock_node_send):
    _root, _machine, container = create_container_graph()
    mock_node_send(NODE_REMOVE_SUCCESS)

    assert container_tasks.remove_container(container.id) is True

    row = _row(db_session, container.id)
    assert row.is_valid is False
    assert row.deleted_trigger == "cleanup"
    assert len(_delete_logs(db_session, container.id)) == 1


@pytest.mark.parametrize(
    "node_status,expected",
    [
        ("online", ContainerStatus.ONLINE),
        ("offline", ContainerStatus.OFFLINE),
        ("paused", ContainerStatus.PAUSED),
        ("failed", ContainerStatus.FAILED),
    ],
)
def test_positive_status_clears_absence_marker(
    app, db_session, node_status, expected,
):
    _root, machine, container = create_container_graph()
    node_comms._handle_container_vanish(container.name, machine.id, source="snapshot_missing")

    node_comms.apply_container_status_snapshot(
        {container.name: {"status": node_status}}, machine.id,
    )

    row = _row(db_session, container.id)
    assert row.id == container.id
    assert row.container_status == expected
    assert row.status_unknown_since is None
    assert row.status_source is None


@pytest.mark.parametrize(
    "node_status,expected_status",
    [
        ("unknown", ContainerStatus.ONLINE),
        ("pausing", ContainerStatus.ONLINE),
        ("unpausing", ContainerStatus.ONLINE),
        ("building", ContainerStatus.BUILDING),
        ("creating", ContainerStatus.CREATING),
        ("starting", ContainerStatus.STARTING),
        ("restarting", ContainerStatus.RESTARTING),
        ("stopping", ContainerStatus.STOPPING),
    ],
)
def test_unknown_or_transition_status_keeps_absence_marker(
    app, db_session, node_status, expected_status,
):
    _root, machine, container = create_container_graph()
    node_comms._handle_container_vanish(container.name, machine.id, source="snapshot_missing")

    node_comms.apply_container_status_snapshot(
        {container.name: {"status": node_status, "status_source": "cold_start_verify"}},
        machine.id,
    )

    row = _row(db_session, container.id)
    assert row.container_status == expected_status
    assert row.status_unknown_since is not None
    assert row.status_source is not None


def test_positive_status_on_other_machine_does_not_clear_marker(app, db_session):
    machine_a = create_machine(machine_name="clear-a")
    machine_b = create_machine(machine_name="clear-b")
    ca = create_container(machine=machine_a, name="same_name")
    cb = create_container(machine=machine_b, name="same_name")
    keep_b = create_container(machine=machine_b, name="keep_b")
    db_session.commit()
    node_comms._handle_container_vanish(ca.name, machine_a.id, source="snapshot_missing")

    node_comms.apply_container_status_snapshot(
        {cb.name: {"status": "online"}, keep_b.name: {"status": "online"}}, machine_b.id,
    )

    assert _row(db_session, ca.id).status_source == "snapshot_missing"
    assert _row(db_session, cb.id).status_source is None
    assert _row(db_session, ca.id).is_valid is True


def test_soft_deleted_same_name_is_not_resurrected_by_status_snapshot(app, db_session):
    _root, machine, container = create_container_graph()
    containers_repo.delete_container(container.id, deleted_trigger="api", session=db_session)
    db_session.commit()
    assert _row(db_session, container.id).is_valid is False

    result = node_comms.apply_container_status_snapshot(
        {container.name: {"status": "online"}}, machine.id,
    )

    db_session.expire_all()
    rows = db_session.scalars(select(Container).where(Container.name == container.name)).all()
    assert len(rows) == 1
    assert rows[0].id == container.id
    assert rows[0].is_valid is False
    assert rows[0].status_source is None
    assert result["updated"] == 0


def test_vanish_sources_are_distinguishable_and_throttled(app, db_session, caplog):
    _root, machine, container = create_container_graph()
    caplog.set_level(logging.WARNING, logger=vanish.__name__)

    node_comms._handle_container_vanish(container.name, machine.id, source="delete_frame")
    first = _row(db_session, container.id)
    first_since = first.status_unknown_since

    node_comms._handle_container_vanish(container.name, machine.id, source="snapshot_missing")
    second = _row(db_session, container.id)

    text = caplog.text
    assert "source=delete_frame" in text
    assert "source=snapshot_missing" in text
    assert f"machine_id={machine.id}" in text
    assert f"container_id={container.id}" in text
    assert "observed_at=" in text
    assert second.status_unknown_since == first_since
    assert second.status_source == "snapshot_missing"
    assert _delete_logs(db_session, container.id) == []

    caplog.clear()
    node_comms._handle_container_vanish(container.name, machine.id, source="snapshot_missing")
    assert "container vanish clue: source=snapshot_missing" not in caplog.text


def test_pending_state_is_visible_as_status_unknown(app, db_session):
    _root, _machine, container = create_container_graph()
    node_comms._handle_container_vanish(container.name, container.machine_id, source="snapshot_missing")

    detail = container_tasks.get_container_detail_information(container.id)

    assert detail["effective_status"] == "status_unknown"
    assert detail["is_long_term"] is False
