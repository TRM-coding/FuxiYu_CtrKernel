"""Ctrl async mount cleanup worker tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from ...models.container_mount_cleanup import ContainerMountCleanup
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
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


def _prepare_cleanup(db_session, *, path="/home/u/containers/async_c"):
    machine = create_machine(machine_ip="127.0.0.60")
    cleanup = container_mount_cleanup_repo.insert(
        container_id=999,
        container_name="async_c",
        machine_id=machine.id,
        mount_path=path,
        session=db_session,
    )
    deleted = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": 999,
            "container_name": "async_c",
            "machine_id": machine.id,
            "bind_mount_path": path,
        },
        session=db_session,
        mount_cleanup_id=cleanup.id,
        mount_cleaned=False,
    )
    cleanup.deleted_id = deleted.id
    db_session.commit()
    return machine, cleanup, deleted


def _mount_response(path, *, present=True):
    if not present:
        return {
            "path": path,
            "bytes": None,
            "measured_at": None,
            "pending": False,
            "error": "not_found",
        }
    return {
        "path": path,
        "bytes": 123,
        "measured_at": "2026-11-11T00:00:00Z",
        "pending": False,
        "error": None,
    }


def _install_node(
    monkeypatch,
    *,
    path,
    start=None,
    status=None,
    present=True,
    status_calls=None,
):
    calls = []

    def _send(url, payload, timeout=5.0, **kwargs):
        calls.append((url, payload, timeout))
        if url.endswith("/check_mount_usage"):
            return {"success": 1, "mounts": [_mount_response(path, present=present)]}
        if url.endswith("/start_clean_mount"):
            return start if start is not None else {"success": 1, "task_id": "task-1"}
        if url.endswith("/get_clean_mount_status"):
            if status_calls is not None:
                status_calls.append(payload)
            if callable(status):
                return status(payload)
            return status if status is not None else {
                "success": 1,
                "task_id": "task-1",
                "state": "succeeded",
                "error_reason": None,
            }
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)
    return calls


def test_manual_cleanup_accepted_then_succeeds(db_session, monkeypatch):
    machine, cleanup, deleted = _prepare_cleanup(db_session)
    calls = _install_node(monkeypatch, path=cleanup.mount_path)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    result = container_tasks.clean_deleted_container_mount(
        mount_cleanup_id=cleanup.id,
        operator_user_id=7,
    )

    assert result["accepted"] is True
    assert result["mount_cleanup_state"] == "cleaning"
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "succeeded"
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is not None
    assert db_session.get(DeletedContainerRestoreSnapshot, deleted.id).mount_cleaned is True
    logs = db_session.scalars(select(OperationLog)).all()
    assert len(logs) == 1
    assert logs[0].success is True
    assert logs[0].operation == "delete_container"
    assert logs[0].detail["trigger"] == "manual_clean_mount"
    assert logs[0].detail["task_id"] == "task-1"
    assert any(url.endswith("/start_clean_mount") for url, _payload, _timeout in calls)
    assert not any(url.endswith("/clean_mount") for url, _payload, _timeout in calls)


def test_running_keeps_polling_without_total_deadline(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)
    status_calls = []
    running = {"success": 1, "task_id": "task-1", "state": "running", "error_reason": None}
    succeeded = {"success": 1, "task_id": "task-1", "state": "succeeded", "error_reason": None}

    def _status(_payload):
        if len(status_calls) < 6:
            return running
        return succeeded

    _install_node(
        monkeypatch,
        path=cleanup.mount_path,
        status=_status,
        status_calls=status_calls,
    )
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    result = container_tasks.submit_mount_cleanup(
        cleanup.id,
        trigger="auto_mount_cleanup",
    )
    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "succeeded"
    assert len(status_calls) == 6
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is not None


def test_consecutive_status_timeouts_reach_unknown(db_session, monkeypatch):
    _machine, cleanup, deleted = _prepare_cleanup(db_session)
    status_calls = []
    calls = _install_node(
        monkeypatch,
        path=cleanup.mount_path,
        status={"status_code": 504, "error": "timeout"},
        status_calls=status_calls,
    )
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mount_cleanup_tasks, "STATUS_RETRY_INTERVAL_SECONDS", 0)

    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "unknown"
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["state"] == "unknown"
    assert len(status_calls) == mount_cleanup_tasks.MAX_CONSECUTIVE_STATUS_FAILURES
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None
    assert db_session.get(DeletedContainerRestoreSnapshot, deleted.id).mount_cleaned is False
    logs = db_session.scalars(select(OperationLog)).all()
    assert len(logs) == 1 and logs[0].success is False
    assert not any(url.endswith("/clean_mount") for url, _payload, _timeout in calls)


def test_transient_failures_retry_and_running_resets_count(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)
    status_calls = []
    running = {"success": 1, "task_id": "task-1", "state": "running", "error_reason": None}
    succeeded = {"success": 1, "task_id": "task-1", "state": "succeeded", "error_reason": None}
    responses = iter([
        {"error": "timeout"},
        {"status_code": 503, "error": "unavailable"},
        running,
        {"error": "connection refused"},
        succeeded,
    ])

    _install_node(
        monkeypatch,
        path=cleanup.mount_path,
        status=lambda _payload: next(responses),
        status_calls=status_calls,
    )
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mount_cleanup_tasks, "STATUS_RETRY_INTERVAL_SECONDS", 0)

    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "succeeded"
    assert len(status_calls) == 5
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is not None


def test_node_task_not_found_is_unknown_not_success(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)
    _install_node(
        monkeypatch,
        path=cleanup.mount_path,
        status={"success": 0, "error_reason": "task_not_found"},
    )
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mount_cleanup_tasks, "STATUS_RETRY_INTERVAL_SECONDS", 0)

    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "unknown"
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["error_reason"] == "node_task_lost"
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None
    logs = db_session.scalars(select(OperationLog)).all()
    assert len(logs) == 1 and logs[0].success is False
    assert logs[0].error_reason == "node_task_lost"


def test_node_status_404_not_found_is_node_task_lost(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)
    _install_node(
        monkeypatch,
        path=cleanup.mount_path,
        status={"status_code": 404, "error_reason": "not_found"},
    )
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mount_cleanup_tasks, "STATUS_RETRY_INTERVAL_SECONDS", 0)

    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "unknown"
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["error_reason"] == "node_task_lost"
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None
    logs = db_session.scalars(select(OperationLog)).all()
    assert len(logs) == 1 and logs[0].success is False
    assert logs[0].error_reason == "node_task_lost"


def test_old_status_endpoint_is_unknown_not_success(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)
    _install_node(
        monkeypatch,
        path=cleanup.mount_path,
        status={"status_code": 404, "error": "Not Found"},
    )
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mount_cleanup_tasks, "STATUS_RETRY_INTERVAL_SECONDS", 0)

    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "unknown"
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["error_reason"] == "node_unsupported"
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None


def test_node_failed_status_keeps_cleanup_unmarked(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)
    _install_node(
        monkeypatch,
        path=cleanup.mount_path,
        status={
            "success": 1,
            "task_id": "task-1",
            "state": "failed",
            "error_reason": "cleanup_failed",
        },
    )
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    container_tasks.submit_mount_cleanup(cleanup.id, trigger="disk_escalation", escalation=True)
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "failed"
    db_session.expire_all()
    row = db_session.get(ContainerMountCleanup, cleanup.id)
    assert row.cleaned_at is None
    logs = db_session.scalars(select(OperationLog)).all()
    assert len(logs) == 1 and logs[0].success is False
    assert logs[0].detail["trigger"] == "disk_escalation"


def test_old_node_start_is_failed_without_legacy_fallback(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)
    calls = _install_node(
        monkeypatch,
        path=cleanup.mount_path,
        start={"status_code": 404, "error": "Not Found"},
    )

    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "failed"
    assert not any(url.endswith("/clean_mount") for url, _payload, _timeout in calls)


def test_manual_not_found_fails_before_node_start(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)
    calls = _install_node(monkeypatch, path=cleanup.mount_path, present=False)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    result = container_tasks.clean_deleted_container_mount(
        mount_cleanup_id=cleanup.id,
        operator_user_id=7,
    )
    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "failed"
    assert not any(url.endswith("/start_clean_mount") for url, _payload, _timeout in calls)


def test_persist_failure_becomes_unknown(db_session, monkeypatch):
    _machine, cleanup, deleted = _prepare_cleanup(db_session)
    _install_node(monkeypatch, path=cleanup.mount_path)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    def _boom(*args, **kwargs):
        raise RuntimeError("snapshot mark failed")

    monkeypatch.setattr(deleted_container_restore_snapshot_repo, "mark_mount_cleaned", _boom)

    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "unknown"
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None
    assert db_session.get(DeletedContainerRestoreSnapshot, deleted.id).mount_cleaned is False
    logs = db_session.scalars(select(OperationLog)).all()
    assert len(logs) == 1 and logs[0].success is False
    assert logs[0].error_reason == "cleanup_persist_failed"
