"""Ctrl-side in-process mount cleanup tasks and restore reservations.

This module owns only process-local coordination. It never persists task state
and never adds a database column. Node remains the authority for realpath
identity; the Ctrl key is a lexical pre-filter and is not equivalent to Node's
realpath reservation for alias tail windows.
"""

from __future__ import annotations

import logging
import posixpath
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

from ...constant import OperationType
from ...extensions import session_scope
from ...repositories import (
    container_mount_cleanup_repo,
    containers_repo,
    deleted_container_restore_snapshot_repo,
    machine_repo,
)
from ..operation_log_tasks import log_failure, log_success
from . import node_comms
from .exceptions import NodeServiceError, safe_reason
from .mount_usage import (
    MOUNT_INVALID_PATH,
    MOUNT_MISSING,
    MOUNT_PERMISSION_DENIED,
    MOUNT_PRESENT,
    probe_mount_path,
)
from .node_comms_modules.endpoint import resolve_endpoint
from .utils import _container_log_detail

logger = logging.getLogger(__name__)

MAX_ACTIVE_TASKS = 128
MAX_TERMINAL_SUMMARIES = 512
TERMINAL_TTL_SECONDS = 900.0
START_TIMEOUT_SECONDS = 10.0
STATUS_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 1.0
STATUS_RETRY_INTERVAL_SECONDS = 2.0
MAX_CONSECUTIVE_STATUS_FAILURES = 3

CLEANUP_IN_PROGRESS = "cleanup_in_progress"
RESTORE_IN_PROGRESS = "restore_in_progress"
CLEANUP_CAPACITY_EXHAUSTED = "cleanup_capacity_exhausted"
CLEANUP_NOT_ACCEPTED = "cleanup_not_accepted"
CLEANUP_RESULT_UNKNOWN = "cleanup_result_unknown"
CLEANUP_PERSIST_FAILED = "cleanup_persist_failed"
CLEANUP_FAILED = "cleanup_failed"
CLEANUP_TARGET_CHANGED = "cleanup_target_changed"
NODE_TASK_LOST = "node_task_lost"

_TRANSIENT_STATUS_FAILURES = frozenset({"node_timeout", "node_unavailable"})

_TERMINAL_STATES = frozenset({"succeeded", "failed", "unknown"})
_ACTIVE_STATES = frozenset({"accepted", "running", "restoring"})


@dataclass
class _Task:
    cleanup_id: int
    deleted_id: int | None
    machine_id: int
    mount_path: str
    canonical_path: str
    container_name: str | None
    trigger: str
    operator_user_id: int | None
    escalation: bool | None
    verify_mount_path: bool
    kind: str = "cleanup"
    state: str = "accepted"
    node_task_id: str | None = None
    error_reason: str | None = None
    accepted_at: datetime = field(default_factory=datetime.utcnow)
    finished_monotonic: float | None = None
    result_logged: bool = False
    thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        return self.state in _ACTIVE_STATES

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL_STATES


_LOCK = threading.RLock()
_ACTIVE_BY_KEY: dict[tuple[int, str], _Task] = {}
_BY_CLEANUP_ID: dict[int, _Task] = {}


def canonical_mount_path(mount_path: str) -> str:
    """Ctrl-only lexical key. Node realpath remains the final authority."""

    text = str(mount_path or "").strip()
    if not text or not text.startswith("/"):
        raise NodeServiceError("mount path is not an absolute path", reason=MOUNT_INVALID_PATH)
    normalized = posixpath.normpath(text)
    if normalized in ("", "/", "."):
        raise NodeServiceError("mount path is not a usable directory path", reason=MOUNT_INVALID_PATH)
    return normalized


def _prune_locked(now: float) -> None:
    expired = [
        cleanup_id
        for cleanup_id, task in list(_BY_CLEANUP_ID.items())
        if task.terminal
        and task.finished_monotonic is not None
        and now - task.finished_monotonic >= TERMINAL_TTL_SECONDS
    ]
    for cleanup_id in expired:
        _BY_CLEANUP_ID.pop(cleanup_id, None)

    terminal = [
        (task.finished_monotonic or 0.0, cleanup_id)
        for cleanup_id, task in _BY_CLEANUP_ID.items()
        if task.terminal
    ]
    if len(terminal) > MAX_TERMINAL_SUMMARIES:
        for _finished, cleanup_id in sorted(terminal)[: len(terminal) - MAX_TERMINAL_SUMMARIES]:
            _BY_CLEANUP_ID.pop(cleanup_id, None)


def _active_cleanup_count_locked() -> int:
    return sum(1 for task in _ACTIVE_BY_KEY.values() if task.kind == "cleanup" and task.active)


def _busy_reason(existing: _Task) -> str:
    if existing.kind == "restore":
        return RESTORE_IN_PROGRESS
    return CLEANUP_IN_PROGRESS


def _begin_cleanup(
    *,
    cleanup_id: int,
    deleted_id: int | None,
    machine_id: int,
    mount_path: str,
    canonical_path: str,
    container_name: str | None,
    trigger: str,
    operator_user_id: int | None,
    escalation: bool | None,
    verify_mount_path: bool,
) -> _Task:
    key = (int(machine_id), canonical_path)
    now = time.monotonic()
    with _LOCK:
        _prune_locked(now)
        existing = _ACTIVE_BY_KEY.get(key)
        if existing is not None:
            raise NodeServiceError(
                f"mount path is busy with {existing.kind}",
                reason=_busy_reason(existing),
            )
        if _active_cleanup_count_locked() >= MAX_ACTIVE_TASKS:
            raise NodeServiceError(
                "too many active mount cleanup tasks",
                reason=CLEANUP_CAPACITY_EXHAUSTED,
            )
        task = _Task(
            cleanup_id=int(cleanup_id),
            deleted_id=int(deleted_id) if deleted_id is not None else None,
            machine_id=int(machine_id),
            mount_path=str(mount_path),
            canonical_path=canonical_path,
            container_name=container_name,
            trigger=trigger,
            operator_user_id=operator_user_id,
            escalation=escalation,
            verify_mount_path=bool(verify_mount_path),
        )
        _ACTIVE_BY_KEY[key] = task
        _BY_CLEANUP_ID[task.cleanup_id] = task
        return task


def _finish_locked(task: _Task, state: str, error_reason: str | None = None) -> bool:
    if task.terminal:
        return False
    task.state = state
    task.error_reason = error_reason
    task.finished_monotonic = time.monotonic()
    _ACTIVE_BY_KEY.pop((task.machine_id, task.canonical_path), None)
    _prune_locked(task.finished_monotonic)
    return True


def _finish(task: _Task, state: str, error_reason: str | None = None) -> bool:
    with _LOCK:
        return _finish_locked(task, state, error_reason)


def _task_detail(task: _Task) -> dict:
    detail = _container_log_detail(task.container_name)
    detail.update({
        "trigger": task.trigger,
        "deleted_id": task.deleted_id,
        "machine_id": task.machine_id,
        "mount_path": task.mount_path,
        "task_id": task.node_task_id,
        "escalation": bool(task.escalation),
    })
    return detail


def _log_failure(task: _Task, reason: str) -> None:
    log_failure(
        operator_user_id=task.operator_user_id,
        operation=OperationType.DELETE_CONTAINER,
        target_type="container_mount_cleanup",
        target_id=task.cleanup_id,
        error_reason=safe_reason(reason, CLEANUP_FAILED),
        detail=_task_detail(task),
    )


def _log_success(task: _Task) -> None:
    log_success(
        operator_user_id=task.operator_user_id,
        operation=OperationType.DELETE_CONTAINER,
        target_type="container_mount_cleanup",
        target_id=task.cleanup_id,
        detail=_task_detail(task),
    )


def _fail(task: _Task, reason: str, *, unknown: bool = False) -> None:
    state = "unknown" if unknown else "failed"
    normalized = safe_reason(
        reason,
        CLEANUP_RESULT_UNKNOWN if unknown else CLEANUP_FAILED,
    )
    if _finish(task, state, normalized):
        _log_failure(task, normalized)


def _persist_success(task: _Task) -> tuple[bool, str | None]:
    """Commit cleanup + snapshot in one transaction. Returns (already, error)."""

    try:
        with session_scope() as session:
            cleanup = container_mount_cleanup_repo.get_by_id(task.cleanup_id, session=session)
            if cleanup is None:
                raise NodeServiceError("mount cleanup record not found", reason="not_found")
            already = cleanup.cleaned_at is not None
            if not already:
                container_mount_cleanup_repo.mark_cleaned(
                    task.cleanup_id,
                    session=session,
                    escalation=task.escalation,
                )
            deleted_id = getattr(cleanup, "deleted_id", None)
            deleted = (
                deleted_container_restore_snapshot_repo.get_by_id(deleted_id, session=session)
                if deleted_id is not None
                else deleted_container_restore_snapshot_repo.get_by_mount_cleanup_id(
                    task.cleanup_id,
                    session=session,
                )
            )
            if deleted is not None:
                deleted_container_restore_snapshot_repo.mark_mount_cleaned(
                    deleted.id,
                    session=session,
                )
            if task.deleted_id is None and deleted_id is not None:
                task.deleted_id = int(deleted_id)
        return already, None
    except Exception as exc:
        return False, safe_reason(exc, CLEANUP_PERSIST_FAILED)


def _resolve_target(cleanup, session) -> tuple[int, str, str | None]:
    """Resolve the same business target the old sync path used.

    The associated container row is authoritative for machine_id/bind_mount_path;
    the cleanup row is only a fallback when the container no longer exists.
    """

    container = containers_repo.get_by_id(
        cleanup.container_id,
        session=session,
        include_invalid=True,
    )
    machine_id = getattr(container, "machine_id", None) or cleanup.machine_id
    mount_path = getattr(container, "bind_mount_path", None) or cleanup.mount_path
    container_name = getattr(container, "name", None) or cleanup.container_name
    return int(machine_id), str(mount_path), container_name


def _load_task_record(task: _Task) -> dict | None:
    with session_scope(commit=False) as session:
        cleanup = container_mount_cleanup_repo.get_by_id(task.cleanup_id, session=session)
        if cleanup is None:
            return None
        machine_id, mount_path, container_name = _resolve_target(cleanup, session)
        return {
            "cleaned_at": cleanup.cleaned_at,
            "machine_id": machine_id,
            "mount_path": mount_path,
            "container_name": container_name,
            "deleted_id": getattr(cleanup, "deleted_id", None),
        }


def _manual_live_container_guard(task: _Task) -> None:
    """After the cleanup reservation, re-check the existing container row.

    The pre-submit check can race with a restore that completes before the
    reservation is acquired. This second check uses only existing
    ``containers.is_valid`` data and runs before any Node request.
    """

    container_ids: set[int] = set()
    with session_scope(commit=False) as session:
        cleanup = container_mount_cleanup_repo.get_by_id(task.cleanup_id, session=session)
        if cleanup is None:
            return
        try:
            container_ids.add(int(cleanup.container_id))
        except (TypeError, ValueError):
            pass
        deleted = (
            deleted_container_restore_snapshot_repo.get_by_id(
                cleanup.deleted_id,
                session=session,
            )
            if getattr(cleanup, "deleted_id", None) is not None
            else deleted_container_restore_snapshot_repo.get_by_mount_cleanup_id(
                task.cleanup_id,
                session=session,
            )
        )
        if deleted is not None:
            snapshot = dict(getattr(deleted, "snapshot", None) or {})
            for value in (
                getattr(deleted, "original_container_id", None),
                snapshot.get("container_id"),
            ):
                try:
                    container_ids.add(int(value))
                except (TypeError, ValueError):
                    continue

    for container_id in container_ids:
        if container_id <= 0:
            continue
        with session_scope(commit=False) as session:
            container = containers_repo.get_by_id(
                container_id,
                session=session,
                include_invalid=True,
            )
        if container is not None and bool(getattr(container, "is_valid", False)):
            raise NodeServiceError(
                "container is valid again; live mount path must not be cleaned",
                reason="container_exists",
            )


def _target_unchanged(task: _Task, record: dict) -> bool:
    """Re-read target must stay on the already-reserved machine/path key."""

    try:
        fresh_machine_id = int(record["machine_id"])
        fresh_mount_path = str(record["mount_path"])
        fresh_canonical = canonical_mount_path(fresh_mount_path)
    except Exception:
        return False
    if (
        fresh_machine_id != task.machine_id
        or fresh_mount_path != task.mount_path
        or fresh_canonical != task.canonical_path
    ):
        return False
    return True


def _endpoint_for(machine_id: int) -> tuple[str, int]:
    with session_scope(commit=False) as session:
        machine_ip, machine_port = machine_repo.get_machine_endpoint_by_id(
            machine_id,
            session=session,
        )
    return resolve_endpoint(machine_ip, machine_port)


def _transport_reason(response: dict, default: str) -> str:
    status = response.get("status_code")
    if type(status) is int:
        if status in (404, 405):
            return "node_unsupported"
        if status == 408:
            return "node_timeout"
        if 500 <= status <= 599:
            return "node_unavailable"
    message = str(response.get("error") or "").lower()
    if "timeout" in message or "timed out" in message:
        return "node_timeout"
    if "error" in response:
        return "node_unavailable"
    return default


def _normalize_task_id(value) -> str | None:
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _start_node_task(host: str, port: int, mount_path: str) -> tuple[str | None, str | None, bool]:
    """Return (task_id, reason, unknown)."""

    url = node_comms.get_full_url(host, "/start_clean_mount", port)
    response = node_comms.send(
        url,
        {"config": {"mount_path": mount_path}},
        timeout=START_TIMEOUT_SECONDS,
    )
    if not isinstance(response, dict):
        return None, "node_bad_response", True
    status = response.get("status_code")
    if status in (404, 405):
        return None, "node_unsupported", False
    if status is not None and type(status) is int and not (200 <= status <= 299):
        if status == 409:
            return None, safe_reason(response.get("error_reason"), CLEANUP_IN_PROGRESS), False
        if response.get("error_reason"):
            return None, safe_reason(response.get("error_reason"), CLEANUP_FAILED), False
        return None, _transport_reason(response, "node_unavailable"), True
    if "success" not in response and "error" in response:
        return None, _transport_reason(response, "node_unavailable"), True
    if response.get("success") == 1:
        task_id = _normalize_task_id(response.get("task_id"))
        if task_id is None:
            return None, "node_bad_response", True
        return task_id, None, False
    reason = safe_reason(response.get("error_reason"), CLEANUP_FAILED)
    return None, reason, False


def _status_node_task(host: str, port: int, task_id: str) -> tuple[str | None, str | None, str | None]:
    """Return (state, error_reason, failure_reason). Unknown failure has state None."""

    url = node_comms.get_full_url(host, "/get_clean_mount_status", port)
    try:
        response = node_comms.send(
            url,
            {"config": {"task_id": task_id}},
            timeout=STATUS_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        text = f"{type(exc).__name__} {exc}".lower()
        return None, None, "node_timeout" if "timeout" in text or "timed out" in text else "node_unavailable"
    if not isinstance(response, dict):
        return None, None, "node_bad_response"
    response_reason = response.get("error_reason")
    if response_reason in ("task_not_found", "cleanup_task_not_found"):
        return None, None, NODE_TASK_LOST
    status = response.get("status_code")
    # Node's actual task-missing shape is HTTP 404 + error_reason='not_found'.
    # A bare route 404/405 without that structure is an old/unsupported endpoint.
    if status == 404 and response_reason == "not_found":
        return None, None, NODE_TASK_LOST
    if status in (404, 405):
        return None, None, "node_unsupported"
    if status is not None and type(status) is int and not (200 <= status <= 299):
        return None, None, _transport_reason(response, "node_unavailable")
    if "success" not in response and "error" in response:
        return None, None, _transport_reason(response, "node_unavailable")
    if "success" in response and response.get("success") != 1:
        return None, None, "node_bad_response"
    echoed = _normalize_task_id(response.get("task_id"))
    if echoed != task_id:
        return None, None, "node_bad_response"
    state = response.get("state")
    if state not in ("running", "succeeded", "failed"):
        return None, None, "node_bad_response"
    error_reason = response.get("error_reason")
    if state in ("running", "succeeded"):
        if error_reason not in (None, ""):
            return None, None, "node_bad_response"
        return state, None, None
    if not isinstance(error_reason, str) or not error_reason.strip():
        return None, None, "node_bad_response"
    return state, error_reason, None


def _manual_precheck(task: _Task) -> tuple[str | None, bool]:
    """Return (failure_reason, unknown). ``None`` means present."""

    probe = probe_mount_path(task.machine_id, task.mount_path)
    state = probe.get("state")
    if state == MOUNT_PRESENT:
        return None, False
    if state == MOUNT_MISSING:
        return "not_found", False
    if state in (MOUNT_PERMISSION_DENIED, MOUNT_INVALID_PATH):
        return state, False
    return safe_reason(state, "node_bad_response"), True


def _run_worker(task: _Task) -> None:
    try:
        record = _load_task_record(task)
        if record is None:
            _fail(task, "not_found")
            return
        if record["cleaned_at"] is not None:
            _finish(task, "succeeded")
            return
        if not _target_unchanged(task, record):
            _fail(task, CLEANUP_TARGET_CHANGED)
            return
        task.container_name = record["container_name"]
        if record["deleted_id"] is not None:
            task.deleted_id = int(record["deleted_id"])
        else:
            with session_scope(commit=False) as session:
                deleted = deleted_container_restore_snapshot_repo.get_by_mount_cleanup_id(
                    task.cleanup_id,
                    session=session,
                )
            if deleted is not None:
                task.deleted_id = int(deleted.id)

        if task.verify_mount_path:
            failure, unknown = _manual_precheck(task)
            if failure is not None:
                _fail(task, failure, unknown=unknown)
                return
            try:
                _manual_live_container_guard(task)
            except Exception as exc:
                _fail(task, safe_reason(exc, "container_exists"))
                return

        try:
            host, port = _endpoint_for(task.machine_id)
        except Exception as exc:
            _fail(task, safe_reason(exc, "node_unavailable"), unknown=True)
            return

        task_id, start_error, start_unknown = _start_node_task(host, port, task.mount_path)
        if task_id is None:
            _fail(task, start_error or "node_bad_response", unknown=start_unknown)
            return
        task.node_task_id = task_id
        with _LOCK:
            task.state = "running"

        consecutive_status_failures = 0
        while True:
            state, error_reason, status_error = _status_node_task(host, port, task_id)
            if state == "running":
                consecutive_status_failures = 0
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            if state == "succeeded":
                already, persist_error = _persist_success(task)
                if persist_error is not None:
                    _fail(task, persist_error, unknown=True)
                    return
                if _finish(task, "succeeded"):
                    if not already:
                        _log_success(task)
                return
            if state == "failed":
                _fail(task, safe_reason(error_reason, CLEANUP_FAILED))
                return
            if status_error in _TRANSIENT_STATUS_FAILURES:
                consecutive_status_failures += 1
                if consecutive_status_failures >= MAX_CONSECUTIVE_STATUS_FAILURES:
                    _fail(task, status_error, unknown=True)
                    return
                time.sleep(STATUS_RETRY_INTERVAL_SECONDS)
                continue
            _fail(task, status_error or CLEANUP_RESULT_UNKNOWN, unknown=True)
            return
    except Exception as exc:
        _fail(task, safe_reason(exc, CLEANUP_FAILED), unknown=True)


def _spawn(task: _Task) -> None:
    try:
        thread = threading.Thread(
            target=_run_worker,
            args=(task,),
            name=f"mount-cleanup-{task.cleanup_id}",
            daemon=True,
        )
        task.thread = thread
        thread.start()
    except Exception as exc:
        with _LOCK:
            _ACTIVE_BY_KEY.pop((task.machine_id, task.canonical_path), None)
            _BY_CLEANUP_ID.pop(task.cleanup_id, None)
        raise NodeServiceError(
            "mount cleanup background task was not started",
            reason=CLEANUP_NOT_ACCEPTED,
        ) from exc


def start_cleanup(
    cleanup_id: int,
    *,
    trigger: str,
    operator_user_id: int | None = None,
    escalation: bool | None = None,
    verify_mount_path: bool = False,
) -> dict:
    """Read the cleanup record and submit it to a daemon worker."""

    with session_scope(commit=False) as session:
        cleanup = container_mount_cleanup_repo.get_by_id(int(cleanup_id), session=session)
        if cleanup is None:
            raise NodeServiceError("mount cleanup record not found", reason="not_found")
        if cleanup.cleaned_at is not None:
            return {
                "accepted": False,
                "already_cleaned": True,
                "mount_cleanup_id": int(cleanup.id),
                "deleted_id": getattr(cleanup, "deleted_id", None),
                "mount_cleanup_state": None,
            }
        machine_id, mount_path, container_name = _resolve_target(cleanup, session)
        task_data = {
            "deleted_id": getattr(cleanup, "deleted_id", None),
            "machine_id": machine_id,
            "mount_path": mount_path,
            "container_name": container_name,
        }

    canonical = canonical_mount_path(task_data["mount_path"])
    task = _begin_cleanup(
        cleanup_id=int(cleanup_id),
        canonical_path=canonical,
        trigger=trigger,
        operator_user_id=operator_user_id,
        escalation=escalation,
        verify_mount_path=verify_mount_path,
        **task_data,
    )
    _spawn(task)
    return {
        "accepted": True,
        "already_cleaned": False,
        "mount_cleanup_id": int(cleanup_id),
        "deleted_id": task.deleted_id,
        "mount_cleanup_state": "cleaning",
    }


@contextmanager
def reserve_restore(machine_id: int, mount_path: str, deleted_id: int | None = None):
    canonical = canonical_mount_path(mount_path)
    key = (int(machine_id), canonical)
    with _LOCK:
        _prune_locked(time.monotonic())
        existing = _ACTIVE_BY_KEY.get(key)
        if existing is not None:
            raise NodeServiceError(
                f"mount path is busy with {existing.kind}",
                reason=_busy_reason(existing),
            )
        task = _Task(
            cleanup_id=0,
            deleted_id=int(deleted_id) if deleted_id is not None else None,
            machine_id=int(machine_id),
            mount_path=str(mount_path),
            canonical_path=canonical,
            container_name=None,
            trigger="restore",
            operator_user_id=None,
            escalation=None,
            verify_mount_path=False,
            kind="restore",
            state="restoring",
        )
        _ACTIVE_BY_KEY[key] = task
    try:
        yield task
    finally:
        with _LOCK:
            _ACTIVE_BY_KEY.pop(key, None)


def describe_cleanup(cleanup_id: int, machine_id: int | None = None, mount_path: str | None = None) -> dict:
    with _LOCK:
        _prune_locked(time.monotonic())
        task = _BY_CLEANUP_ID.get(int(cleanup_id)) if cleanup_id else None
        if task is None and machine_id is not None and mount_path:
            try:
                task = _ACTIVE_BY_KEY.get((int(machine_id), canonical_mount_path(mount_path)))
            except NodeServiceError:
                task = None
        if task is None or task.kind != "cleanup":
            return {"state": None, "error_reason": None}
        if task.state in ("accepted", "running"):
            return {"state": "cleaning", "error_reason": None}
        if task.state in ("failed", "unknown"):
            return {"state": task.state, "error_reason": task.error_reason}
        return {"state": None, "error_reason": None}


def wait_for_cleanup(cleanup_id: int, timeout: float = 2.0) -> str | None:
    """Test helper: wait for terminal state and return it."""

    deadline = time.monotonic() + max(float(timeout), 0.0)
    while time.monotonic() < deadline:
        with _LOCK:
            task = _BY_CLEANUP_ID.get(int(cleanup_id))
            if task is not None and task.terminal:
                return task.state
        time.sleep(0.01)
    with _LOCK:
        task = _BY_CLEANUP_ID.get(int(cleanup_id))
        return task.state if task is not None else None


def reset_registry() -> None:
    with _LOCK:
        _ACTIVE_BY_KEY.clear()
        _BY_CLEANUP_ID.clear()
