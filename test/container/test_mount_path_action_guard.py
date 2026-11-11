"""恢复/手动清理动作前的服务端路径保护。

覆盖点：
- 只信目标 Node 对**这条路径**的同步 os.stat 结论；
- per-path ``not_found`` 才翻译成“不存在”，权限/非法路径各自保留原因；
- 旧 Node/离线/超时/坏响应没有结论：恢复以可重试原因阻断，绝不误称 not_found；
- 恢复在 Create_container 之前拒绝，手动清理在 /clean_mount 之前拒绝，且都不
  写 cleaned_at / mount_cleaned；
- pending 仍表示目录存在（Node 已过路径门禁）；
- 已恢复的有效容器仍有删除记录时，手动清理拒绝，绝不删活挂载目录；
- legacy cleanup-only 记录同样受保护。
"""

from datetime import datetime

import pytest
from sqlalchemy import select

from ...api import deps
from ...constant import MachineStatus
from ...models.container_mount_cleanup import ContainerMountCleanup
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...models.operation_log import OperationLog
from ...repositories import (
    container_mount_cleanup_repo,
    containers_repo,
    deleted_container_restore_snapshot_repo,
    image_repo,
)
from ...services import container_tasks
from ...services.container_module import mount_cleanup_tasks, mount_usage, node_comms
from ..factories import create_container_graph, create_machine

MEASURED_AT = "2026-11-01T00:00:00Z"


@pytest.fixture(autouse=True)
def _reset_cleanup_registry():
    mount_cleanup_tasks.reset_registry()
    yield
    mount_cleanup_tasks.reset_registry()


def _mount(path, *, pending=False, error=None):
    if pending:
        return {
            "path": path,
            "bytes": None,
            "measured_at": None,
            "pending": True,
            "error": None,
        }
    if error is not None:
        return {
            "path": path,
            "bytes": None,
            "measured_at": None,
            "pending": False,
            "error": error,
        }
    return {
        "path": path,
        "bytes": 123,
        "measured_at": MEASURED_AT,
        "pending": False,
        "error": None,
    }


def _check_response(path, *, pending=False, error=None):
    return {"success": 1, "mounts": [_mount(path, pending=pending, error=error)]}


def _install_send(monkeypatch, handler):
    calls = []

    def _send(url, payload, timeout=5.0, **kwargs):
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        return handler(url, payload)

    monkeypatch.setattr(node_comms, "send", _send)
    return calls


def _by_suffix(calls, suffix):
    return [call for call in calls if call["url"].endswith(suffix)]


def _prepare_restore(db_session, monkeypatch, *, path="/home/u/containers/restore_data"):
    root, machine, container = create_container_graph()
    container.name = "guard_restore_target"
    container.bind_mount_path = path
    container.image_id = 1
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    db_session.commit()
    # 造恢复快照/清理记录；这里只关心随后的动作前校验。
    monkeypatch.setattr(node_comms, "send", lambda *args, **kwargs: {"success": 1})
    container_tasks.remove_container(container.id, operator_user_id=root.id)
    db_session.expire_all()
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()
    cleanup = container_mount_cleanup_repo.get_by_id(
        snapshot.mount_cleanup_id,
        session=db_session,
    )
    assert cleanup is not None
    return root, machine, container, snapshot, cleanup


def _prepare_cleanup(
    db_session,
    *,
    path="/home/u/containers/manual_data",
    machine=None,
    link_deleted=True,
):
    machine = machine or create_machine(machine_ip="127.0.60.11")
    cleanup = container_mount_cleanup_repo.insert(
        container_id=999,
        container_name="guard_cleanup_target",
        machine_id=machine.id,
        mount_path=path,
        session=db_session,
    )
    deleted = None
    if link_deleted:
        deleted = deleted_container_restore_snapshot_repo.insert(
            {
                "container_id": 999,
                "container_name": "guard_cleanup_target",
                "machine_id": machine.id,
                "bind_mount_path": path,
            },
            session=db_session,
            mount_cleanup_id=cleanup.id,
            removed_at=datetime(2026, 10, 1, 0, 0, 0),
            mount_cleaned=False,
        )
        cleanup.deleted_id = deleted.id
    db_session.commit()
    return machine, cleanup, deleted


def _auth(monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: 1)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_entity",
        lambda uid, code: True,
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_resource",
        lambda *args, **kwargs: True,
    )


# ---------------------------------------------------------------------------
# 恢复
# ---------------------------------------------------------------------------

def test_restore_missing_path_rejected_before_any_create(db_session, monkeypatch):
    root, _machine, _container, snapshot, cleanup = _prepare_restore(db_session, monkeypatch)
    path = snapshot.snapshot["bind_mount_path"]
    calls = _install_send(
        monkeypatch,
        lambda url, payload: _check_response(path, error="not_found"),
    )

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    assert excinfo.value.reason == "data_not_recoverable"
    checks = _by_suffix(calls, "/check_mount_usage")
    assert len(checks) == 1
    assert checks[0]["payload"] == {"config": {"mount_paths": [path]}}
    assert checks[0]["timeout"] == mount_usage.NODE_QUERY_TIMEOUT_SECONDS
    assert _by_suffix(calls, "/create_container") == []
    db_session.expire_all()
    assert deleted_container_restore_snapshot_repo.get_by_id(snapshot.id, session=db_session) is not None
    assert container_mount_cleanup_repo.get_by_id(cleanup.id, session=db_session).cleaned_at is None


def test_restore_pending_still_means_present_and_restores(db_session, monkeypatch):
    root, _machine, _container, snapshot, _cleanup = _prepare_restore(
        db_session, monkeypatch, path="/home/u/containers/restore_pending",
    )
    path = snapshot.snapshot["bind_mount_path"]
    calls = _install_send(
        monkeypatch,
        lambda url, payload: (
            _check_response(path, pending=True)
            if url.endswith("/check_mount_usage")
            else {"success": 1}
        ),
    )

    result = container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    assert result["container_id"]
    assert len(_by_suffix(calls, "/check_mount_usage")) == 1
    assert len(_by_suffix(calls, "/create_container")) == 1


def test_restore_permission_denied_is_not_reported_as_missing(db_session, monkeypatch):
    root, _machine, _container, snapshot, _cleanup = _prepare_restore(db_session, monkeypatch)
    path = snapshot.snapshot["bind_mount_path"]
    calls = _install_send(
        monkeypatch,
        lambda url, payload: _check_response(path, error="permission_denied"),
    )

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    assert excinfo.value.reason == "permission_denied"
    assert excinfo.value.reason != "data_not_recoverable"
    assert _by_suffix(calls, "/create_container") == []


@pytest.mark.parametrize(
    "probe_response,reason",
    [
        ({"status_code": 404, "error": "Not Found"}, "node_unsupported"),
        ({"status_code": 405, "error": "Method Not Allowed"}, "node_unsupported"),
        ({"success": 1}, "node_bad_response"),
        ({"status_code": 500, "error": "boom"}, "node_unavailable"),
    ],
)
def test_restore_unknown_path_state_blocks_with_retryable_reason(
    db_session, monkeypatch, probe_response, reason,
):
    root, _machine, _container, snapshot, cleanup = _prepare_restore(db_session, monkeypatch)
    calls = _install_send(monkeypatch, lambda url, payload: probe_response)

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    assert excinfo.value.reason == reason
    assert excinfo.value.reason != "data_not_recoverable"
    assert _by_suffix(calls, "/create_container") == []
    db_session.expire_all()
    # 快照与清理记录未被消费，路径状态未知时恢复可重试。
    assert deleted_container_restore_snapshot_repo.get_by_id(snapshot.id, session=db_session) is not None
    assert container_mount_cleanup_repo.get_by_id(cleanup.id, session=db_session).cleaned_at is None


def test_restore_timeout_blocks_with_timeout_reason(db_session, monkeypatch):
    root, _machine, _container, snapshot, _cleanup = _prepare_restore(db_session, monkeypatch)

    def _timeout(url, payload, timeout=5.0):
        if url.endswith("/check_mount_usage"):
            raise TimeoutError("read timed out")
        return {"success": 1}

    calls = _install_send(monkeypatch, _timeout)

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    assert excinfo.value.reason == "node_timeout"
    assert _by_suffix(calls, "/create_container") == []


def test_restore_offline_machine_blocks_without_node_call(db_session, monkeypatch):
    root, machine, _container, snapshot, _cleanup = _prepare_restore(db_session, monkeypatch)
    machine.machine_status = MachineStatus.OFFLINE
    db_session.commit()
    calls = _install_send(
        monkeypatch,
        lambda url, payload: pytest.fail("offline machine must not be called"),
    )

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    assert excinfo.value.reason == "node_unavailable"
    assert calls == []


def test_restore_api_unknown_is_5xx_not_not_found(client, db_session, monkeypatch):
    _auth(monkeypatch)
    root, _machine, _container, snapshot, _cleanup = _prepare_restore(db_session, monkeypatch)
    path = snapshot.snapshot["bind_mount_path"]
    calls = _install_send(
        monkeypatch,
        lambda url, payload: (
            {"status_code": 404, "error": "Not Found"}
            if url.endswith("/check_mount_usage")
            else {"success": 1}
        ),
    )

    resp = client.post(
        "/api/containers/resurrect_container",
        json={"deleted_id": snapshot.id},
    )

    assert resp.status_code == 502
    assert resp.json()["error_reason"] == "node_unsupported"
    assert _by_suffix(calls, "/create_container") == []


def test_restore_refuses_duplicate_when_original_container_is_valid(
    db_session, monkeypatch,
):
    root, _machine, container, snapshot, cleanup = _prepare_restore(db_session, monkeypatch)
    record = containers_repo.get_by_id(
        container.id,
        session=db_session,
        include_invalid=True,
    )
    assert record is not None
    record.is_valid = True
    db_session.commit()
    calls = _install_send(
        monkeypatch,
        lambda url, payload: pytest.fail("duplicate restore must not reach Node"),
    )

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    assert excinfo.value.reason == "container_exists"
    assert calls == []
    db_session.expire_all()
    assert deleted_container_restore_snapshot_repo.get_by_id(snapshot.id, session=db_session) is not None
    assert container_mount_cleanup_repo.get_by_id(cleanup.id, session=db_session).cleaned_at is None


def test_restore_api_duplicate_valid_container_is_409(client, db_session, monkeypatch):
    _auth(monkeypatch)
    root, _machine, container, snapshot, _cleanup = _prepare_restore(db_session, monkeypatch)
    record = containers_repo.get_by_id(
        container.id,
        session=db_session,
        include_invalid=True,
    )
    record.is_valid = True
    db_session.commit()
    calls = _install_send(
        monkeypatch,
        lambda url, payload: pytest.fail("duplicate restore must not reach Node"),
    )

    resp = client.post(
        "/api/containers/resurrect_container",
        json={"deleted_id": snapshot.id},
    )

    assert resp.status_code == 409
    assert resp.json()["error_reason"] == "container_exists"
    assert calls == []


# ---------------------------------------------------------------------------
# 手动清理
# ---------------------------------------------------------------------------

def test_manual_cleanup_missing_path_is_rejected_and_not_marked_cleaned(
    db_session, monkeypatch,
):
    _machine, cleanup, deleted = _prepare_cleanup(db_session)
    path = cleanup.mount_path
    calls = _install_send(
        monkeypatch,
        lambda url, payload: _check_response(path, error="not_found"),
    )
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    result = container_tasks.clean_deleted_container_mount(
        mount_cleanup_id=cleanup.id,
        operator_user_id=7,
    )
    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "failed"
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["error_reason"] == "not_found"
    assert len(_by_suffix(calls, "/check_mount_usage")) == 1
    assert _by_suffix(calls, "/start_clean_mount") == []
    assert _by_suffix(calls, "/clean_mount") == []
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None
    assert db_session.get(DeletedContainerRestoreSnapshot, deleted.id).mount_cleaned is False
    log = db_session.scalars(select(OperationLog)).one()
    assert log.success is False
    assert log.error_reason == "not_found"
    assert log.detail["trigger"] == "manual_clean_mount"
    assert log.detail["mount_path"] == path


@pytest.mark.parametrize(
    "probe,reason",
    [
        ("permission_denied", "permission_denied"),
        ("invalid_path", "invalid_path"),
        ("old_node", "node_unsupported"),
        ("server_error", "node_unavailable"),
        ("bad_shape", "node_bad_response"),
    ],
)
def test_manual_cleanup_unverified_paths_keep_a_distinct_reason(
    db_session, monkeypatch, probe, reason,
):
    _machine, cleanup, deleted = _prepare_cleanup(db_session)

    def _respond(url, payload):
        if probe == "old_node":
            return {"status_code": 404, "error": "Not Found"}
        if probe == "server_error":
            return {"status_code": 500, "error": "boom"}
        if probe == "bad_shape":
            return {"success": 1}
        return _check_response(cleanup.mount_path, error=probe)

    calls = _install_send(monkeypatch, _respond)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    result = container_tasks.clean_deleted_container_mount(
        mount_cleanup_id=cleanup.id,
        operator_user_id=7,
    )
    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) in ("failed", "unknown")
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["error_reason"] == reason
    assert _by_suffix(calls, "/start_clean_mount") == []
    assert _by_suffix(calls, "/clean_mount") == []
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None
    assert db_session.get(DeletedContainerRestoreSnapshot, deleted.id).mount_cleaned is False


def test_manual_cleanup_transport_timeout_keeps_timeout_reason(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)

    def _timeout(url, payload, timeout=5.0):
        if url.endswith("/check_mount_usage"):
            raise TimeoutError("read timed out")
        return {"success": 1}

    calls = _install_send(monkeypatch, _timeout)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    result = container_tasks.clean_deleted_container_mount(
        mount_cleanup_id=cleanup.id,
        operator_user_id=7,
    )
    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "unknown"
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["error_reason"] == "node_timeout"
    assert _by_suffix(calls, "/start_clean_mount") == []
    assert _by_suffix(calls, "/clean_mount") == []


def test_manual_cleanup_offline_machine_never_calls_node_or_marks_cleaned(
    db_session, monkeypatch,
):
    machine = create_machine(
        machine_ip="127.0.60.12",
        machine_status=MachineStatus.OFFLINE,
    )
    _machine, cleanup, deleted = _prepare_cleanup(db_session, machine=machine)
    calls = _install_send(
        monkeypatch,
        lambda url, payload: pytest.fail("offline machine must not be called"),
    )
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    result = container_tasks.clean_deleted_container_mount(
        mount_cleanup_id=cleanup.id,
        operator_user_id=7,
    )
    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "unknown"
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["error_reason"] == "node_unavailable"
    assert calls == []
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None
    assert db_session.get(DeletedContainerRestoreSnapshot, deleted.id).mount_cleaned is False


def test_manual_cleanup_pending_means_present_then_cleans(db_session, monkeypatch):
    _machine, cleanup, deleted = _prepare_cleanup(db_session)
    path = cleanup.mount_path
    def _respond(url, payload):
        if url.endswith("/check_mount_usage"):
            return _check_response(path, pending=True)
        if url.endswith("/start_clean_mount"):
            return {"success": 1, "task_id": "task-pending"}
        if url.endswith("/get_clean_mount_status"):
            return {
                "success": 1,
                "task_id": "task-pending",
                "state": "succeeded",
                "error_reason": None,
            }
        raise AssertionError(f"unexpected node url: {url}")

    calls = _install_send(monkeypatch, _respond)
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    result = container_tasks.clean_deleted_container_mount(
        mount_cleanup_id=cleanup.id,
        operator_user_id=7,
    )

    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "succeeded"
    assert [call["url"].rsplit("/api/", 1)[-1] for call in calls] == [
        "check_mount_usage",
        "start_clean_mount",
        "get_clean_mount_status",
    ]
    assert calls[1]["payload"] == {"config": {"mount_path": path}}
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is not None
    assert db_session.get(DeletedContainerRestoreSnapshot, deleted.id).mount_cleaned is True


def test_manual_cleanup_already_cleaned_skips_path_probe(db_session, monkeypatch):
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)
    cleanup.cleaned_at = datetime(2026, 10, 2, 0, 0, 0)
    db_session.commit()
    calls = _install_send(
        monkeypatch,
        lambda url, payload: pytest.fail("already-cleaned record must not reach Node"),
    )

    result = container_tasks.clean_deleted_container_mount(
        mount_cleanup_id=cleanup.id,
        operator_user_id=7,
    )

    assert result["accepted"] is False
    assert result["already_cleaned"] is True
    assert result["mount_cleanup_state"] is None
    assert calls == []


def test_manual_cleanup_legacy_cleanup_only_record_is_guarded(db_session, monkeypatch):
    _machine, cleanup, deleted = _prepare_cleanup(db_session, link_deleted=False)
    assert deleted is None
    path = cleanup.mount_path
    calls = _install_send(
        monkeypatch,
        lambda url, payload: _check_response(path, error="not_found"),
    )

    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)
    result = container_tasks.clean_deleted_container_mount(
        mount_cleanup_id=cleanup.id,
        operator_user_id=7,
    )

    assert result["accepted"] is True
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "failed"
    assert mount_cleanup_tasks.describe_cleanup(cleanup.id)["error_reason"] == "not_found"
    assert _by_suffix(calls, "/start_clean_mount") == []
    assert _by_suffix(calls, "/clean_mount") == []
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None
    adopted = deleted_container_restore_snapshot_repo.get_by_mount_cleanup_id(
        cleanup.id,
        session=db_session,
    )
    assert adopted is not None
    assert adopted.mount_cleaned is False


def test_manual_cleanup_refuses_live_mount_of_restored_valid_container(
    db_session, monkeypatch,
):
    """恢复后原行有效、删除记录却残留：手动清理必须拒绝，不能 rm 活挂载目录。"""

    root, machine, container = create_container_graph()
    path = f"/home/{root.username}/containers/{container.name}_data"
    container.bind_mount_path = path
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
        removed_at=datetime(2026, 10, 1, 0, 0, 0),
        mount_cleaned=False,
    )
    cleanup.deleted_id = deleted.id
    db_session.commit()
    calls = _install_send(
        monkeypatch,
        lambda url, payload: pytest.fail("live mount must not reach Node"),
    )

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.clean_deleted_container_mount(
            mount_cleanup_id=cleanup.id,
            operator_user_id=root.id,
        )

    assert excinfo.value.reason == "container_exists"
    assert calls == []
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None
    assert db_session.get(DeletedContainerRestoreSnapshot, deleted.id).mount_cleaned is False
    live = db_session.get(type(container), container.id)
    assert live is not None and live.is_valid is True


def test_manual_cleanup_refuses_live_legacy_record_before_adoption(
    db_session, monkeypatch,
):
    """已恢复有效容器 + 仅 cleanup 的 legacy 记录：拒绝必须先于收养/补建快照。"""

    _root, machine, container = create_container_graph()
    path = f"/home/u/containers/{container.name}_legacy_data"
    container.bind_mount_path = path
    db_session.commit()
    cleanup = container_mount_cleanup_repo.insert(
        container_id=container.id,
        container_name=container.name,
        machine_id=machine.id,
        mount_path=path,
        session=db_session,
    )
    db_session.commit()
    calls = _install_send(
        monkeypatch,
        lambda url, payload: pytest.fail("live mount must not reach Node"),
    )

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.clean_deleted_container_mount(
            mount_cleanup_id=cleanup.id,
            operator_user_id=1,
        )

    assert excinfo.value.reason == "container_exists"
    assert calls == []
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None
    assert deleted_container_restore_snapshot_repo.get_by_mount_cleanup_id(
        cleanup.id,
        session=db_session,
    ) is None


def test_manual_cleanup_api_missing_path_is_accepted_then_failed(client, db_session, monkeypatch):
    _auth(monkeypatch)
    _machine, cleanup, _deleted = _prepare_cleanup(db_session)
    path = cleanup.mount_path
    calls = _install_send(
        monkeypatch,
        lambda url, payload: _check_response(path, error="not_found"),
    )
    monkeypatch.setattr(mount_cleanup_tasks, "POLL_INTERVAL_SECONDS", 0)

    resp = client.post(
        "/api/containers/clean_deleted_container_mount",
        json={"mount_cleanup_id": cleanup.id},
    )

    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    assert resp.json()["mount_cleanup_state"] == "cleaning"
    assert mount_cleanup_tasks.wait_for_cleanup(cleanup.id) == "failed"
    assert _by_suffix(calls, "/start_clean_mount") == []
    assert _by_suffix(calls, "/clean_mount") == []
    db_session.expire_all()
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at is None
