"""已删除容器挂载用量查询的隔离测试（SQLite + mock Node）。"""

import threading
import time
from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import event

from ...api import container_api, deps
from ...constant import MachineStatus
from ...models.container_mount_cleanup import ContainerMountCleanup
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...repositories import (
    container_mount_cleanup_repo,
    deleted_container_restore_snapshot_repo,
)
from ...services import container_tasks
from ...services.container_module import deleted_containers as deleted_module
from ...services.container_module import mount_usage, node_comms
from ..factories import create_machine

MEASURED_AT = "2026-10-18T12:00:00Z"


def _insert_deleted(
    db_session,
    *,
    machine=None,
    path="/home/u/containers/deleted_data",
    snapshot_machine_id="infer",
    cleanup_machine_id="infer",
    with_cleanup=True,
    row_mount_cleaned=False,
    cleanup_cleaned_at=None,
    snapshot_path="infer",
):
    """直接造删除快照/清理记录，避免借用会 ensure/adopt 的清理入参解析。"""

    if snapshot_machine_id == "infer":
        snapshot_machine_id = machine.id if machine else None
    if snapshot_path == "infer":
        snapshot_path = path

    cleanup = None
    if with_cleanup:
        if cleanup_machine_id == "infer":
            cleanup_machine_id = machine.id if machine else 0
        cleanup = container_mount_cleanup_repo.insert(
            container_id=999,
            container_name="deleted_usage_target",
            machine_id=cleanup_machine_id,
            mount_path=path,
            session=db_session,
        )

    row = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": 0,
            "container_name": "deleted_usage_target",
            "machine_id": snapshot_machine_id,
            "bind_mount_path": snapshot_path,
        },
        session=db_session,
        mount_cleanup_id=cleanup.id if cleanup is not None else None,
        removed_at=datetime(2026, 10, 18, 12, 0, 0),
        mount_cleaned=row_mount_cleaned,
    )
    if cleanup is not None:
        cleanup.deleted_id = row.id
        if cleanup_cleaned_at is not None:
            cleanup.cleaned_at = cleanup_cleaned_at
    db_session.commit()
    return row, cleanup


def _node_mount(path, *, bytes_value=None, measured_at=None, pending=False, error=None):
    return {
        "path": path,
        "bytes": bytes_value,
        "measured_at": measured_at,
        "pending": pending,
        "error": error,
    }


def _success_mount(path, bytes_value=123, measured_at=MEASURED_AT):
    return _node_mount(path, bytes_value=bytes_value, measured_at=measured_at)


def _pending_mount(path):
    return _node_mount(path, pending=True)


def _error_mount(path, reason="non_zero_exit"):
    return _node_mount(path, error=reason)


def _node_response(*mounts):
    return {"success": 1, "mounts": list(mounts)}


def _mock_send(monkeypatch, handler):
    calls = []

    def _send(url, payload, timeout=5.0, **kwargs):
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        return handler(url, payload)

    monkeypatch.setattr(node_comms, "send", _send)
    return calls


def _by_id(result):
    return {item["deleted_id"]: item for item in result["usages"]}


def _assert_usage_shape(item):
    assert set(item) == {"deleted_id", "bytes", "measured_at", "pending", "error"}


def _auth(monkeypatch, *, manage=True):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: 1)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_entity",
        lambda uid, code: manage or code != "container:manage",
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_resource",
        lambda *args, **kwargs: True,
    )


@contextmanager
def _capture_sql(db_session):
    statements = []
    engine = db_session.get_bind()

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


def _dml_statements(statements):
    return [
        statement for statement in statements
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]


def test_returns_three_states_including_cleaned(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.1")
    ok_path = "/home/u/containers/ok"
    slow_path = "/home/u/containers/slow"
    err_path = "/home/u/containers/err"
    ok, _ = _insert_deleted(db_session, machine=machine, path=ok_path)
    slow, _ = _insert_deleted(db_session, machine=machine, path=slow_path)
    err, _ = _insert_deleted(db_session, machine=machine, path=err_path)
    cleaned, _ = _insert_deleted(
        db_session,
        machine=machine,
        path="/home/u/containers/cleaned",
        row_mount_cleaned=True,
        cleanup_cleaned_at=datetime(2026, 10, 18, 12, 0, 0),
    )
    no_mount, _ = _insert_deleted(
        db_session,
        machine=machine,
        path=None,
        snapshot_path=None,
        with_cleanup=False,
    )
    calls = _mock_send(
        monkeypatch,
        lambda url, payload: _node_response(
            _success_mount(ok_path, bytes_value=0),
            _pending_mount(slow_path),
            _error_mount(err_path),
            _success_mount("/home/u/containers/cleaned", bytes_value=456),
        ),
    )

    result = container_tasks.get_deleted_container_mount_usage(
        [ok.id, slow.id, err.id, cleaned.id, no_mount.id, 999999, ok.id]
    )

    usages = _by_id(result)
    assert list(usages) == [ok.id, slow.id, err.id, cleaned.id, 999999]
    assert len(calls) == 1
    assert calls[0]["payload"] == {"config": {"mount_paths": [ok_path, slow_path, err_path, "/home/u/containers/cleaned"]}}
    assert calls[0]["timeout"] == mount_usage.NODE_QUERY_TIMEOUT_SECONDS

    assert usages[ok.id]["bytes"] == 0
    assert usages[ok.id]["measured_at"] == MEASURED_AT
    assert usages[ok.id]["pending"] is False
    assert usages[ok.id]["error"] is None

    assert usages[slow.id]["bytes"] is None
    assert usages[slow.id]["measured_at"] is None
    assert usages[slow.id]["pending"] is True
    assert usages[slow.id]["error"] is None

    assert usages[err.id]["bytes"] is None
    assert usages[err.id]["measured_at"] is None
    assert usages[err.id]["pending"] is False
    assert usages[err.id]["error"] == "non_zero_exit"

    assert usages[999999]["bytes"] is None
    assert usages[999999]["measured_at"] is None
    assert usages[999999]["pending"] is False
    assert usages[999999]["error"] == "not_found"

    for item in usages.values():
        _assert_usage_shape(item)
    assert usages[cleaned.id]["bytes"] == 456
    assert no_mount.id not in usages


def test_same_machine_same_path_sends_one_path_and_shares_result(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.2")
    path = "/home/u/containers/shared_same_machine"
    first, _ = _insert_deleted(db_session, machine=machine, path=path)
    second, _ = _insert_deleted(db_session, machine=machine, path=path)
    calls = _mock_send(
        monkeypatch,
        lambda url, payload: _node_response(_success_mount(path, bytes_value=456)),
    )

    result = container_tasks.get_deleted_container_mount_usage([first.id, second.id])

    assert len(calls) == 1
    assert calls[0]["payload"]["config"]["mount_paths"] == [path]
    usages = _by_id(result)
    assert usages[first.id]["bytes"] == 456
    assert usages[second.id]["bytes"] == 456


def test_same_path_across_machines_is_queried_per_machine(monkeypatch, db_session):
    left = create_machine(machine_ip="127.0.40.11")
    right = create_machine(machine_ip="127.0.40.12")
    path = "/home/u/containers/shared_cross_machine"
    left_row, _ = _insert_deleted(db_session, machine=left, path=path)
    right_row, _ = _insert_deleted(db_session, machine=right, path=path)

    def handler(url, payload):
        if "127.0.40.11" in url:
            return _node_response(_success_mount(path, bytes_value=111))
        if "127.0.40.12" in url:
            return _node_response(_success_mount(path, bytes_value=222))
        raise AssertionError(f"unexpected node url: {url}")

    calls = _mock_send(monkeypatch, handler)

    result = container_tasks.get_deleted_container_mount_usage([left_row.id, right_row.id])

    assert len(calls) == 2
    assert {call["payload"]["config"]["mount_paths"][0] for call in calls} == {path}
    usages = _by_id(result)
    assert usages[left_row.id]["bytes"] == 111
    assert usages[right_row.id]["bytes"] == 222


def test_uses_machine_specific_node_port(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.23")
    machine.port = 23456
    db_session.commit()
    path = "/home/u/containers/port_target"
    row, _ = _insert_deleted(db_session, machine=machine, path=path)
    calls = _mock_send(monkeypatch, lambda url, payload: _node_response(_success_mount(path)))

    container_tasks.get_deleted_container_mount_usage([row.id])

    assert calls[0]["url"] == "https://127.0.40.23:23456/api/check_mount_usage"


def test_one_machine_failure_does_not_block_other_machine(monkeypatch, db_session):
    failing = create_machine(machine_ip="127.0.40.19")
    healthy = create_machine(machine_ip="127.0.40.20")
    failing_path = "/home/u/containers/failing_machine"
    healthy_path = "/home/u/containers/healthy_machine"
    failing_row, _ = _insert_deleted(db_session, machine=failing, path=failing_path)
    healthy_row, _ = _insert_deleted(db_session, machine=healthy, path=healthy_path)

    def handler(url, payload):
        if "127.0.40.19" in url:
            return {"success": 0, "status_code": 500, "error": "internal"}
        return _node_response(_success_mount(healthy_path, bytes_value=777))

    _mock_send(monkeypatch, handler)

    result = container_tasks.get_deleted_container_mount_usage([failing_row.id, healthy_row.id])

    usages = _by_id(result)
    assert usages[failing_row.id]["error"] == "node_unavailable"
    assert usages[failing_row.id]["bytes"] is None
    assert usages[healthy_row.id]["bytes"] == 777
    assert usages[healthy_row.id]["error"] is None


def test_offline_machine_returns_unavailable_without_send(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.3", machine_status=MachineStatus.OFFLINE)
    row, _ = _insert_deleted(db_session, machine=machine)
    calls = _mock_send(monkeypatch, lambda url, payload: pytest.fail("offline machine must not be called"))

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    usage = _by_id(result)[row.id]
    assert calls == []
    assert usage["bytes"] is None
    assert usage["measured_at"] is None
    assert usage["pending"] is False
    assert usage["error"] == "node_unavailable"


@pytest.mark.parametrize("status_code", [404, 405])
def test_old_node_http_status_maps_unsupported(monkeypatch, db_session, status_code):
    machine = create_machine(machine_ip="127.0.40.4")
    row, _ = _insert_deleted(db_session, machine=machine)
    calls = _mock_send(
        monkeypatch,
        lambda url, payload: {"success": 0, "status_code": status_code, "error": "not found"},
    )

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    usage = _by_id(result)[row.id]
    assert len(calls) == 1
    assert usage["bytes"] is None
    assert usage["measured_at"] is None
    assert usage["pending"] is False
    assert usage["error"] == "node_unsupported"


def test_node_timeout_maps_timeout(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.5")
    row, _ = _insert_deleted(db_session, machine=machine)

    def handler(url, payload):
        raise TimeoutError("read timed out")

    _mock_send(monkeypatch, handler)

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    usage = _by_id(result)[row.id]
    assert usage["error"] == "node_timeout"
    assert usage["bytes"] is None
    assert usage["pending"] is False


def test_transport_error_string_timeout_is_classified_locally(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.6")
    row, _ = _insert_deleted(db_session, machine=machine)
    _mock_send(
        monkeypatch,
        lambda url, payload: {"error": "HTTPSConnectionPool(host='127.0.40.6'): Read timed out."},
    )

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    usage = _by_id(result)[row.id]
    assert usage["error"] == "node_timeout"
    assert usage["bytes"] is None


def test_connection_failure_and_5xx_map_unavailable(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.7")
    row, _ = _insert_deleted(db_session, machine=machine)

    def connection_handler(url, payload):
        raise ConnectionError("connection refused")

    _mock_send(monkeypatch, connection_handler)
    connection_usage = _by_id(
        container_tasks.get_deleted_container_mount_usage([row.id])
    )[row.id]

    _mock_send(
        monkeypatch,
        lambda url, payload: {"success": 0, "status_code": 500, "error": "internal"},
    )
    server_usage = _by_id(
        container_tasks.get_deleted_container_mount_usage([row.id])
    )[row.id]

    assert connection_usage["error"] == "node_unavailable"
    assert server_usage["error"] == "node_unavailable"
    assert connection_usage["bytes"] is None
    assert server_usage["bytes"] is None


@pytest.mark.parametrize(
    "kind",
    [
        "missing_path",
        "duplicate_path",
        "path_mismatch",
        "negative_bytes",
        "bool_bytes",
        "missing_measured_at",
        "naive_measured_at",
        "pending_with_bytes",
        "pending_as_int",
        "error_with_bytes",
        "unstable_error",
        "entry_not_dict",
        "mounts_not_list",
        "success_true_flag",
        "http_200_error_only",
        "http_200_missing_success",
    ],
)
def test_bad_node_response_is_never_success(monkeypatch, db_session, kind):
    machine = create_machine(machine_ip="127.0.40.8")
    path = "/home/u/containers/bad_response"
    row, _ = _insert_deleted(db_session, machine=machine, path=path)

    if kind == "missing_path":
        response = _node_response()
    elif kind == "duplicate_path":
        response = _node_response(_success_mount(path), _success_mount(path))
    elif kind == "path_mismatch":
        response = _node_response(_success_mount("/home/u/containers/other"))
    elif kind == "negative_bytes":
        response = _node_response(_success_mount(path, bytes_value=-1))
    elif kind == "bool_bytes":
        response = _node_response(_success_mount(path, bytes_value=True))
    elif kind == "missing_measured_at":
        response = _node_response(_success_mount(path, measured_at=None))
    elif kind == "naive_measured_at":
        response = _node_response(_success_mount(path, measured_at="2026-10-18T12:00:00"))
    elif kind == "pending_with_bytes":
        response = _node_response(_node_mount(path, bytes_value=0, pending=True))
    elif kind == "pending_as_int":
        response = _node_response(_node_mount(path, pending=1))
    elif kind == "error_with_bytes":
        response = _node_response(_node_mount(path, bytes_value=0, error="non_zero_exit"))
    elif kind == "unstable_error":
        response = _node_response(_node_mount(path, error="non_zero_exit: boom"))
    elif kind == "entry_not_dict":
        response = {"success": 1, "mounts": ["not-a-dict"]}
    elif kind == "mounts_not_list":
        response = {"success": 1, "mounts": {}}
    elif kind == "success_true_flag":
        response = {"success": True, "mounts": [_success_mount(path)]}
    elif kind == "http_200_error_only":
        response = {"status_code": 200, "error": "bad"}
    elif kind == "http_200_missing_success":
        response = {"status_code": 200, "mounts": [_success_mount(path)]}
    else:  # pragma: no cover
        raise AssertionError(kind)

    _mock_send(monkeypatch, lambda url, payload: response)

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    usage = _by_id(result)[row.id]
    assert usage["bytes"] is None
    assert usage["measured_at"] is None
    assert usage["pending"] is False
    assert usage["error"] == "node_bad_response"


def test_one_bad_path_does_not_poison_other_paths(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.22")
    good_path = "/home/u/containers/good_in_batch"
    bad_path = "/home/u/containers/bad_in_batch"
    good_row, _ = _insert_deleted(db_session, machine=machine, path=good_path)
    bad_row, _ = _insert_deleted(db_session, machine=machine, path=bad_path)
    _mock_send(
        monkeypatch,
        lambda url, payload: _node_response(
            _success_mount(good_path, bytes_value=42),
            _success_mount(bad_path, bytes_value=-1),
        ),
    )

    result = container_tasks.get_deleted_container_mount_usage([good_row.id, bad_row.id])

    usages = _by_id(result)
    assert usages[good_row.id]["bytes"] == 42
    assert usages[good_row.id]["error"] is None
    assert usages[bad_row.id]["bytes"] is None
    assert usages[bad_row.id]["error"] == "node_bad_response"


def test_pending_state_requires_all_explicit_fields():
    """回归：``{"pending": True}`` 不能因 .get 得到 None 就被当成有效 pending。"""

    assert mount_usage._normalize_mount_state({"pending": True}) is None
    assert mount_usage._normalize_mount_state({"path": "/x", "pending": True}) is None
    assert mount_usage._normalize_mount_state(
        {
            "path": "/x",
            "bytes": None,
            "measured_at": None,
            "pending": True,
            "error": None,
        }
    ) == {"bytes": None, "measured_at": None, "pending": True, "error": None}


@pytest.mark.parametrize("state", ["success", "pending", "error"])
@pytest.mark.parametrize("field", ["path", "bytes", "measured_at", "pending", "error"])
def test_missing_mount_field_is_bad_response(monkeypatch, db_session, state, field):
    """字段缺失不能借 ``dict.get`` 变成 None；每个三态字段都必须实际存在。"""

    machine = create_machine(machine_ip="127.0.42.30")
    path = "/home/u/containers/missing_field"
    row, _ = _insert_deleted(db_session, machine=machine, path=path)
    if state == "success":
        entry = _success_mount(path)
    elif state == "pending":
        entry = _pending_mount(path)
    else:
        entry = _error_mount(path)
    entry.pop(field)
    _mock_send(monkeypatch, lambda url, payload: _node_response(entry))

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    usage = _by_id(result)[row.id]
    assert usage["bytes"] is None
    assert usage["measured_at"] is None
    assert usage["pending"] is False
    assert usage["error"] == "node_bad_response"


@pytest.mark.parametrize("state", ["success", "pending", "error"])
@pytest.mark.parametrize("field", ["path", "bytes", "measured_at", "pending", "error"])
def test_empty_mount_field_is_bad_response(monkeypatch, db_session, state, field):
    """空串不是有效的 path/时间/状态；nullable 字段只接受显式 null。"""

    machine = create_machine(machine_ip="127.0.42.31")
    path = "/home/u/containers/empty_field"
    row, _ = _insert_deleted(db_session, machine=machine, path=path)
    if state == "success":
        entry = _success_mount(path)
    elif state == "pending":
        entry = _pending_mount(path)
    else:
        entry = _error_mount(path)
    entry[field] = ""
    _mock_send(monkeypatch, lambda url, payload: _node_response(entry))

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    usage = _by_id(result)[row.id]
    assert usage["bytes"] is None
    assert usage["measured_at"] is None
    assert usage["pending"] is False
    assert usage["error"] == "node_bad_response"


@pytest.mark.parametrize(
    "measured_at",
    [
        "2026-10-18T12:00:00Z",
        "2026-10-18T12:00:00.123456Z",
        "2026-10-18T12:00:00+00:00",
    ],
)
def test_valid_utc_iso_timestamp_variants_are_accepted(monkeypatch, db_session, measured_at):
    machine = create_machine(machine_ip="127.0.42.32")
    path = "/home/u/containers/utc_ok"
    row, _ = _insert_deleted(db_session, machine=machine, path=path)
    _mock_send(
        monkeypatch,
        lambda url, payload: _node_response(_success_mount(path, measured_at=measured_at)),
    )

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    usage = _by_id(result)[row.id]
    assert usage["bytes"] == 123
    assert usage["measured_at"] == measured_at
    assert usage["error"] is None


@pytest.mark.parametrize(
    "measured_at",
    [
        "2026-10-18",
        "2026-10-18 12:00:00+00:00",
        "2026-10-18T12:00:00",
        "2026-10-18T12:00:00+08:00",
        "2026-10-18T12:00:00.1234567Z",
        "",
        "not-a-time",
    ],
)
def test_non_utc_iso_timestamp_is_bad_response(monkeypatch, db_session, measured_at):
    machine = create_machine(machine_ip="127.0.42.33")
    path = "/home/u/containers/utc_bad"
    row, _ = _insert_deleted(db_session, machine=machine, path=path)
    _mock_send(
        monkeypatch,
        lambda url, payload: _node_response(_success_mount(path, measured_at=measured_at)),
    )

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    usage = _by_id(result)[row.id]
    assert usage["bytes"] is None
    assert usage["measured_at"] is None
    assert usage["pending"] is False
    assert usage["error"] == "node_bad_response"


@pytest.mark.parametrize(
    "reason",
    [
        "not_found",
        "invalid_path",
        "non_zero_exit",
        "timeout",
        "permission_denied",
        "empty_output",
        "parse_error",
        "du_unavailable",
        "du_failed",
    ],
)
def test_stable_node_error_reason_is_passed_through(monkeypatch, db_session, reason):
    machine = create_machine(machine_ip="127.0.40.9")
    path = "/home/u/containers/stable_error"
    row, _ = _insert_deleted(db_session, machine=machine, path=path)
    _mock_send(monkeypatch, lambda url, payload: _node_response(_error_mount(path, reason)))

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    usage = _by_id(result)[row.id]
    assert usage["bytes"] is None
    assert usage["measured_at"] is None
    assert usage["pending"] is False
    assert usage["error"] == reason


def test_repeated_query_has_no_ctrl_cache(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.10")
    path = "/home/u/containers/repeat_pending"
    row, _ = _insert_deleted(db_session, machine=machine, path=path)
    responses = [
        _node_response(_pending_mount(path)),
        _node_response(_success_mount(path, bytes_value=999)),
    ]

    def handler(url, payload):
        return responses.pop(0)

    calls = _mock_send(monkeypatch, handler)

    first = _by_id(container_tasks.get_deleted_container_mount_usage([row.id]))[row.id]
    second = _by_id(container_tasks.get_deleted_container_mount_usage([row.id]))[row.id]

    assert len(calls) == 2
    assert first["pending"] is True
    assert first["bytes"] is None
    assert second["pending"] is False
    assert second["bytes"] == 999


def test_readonly_resolution_does_not_write_or_call_write_helpers(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.13")
    path = "/home/u/containers/readonly"
    row, cleanup = _insert_deleted(db_session, machine=machine, path=path)

    def _unexpected(*args, **kwargs):
        raise AssertionError("write helper must not be called")

    original_context = deleted_module._get_deleted_container_context
    context_calls = []

    def _context(*args, **kwargs):
        context_calls.append(True)
        return original_context(*args, **kwargs)

    monkeypatch.setattr(deleted_module, "_get_deleted_container_context", _context)
    monkeypatch.setattr(deleted_module, "resolve_mount_cleanup_request", _unexpected)
    monkeypatch.setattr(deleted_module, "ensure_mount_cleanup_record", _unexpected)
    monkeypatch.setattr(deleted_module, "ensure_deleted_record_for_cleanup", _unexpected)
    _mock_send(monkeypatch, lambda url, payload: _node_response(_success_mount(path)))

    with _capture_sql(db_session) as statements:
        result = container_tasks.get_deleted_container_mount_usage([row.id])

    assert context_calls == [True]
    assert _dml_statements(statements) == []
    assert _by_id(result)[row.id]["bytes"] == 123
    db_session.expire_all()
    refreshed_row = db_session.get(DeletedContainerRestoreSnapshot, row.id)
    refreshed_cleanup = db_session.get(ContainerMountCleanup, cleanup.id)
    assert refreshed_row is not None
    assert refreshed_row.mount_cleaned is False
    assert refreshed_row.snapshot["bind_mount_path"] == path
    assert refreshed_cleanup is not None
    assert refreshed_cleanup.cleaned_at is None


def test_missing_machine_id_is_not_found_and_not_sent(monkeypatch, db_session):
    path = "/home/u/containers/orphan"
    row, _ = _insert_deleted(
        db_session,
        machine=None,
        path=path,
        snapshot_machine_id=None,
        with_cleanup=False,
    )
    calls = _mock_send(monkeypatch, lambda url, payload: pytest.fail("missing machine must not be called"))

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    usage = _by_id(result)[row.id]
    assert calls == []
    assert usage["error"] == "not_found"
    assert usage["bytes"] is None


def test_machine_id_falls_back_to_cleanup_record(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.14")
    path = "/home/u/containers/cleanup_machine"
    row, _ = _insert_deleted(
        db_session,
        machine=machine,
        path=path,
        snapshot_machine_id=None,
        cleanup_machine_id=machine.id,
    )
    calls = _mock_send(monkeypatch, lambda url, payload: _node_response(_success_mount(path)))

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    assert len(calls) == 1
    assert "127.0.40.14" in calls[0]["url"]
    assert _by_id(result)[row.id]["bytes"] == 123


@pytest.mark.parametrize(
    "row_cleaned, cleaned_at",
    [
        (True, None),
        (False, datetime(2026, 10, 18, 12, 0, 0)),
    ],
)
def test_cleaned_rows_with_paths_are_measured_read_only(
    monkeypatch, db_session, row_cleaned, cleaned_at,
):
    machine = create_machine(machine_ip="127.0.40.15")
    row, cleanup = _insert_deleted(
        db_session,
        machine=machine,
        row_mount_cleaned=row_cleaned,
        cleanup_cleaned_at=cleaned_at,
    )
    path = "/home/u/containers/deleted_data"
    calls = _mock_send(monkeypatch, lambda url, payload: _node_response(_success_mount(path)))

    with _capture_sql(db_session) as statements:
        result = container_tasks.get_deleted_container_mount_usage([row.id])

    assert _by_id(result)[row.id]["bytes"] == 123
    assert calls[0]["payload"] == {"config": {"mount_paths": [path]}}
    assert _dml_statements(statements) == []
    db_session.expire_all()
    assert db_session.get(DeletedContainerRestoreSnapshot, row.id).mount_cleaned == row_cleaned
    assert db_session.get(ContainerMountCleanup, cleanup.id).cleaned_at == cleaned_at


def test_row_without_mount_path_is_omitted_without_send(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.40.16")
    row, _ = _insert_deleted(
        db_session,
        machine=machine,
        path=None,
        snapshot_path=None,
        with_cleanup=False,
    )
    calls = _mock_send(monkeypatch, lambda url, payload: pytest.fail("no mount path must not be called"))

    result = container_tasks.get_deleted_container_mount_usage([row.id])

    assert result["usages"] == []
    assert calls == []


def test_node_requests_are_bounded(monkeypatch, db_session):
    import threading
    import time

    machines = [
        create_machine(machine_ip=f"127.0.41.{index}")
        for index in range(1, 11)
    ]
    rows = [
        _insert_deleted(db_session, machine=machine, path=f"/home/u/containers/bounded_{index}")[0]
        for index, machine in enumerate(machines, start=1)
    ]
    lock = threading.Lock()
    active = 0
    max_active = 0

    def handler(url, payload):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        path = payload["config"]["mount_paths"][0]
        with lock:
            active -= 1
        return _node_response(_success_mount(path, bytes_value=1))

    calls = _mock_send(monkeypatch, handler)

    result = container_tasks.get_deleted_container_mount_usage([row.id for row in rows])

    assert len(calls) == len(rows)
    assert max_active <= mount_usage.MAX_CONCURRENT_NODE_REQUESTS
    assert all(item["bytes"] == 1 for item in result["usages"])


def test_batch_deadline_keeps_fast_machine_success(monkeypatch, db_session):
    fast_machine = create_machine(machine_ip="127.0.42.1")
    slow_machine = create_machine(machine_ip="127.0.42.2")
    fast_path = "/home/u/containers/deadline_fast"
    slow_path = "/home/u/containers/deadline_slow"
    fast_row, _ = _insert_deleted(db_session, machine=fast_machine, path=fast_path)
    slow_row, _ = _insert_deleted(db_session, machine=slow_machine, path=slow_path)
    release = threading.Event()

    def handler(url, payload):
        if "127.0.42.1" in url:
            return _node_response(_success_mount(fast_path, bytes_value=11))
        release.wait(1.0)
        return _node_response(_success_mount(slow_path, bytes_value=22))

    _mock_send(monkeypatch, handler)
    started = time.monotonic()
    try:
        result = container_tasks.get_deleted_container_mount_usage(
            [fast_row.id, slow_row.id],
            deadline_seconds=0.5,
        )
    finally:
        elapsed = time.monotonic() - started
        release.set()

    usages = _by_id(result)
    assert usages[fast_row.id]["bytes"] == 11
    assert usages[fast_row.id]["error"] is None
    assert usages[slow_row.id]["error"] == "node_timeout"
    assert usages[slow_row.id]["bytes"] is None
    assert elapsed < 1.0


def test_batch_deadline_expires_without_waiting_for_slow_node(monkeypatch, db_session):
    machine = create_machine(machine_ip="127.0.42.3")
    path = "/home/u/containers/deadline_budget"
    row, _ = _insert_deleted(db_session, machine=machine, path=path)
    release = threading.Event()

    def handler(url, payload):
        release.wait(1.0)
        return _node_response(_success_mount(path))

    _mock_send(monkeypatch, handler)
    started = time.monotonic()
    try:
        result = container_tasks.get_deleted_container_mount_usage(
            [row.id],
            deadline_seconds=0.1,
        )
    finally:
        elapsed = time.monotonic() - started
        release.set()

    usage = _by_id(result)[row.id]
    assert usage["error"] == "node_timeout"
    assert usage["bytes"] is None
    assert usage["pending"] is False
    assert elapsed < 0.8


def test_batch_deadline_cancels_queued_work_and_bounds_concurrency(monkeypatch, db_session):
    monkeypatch.setattr(mount_usage, "MAX_CONCURRENT_NODE_REQUESTS", 2)
    machines = [
        create_machine(machine_ip=f"127.0.42.{index}")
        for index in range(10, 14)
    ]
    rows = [
        _insert_deleted(
            db_session,
            machine=machine,
            path=f"/home/u/containers/deadline_queued_{index}",
        )[0]
        for index, machine in enumerate(machines, start=10)
    ]
    release = threading.Event()
    done = threading.Event()
    lock = threading.Lock()
    started = []
    active = 0
    max_active = 0
    completed = 0

    def handler(url, payload):
        nonlocal active, max_active, completed
        with lock:
            active += 1
            max_active = max(max_active, active)
            started.append(url)
        try:
            release.wait(1.0)
        finally:
            with lock:
                active -= 1
                completed += 1
                if active == 0:
                    done.set()
        path = payload["config"]["mount_paths"][0]
        return _node_response(_success_mount(path, bytes_value=5))

    _mock_send(monkeypatch, handler)
    try:
        result = container_tasks.get_deleted_container_mount_usage(
            [row.id for row in rows],
            deadline_seconds=0.5,
        )
        assert 1 <= len(started) <= 2
        assert max_active <= 2
        assert all(item["error"] == "node_timeout" for item in result["usages"])
    finally:
        release.set()

    assert done.wait(1.0)
    time.sleep(0.1)
    assert len(started) <= 2


def test_api_success_returns_fixed_shape_without_path(client, monkeypatch, db_session):
    _auth(monkeypatch)
    machine = create_machine(machine_ip="127.0.40.17")
    path = "/home/u/containers/api_shape"
    row, _ = _insert_deleted(db_session, machine=machine, path=path)
    _mock_send(monkeypatch, lambda url, payload: _node_response(_success_mount(path, bytes_value=321)))

    resp = client.post(
        "/api/containers/get_deleted_container_mount_usage",
        json={"deleted_ids": [row.id]},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] == 1
    assert len(payload["usages"]) == 1
    item = payload["usages"][0]
    _assert_usage_shape(item)
    assert "path" not in item
    assert item["deleted_id"] == row.id
    assert item["bytes"] == 321
    assert item["measured_at"] == MEASURED_AT
    assert item["pending"] is False
    assert item["error"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"deleted_ids": [0]},
        {"deleted_ids": [-1]},
        {"deleted_ids": [True]},
        {"deleted_ids": [1.0]},
        {"deleted_ids": ["1"]},
        {"deleted_ids": [None]},
        {"deleted_ids": "1"},
        {"deleted_ids": list(range(1, 102))},
        {"deleted_ids": [1], "mount_path": "/home/u/containers/browser_path"},
        {"deleted_ids": [1], "machine_id": 2},
    ],
)
def test_api_rejects_invalid_payload_and_extra_fields(client, monkeypatch, body):
    _auth(monkeypatch)
    calls = _mock_send(monkeypatch, lambda url, payload: pytest.fail("invalid payload must not reach Node"))

    resp = client.post(
        "/api/containers/get_deleted_container_mount_usage",
        json=body,
    )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_payload"
    assert calls == []


def test_api_missing_body_returns_invalid_payload(client, monkeypatch):
    _auth(monkeypatch)
    calls = _mock_send(monkeypatch, lambda url, payload: pytest.fail("missing body must not reach Node"))

    resp = client.post("/api/containers/get_deleted_container_mount_usage")

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_payload"
    assert calls == []


def test_api_dedupes_ids_preserving_input_order(client, monkeypatch):
    _auth(monkeypatch)
    captured = {}

    def _query(deleted_ids):
        captured["deleted_ids"] = deleted_ids
        return {"usages": []}

    monkeypatch.setattr(container_api.container_service, "get_deleted_container_mount_usage", _query)

    resp = client.post(
        "/api/containers/get_deleted_container_mount_usage",
        json={"deleted_ids": [3, 1, 3, 2, 1]},
    )

    assert resp.status_code == 200
    assert captured["deleted_ids"] == [3, 1, 2]


def test_api_accepts_exactly_100_ids(client, monkeypatch):
    _auth(monkeypatch)
    captured = {}

    def _query(deleted_ids):
        captured["deleted_ids"] = deleted_ids
        return {"usages": []}

    monkeypatch.setattr(container_api.container_service, "get_deleted_container_mount_usage", _query)
    ids = list(range(1, 101))

    resp = client.post(
        "/api/containers/get_deleted_container_mount_usage",
        json={"deleted_ids": ids},
    )

    assert resp.status_code == 200
    assert resp.json() == {"success": 1, "usages": []}
    assert captured["deleted_ids"] == ids


def test_api_queries_cleaned_and_omits_no_mount(client, monkeypatch, db_session):
    _auth(monkeypatch)
    machine = create_machine(machine_ip="127.0.40.21")
    cleaned, _ = _insert_deleted(
        db_session,
        machine=machine,
        path="/home/u/containers/api_cleaned",
        row_mount_cleaned=True,
        cleanup_cleaned_at=datetime(2026, 10, 18, 12, 0, 0),
    )
    no_mount, _ = _insert_deleted(
        db_session,
        machine=machine,
        path=None,
        snapshot_path=None,
        with_cleanup=False,
    )
    path = "/home/u/containers/api_cleaned"
    calls = _mock_send(monkeypatch, lambda url, payload: _node_response(_error_mount(path, "not_found")))

    resp = client.post(
        "/api/containers/get_deleted_container_mount_usage",
        json={"deleted_ids": [cleaned.id, no_mount.id]},
    )

    assert resp.status_code == 200
    assert _by_id(resp.json())[cleaned.id]["error"] == "not_found"
    assert no_mount.id not in _by_id(resp.json())
    assert calls[0]["payload"] == {"config": {"mount_paths": [path]}}


def test_api_requires_container_manage(client, monkeypatch):
    _auth(monkeypatch, manage=False)
    calls = _mock_send(monkeypatch, lambda url, payload: pytest.fail("permission denied must not reach Node"))

    resp = client.post(
        "/api/containers/get_deleted_container_mount_usage",
        json={"deleted_ids": [1]},
    )

    assert resp.status_code == 403
    assert resp.json()["error_reason"] == "insufficient_permission"
    assert calls == []


def test_api_does_not_require_machine_role(client, monkeypatch, db_session):
    _auth(monkeypatch)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_resource",
        lambda *args, **kwargs: False,
    )
    machine = create_machine(machine_ip="127.0.40.18")
    path = "/home/u/containers/no_machine_role"
    row, _ = _insert_deleted(db_session, machine=machine, path=path)
    _mock_send(monkeypatch, lambda url, payload: _node_response(_success_mount(path)))

    resp = client.post(
        "/api/containers/get_deleted_container_mount_usage",
        json={"deleted_ids": [row.id]},
    )

    assert resp.status_code == 200
    assert resp.json()["usages"][0]["bytes"] == 123


def test_api_empty_list_returns_empty_success(client, monkeypatch):
    _auth(monkeypatch)
    calls = _mock_send(monkeypatch, lambda url, payload: pytest.fail("empty list must not reach Node"))

    resp = client.post(
        "/api/containers/get_deleted_container_mount_usage",
        json={"deleted_ids": []},
    )

    assert resp.status_code == 200
    assert resp.json() == {"success": 1, "usages": []}
    assert calls == []


def test_api_unknown_id_returns_not_found_usage(client, monkeypatch):
    _auth(monkeypatch)
    calls = _mock_send(monkeypatch, lambda url, payload: pytest.fail("unknown id must not reach Node"))

    resp = client.post(
        "/api/containers/get_deleted_container_mount_usage",
        json={"deleted_ids": [123456]},
    )

    assert resp.status_code == 200
    item = resp.json()["usages"][0]
    _assert_usage_shape(item)
    assert item["deleted_id"] == 123456
    assert item["bytes"] is None
    assert item["measured_at"] is None
    assert item["pending"] is False
    assert item["error"] == "not_found"
    assert calls == []
