"""Mount cleanup async result-log contracts."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import select

from ...models.operation_log import OperationLog
from ...repositories import (
    container_mount_cleanup_repo,
    deleted_container_restore_snapshot_repo,
)
from ...services import container_tasks
from ...services.container_module import mount_cleanup_tasks, node_comms
from ..factories import create_machine


pytestmark = pytest.mark.usefixtures("ensure_auth_users")


@pytest.fixture(autouse=True)
def _clean_registry():
    mount_cleanup_tasks.reset_registry()
    yield
    mount_cleanup_tasks.reset_registry()


def _prepare(db_session):
    machine = create_machine()
    cleanup = container_mount_cleanup_repo.insert(
        container_id=999,
        container_name="log_c",
        machine_id=machine.id,
        mount_path="/home/u/containers/log_c",
        session=db_session,
    )
    deleted = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": 999,
            "container_name": "log_c",
            "machine_id": machine.id,
            "bind_mount_path": "/home/u/containers/log_c",
        },
        session=db_session,
        mount_cleanup_id=cleanup.id,
        mount_cleaned=False,
    )
    cleanup.deleted_id = deleted.id
    db_session.commit()
    return cleanup


def test_accepted_writes_no_result_log_until_success(db_session, monkeypatch):
    cleanup = _prepare(db_session)
    entered = threading.Event()
    release = threading.Event()

    def _send(url, payload, timeout=5.0, **kwargs):
        if url.endswith("/start_clean_mount"):
            entered.set()
            release.wait(2.0)
            return {"success": 1, "task_id": "task-log"}
        if url.endswith("/get_clean_mount_status"):
            return {
                "success": 1,
                "task_id": "task-log",
                "state": "succeeded",
                "error_reason": None,
            }
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert entered.wait(2.0)
    assert db_session.scalars(select(OperationLog)).all() == []

    release.set()
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "succeeded"
    logs = db_session.scalars(select(OperationLog)).all()
    assert len(logs) == 1
    log = logs[0]
    assert log.success is True
    assert log.operation == "delete_container"
    assert log.target_type == "container_mount_cleanup"
    assert log.detail["trigger"] == "auto_mount_cleanup"
    assert log.detail["task_id"] == "task-log"
    assert log.detail["escalation"] is False


def test_unknown_writes_failure_log_with_stable_reason(db_session, monkeypatch):
    cleanup = _prepare(db_session)

    def _send(url, payload, timeout=5.0, **kwargs):
        if url.endswith("/start_clean_mount"):
            return {"success": 1, "task_id": "task-log-unknown"}
        if url.endswith("/get_clean_mount_status"):
            return {"error": "timeout"}
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mount_cleanup_tasks, "STATUS_RETRY_INTERVAL_SECONDS", 0)
    container_tasks.submit_mount_cleanup(cleanup.id, trigger="disk_escalation", escalation=True)
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "unknown"

    logs = db_session.scalars(select(OperationLog)).all()
    assert len(logs) == 1
    assert logs[0].success is False
    assert logs[0].error_reason == "node_timeout"
    assert logs[0].detail["trigger"] == "disk_escalation"
