"""In-process cleanup key / restore reservation tests."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import select

from ...extensions import session_scope
from ...models.container_mount_cleanup import ContainerMountCleanup
from ...models.containers import Container
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...models.operation_log import OperationLog
from ...repositories import (
    container_mount_cleanup_repo,
    deleted_container_restore_snapshot_repo,
    image_repo,
)
from ...services import container_tasks
from ...services.container_module import mount_cleanup_tasks, node_comms
from ..factories import create_container_graph, create_machine


pytestmark = pytest.mark.usefixtures("ensure_auth_users")


@pytest.fixture(autouse=True)
def _clean_registry():
    mount_cleanup_tasks.reset_registry()
    yield
    mount_cleanup_tasks.reset_registry()


def _prepare_cleanup(db_session, *, path="/home/u/containers/registry_c"):
    machine = create_machine()
    cleanup = container_mount_cleanup_repo.insert(
        container_id=999,
        container_name="registry_c",
        machine_id=machine.id,
        mount_path=path,
        session=db_session,
    )
    deleted = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": 999,
            "container_name": "registry_c",
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


def _install_blocked_start(monkeypatch, *, entered, release):
    def _send(url, payload, timeout=5.0, **kwargs):
        if url.endswith("/start_clean_mount"):
            entered.set()
            release.wait(2.0)
            return {"success": 1, "task_id": "task-registry"}
        if url.endswith("/get_clean_mount_status"):
            return {
                "success": 1,
                "task_id": "task-registry",
                "state": "succeeded",
                "error_reason": None,
            }
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)


def test_same_key_concurrent_cleanup_only_one_start(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)
    entered = threading.Event()
    release = threading.Event()
    _install_blocked_start(monkeypatch, entered=entered, release=release)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    first = container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert first["accepted"] is True
    assert entered.wait(2.0)

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert excinfo.value.reason == "cleanup_in_progress"

    release.set()
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "succeeded"


def test_restore_reservation_blocks_cleanup_and_cleanup_blocks_restore(db_session, monkeypatch):
    machine, cleanup, _deleted = _prepare_cleanup(db_session)
    with mount_cleanup_tasks.reserve_restore(machine.id, cleanup.mount_path):
        with pytest.raises(container_tasks.NodeServiceError) as excinfo:
            container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
        assert excinfo.value.reason == "restore_in_progress"

    entered = threading.Event()
    release = threading.Event()
    _install_blocked_start(monkeypatch, entered=entered, release=release)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert entered.wait(2.0)
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        with mount_cleanup_tasks.reserve_restore(machine.id, cleanup.mount_path):
            pass
    assert excinfo.value.reason == "cleanup_in_progress"
    release.set()
    mount_cleanup_tasks.wait_for_cleanup(cleanup.id)


def test_different_machine_or_real_path_keys_are_independent(db_session, monkeypatch):
    first_machine, first, _ = _prepare_cleanup(db_session, path="/home/u/containers/a")
    second_machine, second, _ = _prepare_cleanup(db_session, path="/home/u/containers/b")

    def _send(url, payload, timeout=5.0, **kwargs):
        if url.endswith("/start_clean_mount"):
            return {"success": 1, "task_id": f"task-{id(payload)}"}
        if url.endswith("/get_clean_mount_status"):
            return {
                "success": 1,
                "task_id": payload["config"]["task_id"],
                "state": "succeeded",
                "error_reason": None,
            }
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    assert container_tasks.submit_mount_cleanup(first.id, trigger="auto_mount_cleanup")["accepted"]
    assert container_tasks.submit_mount_cleanup(second.id, trigger="auto_mount_cleanup")["accepted"]
    assert mount_cleanup_tasks.wait_for_cleanup(first.id) == "succeeded"
    assert mount_cleanup_tasks.wait_for_cleanup(second.id) == "succeeded"


def test_active_capacity_rejects_new_cleanup(db_session, monkeypatch):
    _machine, first, _ = _prepare_cleanup(db_session, path="/home/u/containers/capacity-a")
    _machine2, second, _ = _prepare_cleanup(db_session, path="/home/u/containers/capacity-b")
    entered = threading.Event()
    release = threading.Event()
    _install_blocked_start(monkeypatch, entered=entered, release=release)
    monkeypatch.setattr(mount_cleanup_tasks, "MAX_ACTIVE_TASKS", 1)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    container_tasks.submit_mount_cleanup(first.id, trigger="auto_mount_cleanup")
    assert entered.wait(2.0)
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.submit_mount_cleanup(second.id, trigger="auto_mount_cleanup")
    assert excinfo.value.reason == "cleanup_capacity_exhausted"
    release.set()
    mount_cleanup_tasks.wait_for_cleanup(first.id)


def test_terminal_summary_expiry_and_restart_clear(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)

    def _send(url, payload, timeout=5.0, **kwargs):
        if url.endswith("/start_clean_mount"):
            return {"success": 1, "task_id": "task-expire"}
        if url.endswith("/get_clean_mount_status"):
            return {
                "success": 1,
                "task_id": "task-expire",
                "state": "failed",
                "error_reason": "cleanup_failed",
            }
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "failed"
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["state"] == "failed"

    monkeypatch.setattr(mount_cleanup_tasks, "TERMINAL_TTL_SECONDS", 0)
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["state"] is None

    mount_cleanup_tasks.reset_registry()
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["state"] is None


def test_restore_is_rejected_while_same_lexical_cleanup_is_active(db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    container.bind_mount_path = f"/home/{root.username}/containers/restore_guard_data"
    db_session.commit()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def _send(url, payload, timeout=5.0, **kwargs):
        calls.append(url)
        if url.endswith("/remove_container"):
            return {"success": 1}
        if url.endswith("/start_clean_mount"):
            entered.set()
            release.wait(2.0)
            return {"success": 1, "task_id": "task-restore-guard"}
        if url.endswith("/get_clean_mount_status"):
            return {
                "success": 1,
                "task_id": "task-restore-guard",
                "state": "succeeded",
                "error_reason": None,
            }
        if url.endswith("/create_container"):
            raise AssertionError("restore must not reach create while cleanup is active")
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    container_tasks.remove_container(container.id, operator_user_id=root.id)
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()

    container_tasks.submit_mount_cleanup(
        snapshot.mount_cleanup_id,
        trigger="auto_mount_cleanup",
    )
    assert entered.wait(2.0)
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)
    assert excinfo.value.reason == "cleanup_in_progress"
    assert not any(url.endswith("/create_container") for url in calls)
    release.set()
    mount_cleanup_tasks.wait_for_cleanup(snapshot.mount_cleanup_id)


def _prepare_container_cleanup(db_session, *, cleanup_path="stale", stale_machine=True):
    root, machine, container = create_container_graph()
    current_path = f"/home/{root.username}/containers/current_target"
    container.bind_mount_path = current_path
    container.is_valid = False
    db_session.commit()
    target_machine = create_machine() if stale_machine else machine
    cleanup = container_mount_cleanup_repo.insert(
        container_id=container.id,
        container_name=container.name,
        machine_id=target_machine.id,
        mount_path=(
            "/home/u/containers/stale_target"
            if cleanup_path == "stale"
            else current_path
        ),
        escalation=False,
        session=db_session,
    )
    deleted = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": container.id,
            "container_name": container.name,
            "machine_id": machine.id,
            "bind_mount_path": current_path,
        },
        session=db_session,
        mount_cleanup_id=cleanup.id,
        mount_cleaned=False,
    )
    cleanup.deleted_id = deleted.id
    db_session.commit()
    return root, machine, target_machine, container, cleanup, deleted, current_path


def _install_success(monkeypatch, calls, *, task_id="task-target", path=None):
    def _send(url, payload, timeout=5.0, **kwargs):
        calls.append((url, payload))
        if url.endswith("/check_mount_usage"):
            return {
                "success": 1,
                "mounts": [{
                    "path": payload["config"]["mount_paths"][0],
                    "bytes": 1,
                    "measured_at": "2026-11-11T00:00:00Z",
                    "pending": False,
                    "error": None,
                }],
            }
        if url.endswith("/start_clean_mount"):
            return {"success": 1, "task_id": task_id}
        if url.endswith("/get_clean_mount_status"):
            return {
                "success": 1,
                "task_id": task_id,
                "state": "succeeded",
                "error_reason": None,
            }
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mount_cleanup_tasks, "STATUS_RETRY_INTERVAL_SECONDS", 0)


def test_manual_target_prefers_container_machine_before_registration(db_session, monkeypatch):
    root, machine, _stale_machine, _container, cleanup, _deleted, path = _prepare_container_cleanup(
        db_session,
        cleanup_path="current",
    )
    calls = []
    _install_success(monkeypatch, calls, task_id="task-manual-target")

    result = container_tasks.clean_deleted_container_mount(
        mount_cleanup_id=cleanup.id,
        operator_user_id=root.id,
    )
    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "succeeded"
    start_calls = [item for item in calls if item[0].endswith("/start_clean_mount")]
    assert start_calls and start_calls[0][1]["config"]["mount_path"] == path
    assert machine.machine_ip in start_calls[0][0]
    log = db_session.scalars(select(OperationLog)).one()
    assert log.success is True
    assert log.detail["machine_id"] == machine.id


def test_escalation_target_prefers_container_machine_before_registration(db_session, monkeypatch):
    root, machine, _stale_machine, container, cleanup, _deleted, path = _prepare_container_cleanup(
        db_session,
        cleanup_path="current",
    )
    calls = []
    _install_success(monkeypatch, calls, task_id="task-escalation-target")

    from ...schedulers import container_disk_check_task

    container_disk_check_task._clean_mount_immediately(container)
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "succeeded"
    start_calls = [item for item in calls if item[0].endswith("/start_clean_mount")]
    assert start_calls and start_calls[0][1]["config"]["mount_path"] == path
    assert machine.machine_ip in start_calls[0][0]
    log = db_session.scalars(select(OperationLog)).one()
    assert log.success is True
    assert log.detail["machine_id"] == machine.id
    assert log.detail["trigger"] == "disk_escalation"


def test_start_cleanup_target_prefers_container_path_over_stale_cleanup(db_session, monkeypatch):
    _root, machine, _stale_machine, _container, cleanup, _deleted, path = _prepare_container_cleanup(
        db_session,
        cleanup_path="stale",
        stale_machine=False,
    )
    calls = []
    _install_success(monkeypatch, calls, task_id="task-path-target")

    result = container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "succeeded"
    start_calls = [item for item in calls if item[0].endswith("/start_clean_mount")]
    assert start_calls and start_calls[0][1]["config"]["mount_path"] == path
    log = db_session.scalars(select(OperationLog)).one()
    assert log.detail["machine_id"] == machine.id


def test_manual_cleanup_rechecks_live_container_after_reservation(db_session, monkeypatch):
    root, machine, container = create_container_graph()
    path = f"/home/{root.username}/containers/live_after_reservation"
    container.bind_mount_path = path
    container.is_valid = False
    db_session.commit()
    cleanup = container_mount_cleanup_repo.insert(
        container_id=container.id,
        container_name=container.name,
        machine_id=machine.id,
        mount_path=path,
        session=db_session,
    )
    deleted = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": container.id,
            "container_name": container.name,
            "machine_id": machine.id,
            "bind_mount_path": path,
        },
        session=db_session,
        mount_cleanup_id=cleanup.id,
        mount_cleaned=False,
    )
    cleanup.deleted_id = deleted.id
    db_session.commit()

    original_load = mount_cleanup_tasks._load_task_record
    calls = []

    def _load_then_restore(task):
        with session_scope() as session:
            session.get(Container, container.id).is_valid = True
        return original_load(task)

    def _send(url, payload, timeout=5.0, **kwargs):
        calls.append(url)
        if url.endswith("/check_mount_usage"):
            return {
                "success": 1,
                "mounts": [{
                    "path": path,
                    "bytes": 1,
                    "measured_at": "2026-11-11T00:00:00Z",
                    "pending": False,
                    "error": None,
                }],
            }
        pytest.fail("manual cleanup must not start Node after restore becomes valid")

    monkeypatch.setattr(mount_cleanup_tasks, "_load_task_record", _load_then_restore)
    monkeypatch.setattr(node_comms, "send", _send)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    result = container_tasks.clean_deleted_container_mount(
        mount_cleanup_id=cleanup.id,
        operator_user_id=root.id,
    )
    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "failed"
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["error_reason"] == "container_exists"
    assert not any(url.endswith("/start_clean_mount") for url in calls)
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None


@pytest.mark.parametrize("changed_field", ["mount_path", "machine_id"])
def test_worker_rejects_target_changed_after_registration(db_session, monkeypatch, changed_field):
    machine, cleanup, _deleted = _prepare_cleanup(db_session)
    original_path = cleanup.mount_path
    other_machine = create_machine()
    original_load = mount_cleanup_tasks._load_task_record
    calls = []

    def _load_changed(task):
        row = db_session.get(ContainerMountCleanup, task.cleanup_id)
        if changed_field == "mount_path":
            row.mount_path = "/home/u/containers/other_target"
        else:
            row.machine_id = other_machine.id
        db_session.commit()
        return original_load(task)

    def _send(url, payload, timeout=5.0, **kwargs):
        calls.append(url)
        pytest.fail("changed target must not reach Node")

    monkeypatch.setattr(mount_cleanup_tasks, "_load_task_record", _load_changed)
    monkeypatch.setattr(node_comms, "send", _send)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    result = container_tasks.submit_mount_cleanup(cleanup.id, trigger="auto_mount_cleanup")
    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "failed"
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["error_reason"] == "cleanup_target_changed"
    assert calls == []
    # The original reservation key must be released, not a key for the changed target.
    with mount_cleanup_tasks.reserve_restore(machine.id, original_path):
        pass


def test_node_create_conflict_keeps_snapshot_and_does_not_write_success(db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    container.bind_mount_path = f"/home/{root.username}/containers/node_conflict_data"
    container.image_id = 1
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    db_session.commit()

    def _send(url, payload, timeout=5.0, **kwargs):
        if url.endswith("/remove_container"):
            return {"success": 1}
        if url.endswith("/check_mount_usage"):
            path = payload["config"]["mount_paths"][0]
            return {
                "success": 1,
                "mounts": [{
                    "path": path,
                    "bytes": 1,
                    "measured_at": "2026-11-11T00:00:00Z",
                    "pending": False,
                    "error": None,
                }],
            }
        if url.endswith("/create_container"):
            return {"success": 0, "error_reason": "cleanup_in_progress"}
        raise AssertionError(f"unexpected node url: {url}")

    monkeypatch.setattr(node_comms, "send", _send)
    container_tasks.remove_container(container.id, operator_user_id=root.id)
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)
    assert excinfo.value.reason == "cleanup_in_progress"
    db_session.expire_all()
    assert db_session.get(DeletedContainerRestoreSnapshot, snapshot.id) is not None
    assert db_session.get(ContainerMountCleanup, snapshot.mount_cleanup_id).cleaned_at is None
    assert not any(
        log.success
        for log in db_session.scalars(select(OperationLog)).all()
        if log.operation == "create_container"
    )
