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


def build_container_restore_snapshot(container_id: int, cleanup_context: dict | None = None) -> dict:
    """Build a pre-removal snapshot with enough metadata to recreate a container."""

    with session_scope(commit=False) as session:
        container = containers_repo.get_by_id(container_id, session=session)
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
    operator_user_id: int | None = None,
    cleanup_context: dict | None = None,
    session,
) -> dict:
    container = containers_repo.get_by_id(container_id, session=session)
    if container is None:
        return {"snapshot": None, "mount_cleanup": None}

    snapshot = build_container_restore_snapshot(container_id, cleanup_context=cleanup_context)
    bind_mount = getattr(container, "bind_mount_path", None)
    removed_at = datetime.utcnow()
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
                escalation=False,
                removed_at=removed_at,
                session=session,
            )

    snapshot_row = deleted_container_restore_snapshot_repo.insert(
        snapshot,
        session=session,
        mount_cleanup_id=getattr(cleanup_row, "id", None),
        mount_path=bind_mount,
        removed_trigger=removed_trigger,
        operator_user_id=operator_user_id,
        removed_at=removed_at,
    )
    return {"snapshot": snapshot_row, "mount_cleanup": cleanup_row}


def serialize_deleted_container_record(row, cleanup) -> dict:
    cleaned_at = getattr(cleanup, "cleaned_at", None) if cleanup else None
    return {
        "deleted_id": row.id,
        "original_container_id": row.original_container_id,
        "container_name": row.container_name,
        "image": (row.snapshot or {}).get("image"),
        "machine_id": row.machine_id,
        "machine_name": row.machine_name,
        "machine_ip": row.machine_ip,
        "mount_path": row.mount_path,
        "mount_cleanup_id": row.mount_cleanup_id,
        "removed_at": _serialize_dt(row.removed_at),
        "removed_trigger": row.removed_trigger,
        "operator_user_id": row.operator_user_id,
        "cleaned_at": _serialize_dt(cleaned_at),
        "cleanup_escalation": bool(getattr(cleanup, "escalation", False)) if cleanup else False,
        "data_recoverable": bool(row.mount_path and cleaned_at is None),
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
        seen_cleanup_ids = set()
        for row in rows:
            cleanup = None
            if row.mount_cleanup_id:
                cleanup = container_mount_cleanup_repo.get_by_id(row.mount_cleanup_id, session=session)
                seen_cleanup_ids.add(row.mount_cleanup_id)
            records.append(serialize_deleted_container_record(row, cleanup))
        cleanup_rows = container_mount_cleanup_repo.list_records(limit=1000000, offset=0, session=session)
        for cleanup in cleanup_rows:
            if cleanup.id in seen_cleanup_ids:
                continue
            machine = machine_repo.get_by_id(cleanup.machine_id, session=session)
            records.append({
                "deleted_id": f"mount-{cleanup.id}",
                "original_container_id": cleanup.container_id,
                "container_name": cleanup.container_name,
                "image": None,
                "machine_id": cleanup.machine_id,
                "machine_name": getattr(machine, "machine_name", None),
                "machine_ip": getattr(machine, "machine_ip", None),
                "mount_path": cleanup.mount_path,
                "mount_cleanup_id": cleanup.id,
                "removed_at": _serialize_dt(cleanup.removed_at),
                "removed_trigger": "mount_cleanup",
                "operator_user_id": None,
                "cleaned_at": _serialize_dt(cleanup.cleaned_at),
                "cleanup_escalation": bool(cleanup.escalation),
                "data_recoverable": bool(cleanup.mount_path and cleanup.cleaned_at is None),
                "snapshot": {},
            })
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
