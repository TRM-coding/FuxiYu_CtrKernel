"""deleted_containers.resolve_mount_cleanup_request 的单元测试。

手动 mount 清理的入参解析：调用方可能只给 deleted_id、只给 mount_cleanup_id，
或给出历史遗留的"只有 cleanup 行、没有 deleted 快照"的 id。
这段是三路调用的公共入口，判错会导致清错目录或直接 404，所以逐分支锁一遍。
"""

import pytest

from ...repositories import container_mount_cleanup_repo, deleted_container_restore_snapshot_repo
from ...services.container_module.deleted_containers import resolve_mount_cleanup_request
from ...services.container_module.exceptions import NodeServiceError
from ..factories import create_container, create_machine


def _cleanup_row(db_session, *, container_id=999, mount_path="/home/u/containers/c_data"):
    machine = create_machine()
    row = container_mount_cleanup_repo.insert(
        container_id=container_id,
        container_name="c",
        machine_id=machine.id,
        mount_path=mount_path,
        session=db_session,
    )
    db_session.commit()
    return row


def _deleted_row(db_session, *, container_id=None, mount_cleanup_id=None):
    machine = create_machine()
    container = create_container(machine=machine, name=f"gone_{container_id or 1}")
    row = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": container.id if container_id is None else container_id,
            "container_name": container.name,
            "machine_id": machine.id,
            "bind_mount_path": "/home/u/containers/gone_data",
        },
        mount_cleanup_id=mount_cleanup_id,
        session=db_session,
    )
    db_session.commit()
    return row


def test_missing_both_ids_is_invalid_payload(db_session):
    with pytest.raises(NodeServiceError) as excinfo:
        resolve_mount_cleanup_request(None, None)

    assert excinfo.value.reason == "invalid_payload"


def test_unknown_mount_cleanup_id_is_not_found(db_session):
    with pytest.raises(NodeServiceError) as excinfo:
        resolve_mount_cleanup_request(None, 999999)

    assert excinfo.value.reason == "not_found"


def test_deleted_id_resolves_to_its_cleanup_record(db_session):
    cleanup = _cleanup_row(db_session)
    deleted = _deleted_row(db_session, mount_cleanup_id=cleanup.id)

    resolved_deleted_id, resolved_cleanup = resolve_mount_cleanup_request(deleted.id, None)

    assert resolved_deleted_id == deleted.id
    assert resolved_cleanup is not None
    assert resolved_cleanup.id == cleanup.id


def test_legacy_cleanup_only_id_is_redirected_from_deleted_id(db_session):
    """历史遗留：调用方把 cleanup 的 id 当 deleted_id 传 → 自动改判为 mount_cleanup_id。"""
    cleanup = _cleanup_row(db_session, container_id=999)
    db_session.commit()

    resolved_deleted_id, resolved_cleanup = resolve_mount_cleanup_request(cleanup.id, None)

    # 返回的 deleted_id 指向的是 deleted 快照（不是 cleanup 行），收养时按 cleanup 的路径信息补建
    adopted = deleted_container_restore_snapshot_repo.get_by_id(resolved_deleted_id, session=db_session)
    assert adopted is not None
    assert adopted.removed_trigger == "legacy_mount_cleanup"
    assert adopted.original_container_id == 999
    assert adopted.container_name == "c"
    assert adopted.mount_cleanup_id == cleanup.id
    # 双向回填：cleanup 行也指回新快照
    assert resolved_cleanup is not None
    assert resolved_cleanup.id == cleanup.id
    assert resolved_cleanup.deleted_id == adopted.id


def test_mount_cleanup_id_resolves_via_linked_deleted_record(db_session):
    cleanup = _cleanup_row(db_session)
    deleted = _deleted_row(db_session, mount_cleanup_id=cleanup.id)

    resolved_deleted_id, resolved_cleanup = resolve_mount_cleanup_request(None, cleanup.id)

    assert resolved_deleted_id == deleted.id
    assert resolved_cleanup.id == cleanup.id


def test_deleted_id_wins_when_both_ids_given(db_session):
    """两个 id 都给时以 deleted_id 为准（mount_cleanup_id 只作兼容入参，不参与判路）。"""
    cleanup = _cleanup_row(db_session)
    deleted = _deleted_row(db_session, mount_cleanup_id=cleanup.id)

    resolved_deleted_id, resolved_cleanup = resolve_mount_cleanup_request(deleted.id, cleanup.id)

    assert resolved_deleted_id == deleted.id
    assert resolved_cleanup.id == cleanup.id
