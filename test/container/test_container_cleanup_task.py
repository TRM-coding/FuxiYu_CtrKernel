import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from ...constant import MachineStatus
from ...extensions import session_scope
from ...models.container_ssh_login import ContainerSSHLogin
from ...models.containers import Container
from ...models.operation_log import OperationLog
from ...repositories import long_term_container_repo
from ...schedulers import container_cleanup_task
from ..factories import create_container_graph


def _ssh_record(db_session, machine_id, container_id, last_ssh_login_time):
    record = ContainerSSHLogin(
        machine_id=machine_id,
        container_id=container_id,
        last_ssh_login_time=last_ssh_login_time,
    )
    db_session.add(record)
    db_session.commit()
    return record


def test_cleanup_expired_containers_skips_long_term(app, db_session, monkeypatch):
    _root, machine, container = create_container_graph()
    _ssh_record(db_session, machine.id, container.id, (datetime.utcnow() - timedelta(days=8)).isoformat())
    long_term_container_repo.add(container.id, session=db_session)
    db_session.commit()
    removed = []
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container", lambda container_id: removed.append(container_id) or True)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert removed == []


def test_cleanup_expired_containers_sends_reminder_for_countdown(app, db_session, monkeypatch):
    _root, machine, container = create_container_graph()
    _ssh_record(db_session, machine.id, container.id, (datetime.utcnow() - timedelta(days=6, hours=13)).isoformat())
    reminded = []
    monkeypatch.setattr(container_cleanup_task, "_send_cleanup_reminders_if_needed", lambda cid, info: reminded.append((cid, info["cleanup_status"])))
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container", lambda container_id: True)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert reminded == [(container.id, "countdown")]


def test_cleanup_expired_containers_removes_due_container_after_snapshot(app, db_session, monkeypatch):
    _root, machine, container = create_container_graph()
    _ssh_record(db_session, machine.id, container.id, (datetime.utcnow() - timedelta(days=8)).isoformat())
    snapshots = []
    removed = []
    monkeypatch.setattr(container_cleanup_task.container_tasks, "build_container_restore_snapshot", lambda cid, cleanup_context=None: snapshots.append(cid) or {"container_id": cid})
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container", lambda container_id: removed.append(container_id) or True)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert snapshots == [container.id]
    assert removed == [container.id]


def test_cleanup_expired_containers_skips_soft_deleted_ssh_records(app, db_session, monkeypatch):
    _root, machine, container = create_container_graph()
    _ssh_record(db_session, machine.id, container.id, (datetime.utcnow() - timedelta(days=8)).isoformat())
    with session_scope() as session:
        from ...repositories import containers_repo

        containers_repo.delete_container(container.id, session=session)
    removed = []
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container", lambda container_id: removed.append(container_id) or True)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert removed == []


def test_cleanup_expired_containers_continues_after_remove_failure(app, db_session, monkeypatch):
    _root1, machine1, first = create_container_graph()
    _root2, machine2, second = create_container_graph()
    old = (datetime.utcnow() - timedelta(days=8)).isoformat()
    _ssh_record(db_session, machine1.id, first.id, old)
    _ssh_record(db_session, machine2.id, second.id, old)
    removed = []

    def _remove(container_id):
        removed.append(container_id)
        if container_id == first.id:
            raise RuntimeError("remove failed")
        return True

    monkeypatch.setattr(container_cleanup_task.container_tasks, "build_container_restore_snapshot", lambda cid, cleanup_context=None: {"container_id": cid})
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container", _remove)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert removed == [first.id, second.id]


# ---------------------------------------------------------------------------
# 管辖范畴门禁：范畴外静默跳过（不动作、不留审计、不留常规日志）
# ---------------------------------------------------------------------------

def _expired_ssh_record(db_session, machine_id, container_id, days=8):
    return _ssh_record(db_session, machine_id, container_id,
                       (datetime.utcnow() - timedelta(days=days)).isoformat())


def _cleanup_log_records(caplog):
    return [r for r in caplog.records if "container-cleanup" in r.getMessage()]


def test_out_of_scope_skips_remove_container(app, db_session, monkeypatch):
    """范畴外：不调用动作层 remove_container。"""
    _root, machine, container = create_container_graph()
    machine.machine_status = MachineStatus.OFFLINE
    db_session.commit()
    _expired_ssh_record(db_session, machine.id, container.id)
    removed = []
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container",
                        lambda container_id: removed.append(container_id) or True)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert removed == []


def test_out_of_scope_produces_no_records_across_rounds(app, db_session, caplog):
    """范畴外连续多轮：op-log 与常规日志均零增长（走真实 remove_container 失败路径）。

    修复前模型：动作层抛错、_audit_removal 在 raise 前落库 → 每轮一条 delete_container 失败记录。
    """
    _root, machine, container = create_container_graph()
    machine.machine_status = MachineStatus.OFFLINE
    db_session.commit()
    _expired_ssh_record(db_session, machine.id, container.id)

    with caplog.at_level(logging.DEBUG):
        for _ in range(3):
            container_cleanup_task.cleanup_expired_containers_once(7)

    assert db_session.scalars(select(OperationLog)).all() == []
    assert _cleanup_log_records(caplog) == []
    db_session.expire_all()
    assert db_session.get(Container, container.id).is_valid is True


def test_in_scope_failure_is_still_audited(app, db_session, monkeypatch):
    """范畴内动作失败照常留痕（回归保护）：门禁不吞掉真实失败。"""
    _root, machine, container = create_container_graph()
    _expired_ssh_record(db_session, machine.id, container.id)

    def _reject(container_):
        raise RuntimeError("node refused removal")

    monkeypatch.setattr(container_cleanup_task.container_tasks, "_request_node_removal", _reject)

    container_cleanup_task.cleanup_expired_containers_once(7)

    logs = db_session.scalars(select(OperationLog)).all()
    assert len(logs) == 1
    assert logs[0].success is False
    assert "node refused removal" in (logs[0].error_reason or "")


def test_same_round_mixes_in_and_out_of_scope(app, db_session, monkeypatch):
    """同轮内按机器区分：范畴内照常清理、范畴外被跳过，互不牵连。"""
    _root_off, machine_off, container_off = create_container_graph()
    _root_on, machine_on, container_on = create_container_graph()
    machine_off.machine_status = MachineStatus.OFFLINE
    db_session.commit()
    _expired_ssh_record(db_session, machine_off.id, container_off.id)
    _expired_ssh_record(db_session, machine_on.id, container_on.id)
    removed = []
    monkeypatch.setattr(container_cleanup_task.container_tasks, "build_container_restore_snapshot",
                        lambda cid, cleanup_context=None: {"container_id": cid})
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container",
                        lambda container_id: removed.append(container_id) or True)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert removed == [container_on.id]


def test_maintenance_machine_is_out_of_scope(app, db_session, monkeypatch):
    """维护中（状态仍 ONLINE）：容器清理同样不动作。"""
    _root, machine, container = create_container_graph()
    machine.is_maintenance = True
    db_session.commit()
    _expired_ssh_record(db_session, machine.id, container.id)
    removed = []
    monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container",
                        lambda container_id: removed.append(container_id) or True)

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert removed == []

