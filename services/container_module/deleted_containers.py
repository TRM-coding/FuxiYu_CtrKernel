import math
from datetime import datetime

from ...constant import ROLE
from ...extensions import session_scope
from ...repositories import (
    container_mount_cleanup_repo,
    containers_repo,
    deleted_container_restore_snapshot_repo,
    long_term_container_repo,
    machine_repo,
    user_repo,
    usercontainer_repo,
)
from ...repositories.containers_repo import derive_port_mappings
from .exceptions import NodeServiceError


def resolve_mount_cleanup_request(
    deleted_id: int | None, mount_cleanup_id: int | None,
) -> tuple[int, object | None]:
    """Resolve manual cleanup input, including legacy cleanup-only records."""
    if deleted_id is not None and mount_cleanup_id is None:
        with session_scope(commit=False) as session:
            deleted_exists = deleted_container_restore_snapshot_repo.get_by_id(
                int(deleted_id),
                session=session,
            )
            cleanup_exists = container_mount_cleanup_repo.get_by_id(
                int(deleted_id),
                session=session,
            )
        if deleted_exists is None and cleanup_exists is not None:
            mount_cleanup_id = int(deleted_id)
            deleted_id = None

    if deleted_id is None and mount_cleanup_id is not None:
        with session_scope(commit=False) as session:
            cleanup = container_mount_cleanup_repo.get_by_id(int(mount_cleanup_id), session=session)
            if cleanup is None:
                raise NodeServiceError("mount cleanup record not found", reason="not_found")
            deleted_id = getattr(cleanup, "deleted_id", None)
            if deleted_id is None:
                deleted = deleted_container_restore_snapshot_repo.get_by_mount_cleanup_id(
                    int(mount_cleanup_id),
                    session=session,
                )
                deleted_id = deleted.id if deleted else None
        if deleted_id is None:
            with session_scope() as session:
                cleanup = container_mount_cleanup_repo.get_by_id(
                    int(mount_cleanup_id),
                    session=session,
                )
                if cleanup is None:
                    raise NodeServiceError("mount cleanup record not found", reason="not_found")
                deleted = ensure_deleted_record_for_cleanup(cleanup, session=session)
                deleted_id = deleted.id

    if deleted_id is None:
        raise NodeServiceError("deleted_id is required", reason="invalid_payload")
    with session_scope() as session:
        _deleted, cleanup = ensure_mount_cleanup_record(int(deleted_id), session=session)
    return int(deleted_id), cleanup


def build_container_restore_snapshot(
    container_id: int,
    cleanup_context: dict | None = None,
    *,
    include_invalid: bool = False,
) -> dict:
    """Build a pre-removal snapshot with enough metadata to recreate a container."""

    with session_scope(commit=False) as session:
        container = containers_repo.get_by_id(
            container_id,
            session=session,
            include_invalid=include_invalid,
        )
    if not container:
        return {
            "container_id": container_id,
            "snapshot_status": "container_not_found",
            "cleanup_context": cleanup_context or {},
        }

    try:
        with session_scope(commit=False) as session:
            machine = machine_repo.get_by_id(container.machine_id, session=session)
    except Exception:
        machine = None

    with session_scope(commit=False) as session:
        bindings = usercontainer_repo.get_container_bindings(container_id, session=session) or []
    accounts = []
    for binding in bindings:
        user_id = binding.get("user_id")
        role = binding.get("role")
        role_value = role.value if isinstance(role, ROLE) else str(role or "")
        with session_scope(commit=False) as session:
            system_username = user_repo.get_name_by_id(user_id, session=session) if user_id is not None else None
        accounts.append({
            "user_id": user_id,
            "system_username": system_username,
            "container_username": binding.get("username"),
            "role": role_value,
            "public_key": binding.get("public_key"),
            "granted_at": str(binding.get("granted_at")) if binding.get("granted_at") is not None else None,
        })

    status = container.container_status
    status_value = status.value if hasattr(status, "value") else str(status or "")
    with session_scope(commit=False) as session:
        is_long_term = long_term_container_repo.is_long_term(container.id, session=session)

    return {
        "container_id": container.id,
        "container_name": container.name,
        "image": container.image,
        "machine_id": container.machine_id,
        "machine_ip": getattr(machine, "machine_ip", None),
        "machine_name": getattr(machine, "machine_name", None),
        "container_status": status_value,
        "port": container.port,
        "port_mappings": derive_port_mappings(container.port, container.port_mappings),
        "memory_gb": container.memory_gb,
        "shared_gb": container.shared_gb,
        "gpu_number": container.gpu_number,
        "gpu_chosen_list": container.gpu_chosen_list,
        "cpu_number": container.cpu_number,
        "bind_mount_path": getattr(container, "bind_mount_path", None),
        "is_long_term": is_long_term,
        "accounts": accounts,
        "cleanup_context": cleanup_context or {},
    }


def record_deleted_container_artifacts(
    container_id: int,
    *,
    removed_trigger: str = "api",
    cleanup_context: dict | None = None,
    session,
) -> dict:
    container = containers_repo.get_by_id(container_id, session=session)
    if container is None:
        return {"snapshot": None, "mount_cleanup": None}

    snapshot = build_container_restore_snapshot(container_id, cleanup_context=cleanup_context)
    bind_mount = getattr(container, "bind_mount_path", None)
    removed_at = datetime.utcnow()
    snapshot_row = deleted_container_restore_snapshot_repo.insert(
        snapshot,
        session=session,
        removed_trigger=removed_trigger,
        removed_at=removed_at,
        mount_cleaned=not bool(bind_mount),
    )
    cleanup_row = None
    if bind_mount:
        cleanup_row = container_mount_cleanup_repo.get_latest_for_container(
            container.id,
            bind_mount,
            session=session,
        )
        if cleanup_row is None:
            cleanup_row = container_mount_cleanup_repo.insert(
                container_id=container.id,
                container_name=container.name,
                machine_id=container.machine_id,
                mount_path=bind_mount,
                deleted_id=snapshot_row.id,
                escalation=False,
                removed_at=removed_at,
                session=session,
            )
        else:
            cleanup_row.deleted_id = snapshot_row.id
        snapshot_row.mount_cleanup_id = cleanup_row.id
        session.flush()
    return {"snapshot": snapshot_row, "mount_cleanup": cleanup_row}


def ensure_deleted_record_for_cleanup(cleanup, *, session):
    """Adopt a legacy cleanup row so deleted owns the cleanup lifecycle state."""

    deleted = (
        deleted_container_restore_snapshot_repo.get_by_id(cleanup.deleted_id, session=session)
        if getattr(cleanup, "deleted_id", None) is not None
        else deleted_container_restore_snapshot_repo.get_by_mount_cleanup_id(
            cleanup.id,
            session=session,
        )
    )
    if deleted is not None:
        if deleted.mount_cleanup_id != cleanup.id:
            deleted.mount_cleanup_id = cleanup.id
        if cleanup.deleted_id != deleted.id:
            cleanup.deleted_id = deleted.id
        session.flush()
        return deleted

    container = containers_repo.get_by_id(
        cleanup.container_id,
        session=session,
        include_invalid=True,
    )
    if container is not None:
        snapshot = build_container_restore_snapshot(
            container.id,
            cleanup_context={"legacy_cleanup_id": cleanup.id},
            include_invalid=True,
        )
        container_name = container.name
        machine_id = container.machine_id
    else:
        snapshot = {
            "container_id": cleanup.container_id,
            "container_name": cleanup.container_name,
            "machine_id": cleanup.machine_id,
            "bind_mount_path": cleanup.mount_path,
            "accounts": [],
        }
        container_name = cleanup.container_name
        machine_id = cleanup.machine_id

    deleted = deleted_container_restore_snapshot_repo.insert(
        snapshot,
        session=session,
        removed_trigger="legacy_mount_cleanup",
        removed_at=cleanup.removed_at,
        mount_cleaned=cleanup.cleaned_at is not None,
    )
    deleted.container_name = container_name
    deleted.machine_id = machine_id
    deleted.mount_cleanup_id = cleanup.id
    cleanup.deleted_id = deleted.id
    session.flush()
    return deleted


def _get_deleted_container_context(row, cleanup, *, session) -> dict:
    snapshot = dict(row.snapshot or {})
    container_id = int(row.original_container_id or snapshot.get("container_id") or 0)
    container = (
        containers_repo.get_by_id(container_id, session=session, include_invalid=True)
        if container_id
        else None
    )
    machine_id = getattr(container, "machine_id", None) or row.machine_id or snapshot.get("machine_id")
    machine = machine_repo.get_by_id(machine_id, session=session) if machine_id else None
    mount_path = (
        getattr(container, "bind_mount_path", None)
        or (getattr(cleanup, "mount_path", None) if cleanup else None)
        or snapshot.get("bind_mount_path")
    )
    return {
        "container": container,
        "machine": machine,
        "container_id": container_id,
        "container_name": (
            getattr(container, "name", None)
            or row.container_name
            or snapshot.get("container_name")
        ),
        "machine_id": machine_id,
        "machine_name": getattr(machine, "machine_name", None) or snapshot.get("machine_name"),
        "machine_ip": getattr(machine, "machine_ip", None) or snapshot.get("machine_ip"),
        "mount_path": mount_path,
    }


def ensure_mount_cleanup_record(deleted_id: int, *, session) -> tuple[object, object | None]:
    """Resolve a deleted row and its cleanup execution record from Container-owned path data."""

    row = deleted_container_restore_snapshot_repo.get_by_id(deleted_id, session=session)
    if row is None:
        raise ValueError("deleted container record not found")
    cleanup = (
        container_mount_cleanup_repo.get_by_id(row.mount_cleanup_id, session=session)
        if row.mount_cleanup_id
        else container_mount_cleanup_repo.get_by_deleted_id(row.id, session=session)
    )
    context = _get_deleted_container_context(row, cleanup, session=session)
    mount_path = context["mount_path"]
    if not mount_path:
        row.mount_cleaned = True
        session.flush()
        return row, None

    if cleanup is None:
        cleanup = container_mount_cleanup_repo.get_latest_for_container(
            context["container_id"],
            mount_path,
            session=session,
        )
    if cleanup is None:
        if not context["container_id"] or not context["machine_id"] or not context["container_name"]:
            raise ValueError("deleted container mount metadata is incomplete")
        cleanup = container_mount_cleanup_repo.insert(
            container_id=context["container_id"],
            container_name=context["container_name"],
            machine_id=context["machine_id"],
            mount_path=mount_path,
            deleted_id=row.id,
            escalation=False,
            removed_at=row.removed_at,
            session=session,
        )
    else:
        cleanup.deleted_id = row.id
        if not row.mount_cleanup_id:
            row.mount_cleanup_id = cleanup.id
        if not cleanup.cleaned_at and cleanup.mount_path != mount_path:
            cleanup.mount_path = mount_path
    session.flush()
    return row, cleanup


def serialize_deleted_container_record(row, cleanup, *, context: dict | None = None) -> dict:
    context = context or {}
    cleaned_at = getattr(cleanup, "cleaned_at", None) if cleanup else None
    mount_cleaned = bool(getattr(row, "mount_cleaned", False))
    return {
        "deleted_id": row.id,
        "original_container_id": row.original_container_id,
        "container_name": context.get("container_name") or row.container_name,
        "image": (row.snapshot or {}).get("image"),
        "machine_id": context.get("machine_id") or row.machine_id,
        "machine_name": context.get("machine_name"),
        "machine_ip": context.get("machine_ip"),
        "mount_path": context.get("mount_path"),
        "mount_cleanup_id": row.mount_cleanup_id,
        "removed_at": _serialize_dt(row.removed_at),
        "removed_trigger": row.removed_trigger,
        "cleaned_at": _serialize_dt(cleaned_at),
        "mount_cleaned": mount_cleaned,
        "cleanup_escalation": bool(getattr(cleanup, "escalation", False)) if cleanup else False,
        "data_recoverable": bool(context.get("mount_path") and not mount_cleaned),
        "snapshot": row.snapshot or {},
    }


def build_deleted_container_page(page_number: int = 1, page_size: int = 20) -> dict:
    page_number = max(int(page_number or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)
    offset = (page_number - 1) * page_size
    with session_scope(commit=False) as session:
        rows = deleted_container_restore_snapshot_repo.list_records(
            session=session,
            limit=1000000,
            offset=0,
        )
        records = []
        for row in rows:
            cleanup = None
            if row.mount_cleanup_id:
                cleanup = container_mount_cleanup_repo.get_by_id(row.mount_cleanup_id, session=session)
            context = _get_deleted_container_context(row, cleanup, session=session)
            records.append(serialize_deleted_container_record(row, cleanup, context=context))
        records.sort(key=lambda item: item.get("removed_at") or "", reverse=True)
        total = len(records)
        records = records[offset:offset + page_size]
    return {
        "records": records,
        "total_number": total,
        "total_page": max(math.ceil(total / page_size), 1) if total else 0,
    }


def restore_accounts_from_snapshot(snapshot: dict) -> tuple[dict, list[dict]]:
    accounts = list(snapshot.get("accounts") or [])
    root_accounts = [item for item in accounts if str(item.get("role") or "").upper() == ROLE.ROOT.value]
    root_account = root_accounts[0] if root_accounts else (accounts[0] if accounts else None)
    if not root_account:
        raise ValueError("restore snapshot has no owner account")
    collaborators = [item for item in accounts if item is not root_account]
    return root_account, collaborators


def restore_role_api_value(value) -> str:
    if isinstance(value, ROLE):
        return value.value.lower()
    raw = str(value or ROLE.COLLABORATOR.value)
    if raw.upper() == ROLE.ADMIN.value:
        return "admin"
    return "collaborator"


def delete_restore_artifacts(snapshot_id: int, mount_cleanup_id: int | None, *, session) -> None:
    deleted_container_restore_snapshot_repo.delete(snapshot_id, session=session)
    if mount_cleanup_id:
        container_mount_cleanup_repo.delete(mount_cleanup_id, session=session)


def _serialize_dt(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
