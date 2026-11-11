"""Deleted-list cleanup state projection tests."""

from __future__ import annotations

import threading

import pytest

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


def _prepare_deleted(db_session, *, path="/home/u/containers/list_c"):
    machine = create_machine()
    cleanup = container_mount_cleanup_repo.insert(
        container_id=999,
        container_name="list_c",
        machine_id=machine.id,
        mount_path=path,
        session=db_session,
    )
    deleted = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": 999,
            "container_name": "list_c",
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


def _record(db_session):
    result = container_tasks.list_deleted_containers(page_number=1, page_size=20)
    assert result["total_number"] == 1
    return result["records"][0]


def test_list_shows_cleaning_then_success(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_deleted(db_session)
    entered = threading.Event()
    release = threading.Event()

    def _send(url, payload, timeout=5.0, **kwargs):
        if url.endswith("/start_clean_mount"):
            entered.set()
            release.wait(2.0)
            return {"success": 1, "task_id": "task-list"}
        if url.endswith("/get_clean_mount_status"):
            return {
                "success": 1,
                "task_id": "task-list",
                "state": "succeeded",
                "error_reason": None,
            }
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert entered.wait(2.0)

    record = _record(db_session)
    assert record["mount_cleanup_state"] == "cleaning"
    assert record["mount_cleanup_error_reason"] is None
    assert record["data_recoverable"] is False
    assert record["cleaned_at"] is None
    assert record["mount_cleaned"] is False

    release.set()
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "succeeded"
    record = _record(db_session)
    assert record["mount_cleanup_state"] is None
    assert record["mount_cleaned"] is True
    assert record["cleaned_at"] is not None
    assert record["data_recoverable"] is False


def test_list_shows_failed_and_unknown(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_deleted(db_session)
    states = iter(["failed", "unknown"])

    def _send(url, payload, timeout=5.0, **kwargs):
        if url.endswith("/start_clean_mount"):
            return {"success": 1, "task_id": "task-state"}
        if url.endswith("/get_clean_mount_status"):
            try:
                state = next(states)
            except StopIteration:
                return {"error": "timeout"}
            if state == "unknown":
                return {"error": "timeout"}
            return {
                "success": 1,
                "task_id": "task-state",
                "state": "failed",
                "error_reason": "cleanup_failed",
            }
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mount_cleanup_tasks, "STATUS_RETRY_INTERVAL_SECONDS", 0)

    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "failed"
    record = _record(db_session)
    assert record["mount_cleanup_state"] == "failed"
    assert record["mount_cleanup_error_reason"] == "cleanup_failed"
    assert record["data_recoverable"] is True

    mount_cleanup_tasks.reset_registry()
    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "unknown"
    record = _record(db_session)
    assert record["mount_cleanup_state"] == "unknown"
    assert record["mount_cleanup_error_reason"] == "node_timeout"


def test_list_without_registry_is_read_only_and_node_free(db_session, monkeypatch):
    _machine, _cleanup, _deleted = _prepare_deleted(db_session)
    calls = []
    monkeypatch.setattr(node_comms, "send", lambda *args, **kwargs: calls.append(args) or {})

    record = _record(db_session)
    assert record["mount_cleanup_state"] is None
    assert record["mount_cleanup_error_reason"] is None
    assert record["data_recoverable"] is True
    assert calls == []


def test_list_after_registry_reset_uses_database(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_deleted(db_session)
    entered = threading.Event()
    release = threading.Event()

    def _send(url, payload, timeout=5.0, **kwargs):
        if url.endswith("/start_clean_mount"):
            entered.set()
            release.wait(2.0)
            return {"success": 1, "task_id": "task-reset-list"}
        if url.endswith("/get_clean_mount_status"):
            return {
                "success": 1,
                "task_id": "task-reset-list",
                "state": "succeeded",
                "error_reason": None,
            }
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert entered.wait(2.0)
    assert _record(db_session)["mount_cleanup_state"] == "cleaning"

    mount_cleanup_tasks.reset_registry()
    record = _record(db_session)
    assert record["mount_cleanup_state"] is None
    assert record["mount_cleaned"] is False
    assert record["data_recoverable"] is True
    release.set()
    mount_cleanup_tasks.wait_for_cleanup(cleanup.id)
