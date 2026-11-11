"""长期容器切换守卫、同目标 no-op、Q74 删除重置与恢复新建边界。

全部使用隔离 SQLite + mock Node，不连接真实 Docker/Node/生产库。
"""

from datetime import datetime

import pytest
from sqlalchemy import func, select

from ...api import deps
from ...constant import ContainerStatus, MachineStatus, OperationType, ROLE
from ...extensions import session_scope
from ...models.container_disk_freeze_state import ContainerDiskFreezeState
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...models.long_term_container import LongTermContainer
from ...models.operation_log import OperationLog
from ...repositories import (
    container_disk_freeze_state_repo,
    containers_repo,
    image_repo,
    long_term_container_repo,
)
from ...services import container_tasks
from ...services.container_module.exceptions import NodeServiceError
from ..factories import create_container, create_container_graph
from .conftest import NODE_REMOVE_SUCCESS


pytestmark = pytest.mark.usefixtures("ensure_auth_users")


def _auth(monkeypatch, *, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)


def _freeze_fields(db_session, container_id):
    row = container_disk_freeze_state_repo.get(
        container_id, session=db_session, include_invalid=True,
    )
    if row is None:
        return None
    return (row.first_frozen_at, row.grace_until, row.deferral_seconds)


def _freeze_row(db_session, container_id):
    return container_disk_freeze_state_repo.get(
        container_id, session=db_session, include_invalid=True,
    )


def _long_term_count(db_session, container_id):
    return int(db_session.scalar(
        select(func.count()).select_from(LongTermContainer).where(
            LongTermContainer.container_id == container_id,
        )
    ) or 0)


def _success_audits(db_session, container_id):
    return db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == OperationType.SET_LONG_TERM,
            OperationLog.target_id == container_id,
            OperationLog.success.is_(True),
        )
    ).all()


def _failure_audits(db_session, container_id):
    return db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == OperationType.SET_LONG_TERM,
            OperationLog.target_id == container_id,
            OperationLog.success.is_(False),
        )
    ).all()


def _add_long_term(db_session, container, user_id):
    long_term_container_repo.add(container.id, created_by_user_id=user_id, session=db_session)
    db_session.commit()


# ---------------------------------------------------------------------------
# 静态守卫：配额 / 磁盘 / 冻结取消 / 状态矩阵
# ---------------------------------------------------------------------------

def test_enable_rejected_when_root_quota_full(app, db_session):
    root, machine, container = create_container_graph()
    _r2, _m2, other = create_container_graph(root_user=root, machine=machine)
    _add_long_term(db_session, other, root.id)

    with pytest.raises(NodeServiceError) as excinfo:
        container_tasks.set_long_term_container(container.id, True, operator_user_id=root.id)

    assert excinfo.value.reason == "long_term_limit_reached"
    assert "(1/1)" in str(excinfo.value)
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is False
    assert _long_term_count(db_session, container.id) == 0


@pytest.mark.parametrize("total_bytes,blocked", [
    (512 * 1024**3, True),
    (513 * 1024**3, True),
    (511 * 1024**3, False),
    (None, False),
])
def test_enable_disk_hard_limit_is_static_and_unknown_is_not_zero(
    app, db_session, total_bytes, blocked,
):
    root, machine, container = create_container_graph()
    machine.max_disk_size_gb = 512
    container.disk_total_bytes = total_bytes
    db_session.commit()

    if blocked:
        with pytest.raises(NodeServiceError) as excinfo:
            container_tasks.set_long_term_container(container.id, True, operator_user_id=root.id)
        assert excinfo.value.reason == "disk_usage_over_limit"
        assert long_term_container_repo.is_long_term(container.id, session=db_session) is False
    else:
        result = container_tasks.set_long_term_container(container.id, True, operator_user_id=root.id)
        assert result["is_long_term"] is True
        assert long_term_container_repo.is_long_term(container.id, session=db_session) is True


def test_soft_threshold_and_unconfigured_limit_do_not_block_enable(app, db_session):
    root, machine, container = create_container_graph()
    machine.max_disk_size_gb = 512
    container.disk_total_bytes = int(0.85 * 512 * 1024**3)  # 高于软阈值 80%，低于硬限制
    db_session.commit()

    result = container_tasks.set_long_term_container(container.id, True, operator_user_id=root.id)
    assert result["is_long_term"] is True

    root2, machine2, container2 = create_container_graph()
    machine2.max_disk_size_gb = 0
    container2.disk_total_bytes = 999 * 1024**3
    db_session.commit()
    result2 = container_tasks.set_long_term_container(container2.id, True, operator_user_id=root2.id)
    assert result2["is_long_term"] is True


def test_cancel_rejected_while_paused_and_freeze_fields_unchanged(app, db_session):
    root, _machine, container = create_container_graph()
    _add_long_term(db_session, container, root.id)
    row = container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    row.first_frozen_at = datetime(2026, 10, 1, 12, 0, 0)
    row.grace_until = datetime(2026, 10, 5, 12, 0, 0)
    row.deferral_seconds = 321
    container.container_status = ContainerStatus.PAUSED
    db_session.commit()
    before = _freeze_fields(db_session, container.id)

    with pytest.raises(NodeServiceError) as excinfo:
        container_tasks.set_long_term_container(container.id, False, operator_user_id=root.id)

    assert excinfo.value.reason == "container_paused"
    db_session.expire_all()
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True
    assert _freeze_fields(db_session, container.id) == before


@pytest.mark.parametrize("status", [ContainerStatus.ONLINE, ContainerStatus.OFFLINE])
def test_cancel_allowed_after_resume_even_with_legacy_freeze_row(app, db_session, status):
    root, _machine, container = create_container_graph()
    _add_long_term(db_session, container, root.id)
    row = container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    row.first_frozen_at = datetime(2026, 10, 1, 12, 0, 0)
    row.grace_until = datetime(2026, 10, 5, 12, 0, 0)
    row.deferral_seconds = 99
    container.container_status = status
    db_session.commit()
    before = _freeze_fields(db_session, container.id)

    result = container_tasks.set_long_term_container(container.id, False, operator_user_id=root.id)

    assert result["is_long_term"] is False
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is False
    assert _freeze_fields(db_session, container.id) == before


def test_paused_container_can_still_enable_long_term(app, db_session):
    root, _machine, container = create_container_graph()
    container.container_status = ContainerStatus.PAUSED
    db_session.commit()

    result = container_tasks.set_long_term_container(container.id, True, operator_user_id=root.id)

    assert result["is_long_term"] is True


@pytest.mark.parametrize("target,status,expected_reason", [
    (True, ContainerStatus.FAILED, "container_failed"),
    (False, ContainerStatus.CREATING, "container_busy"),
])
def test_status_matrix_remains_authoritative(app, db_session, target, status, expected_reason):
    root, _machine, container = create_container_graph()
    if target is False:
        _add_long_term(db_session, container, root.id)
    container.container_status = status
    db_session.commit()

    with pytest.raises(NodeServiceError) as excinfo:
        container_tasks.set_long_term_container(container.id, target, operator_user_id=root.id)

    assert excinfo.value.reason == expected_reason


def test_host_and_unknown_conditions_still_rejected(app, db_session):
    root, machine, container = create_container_graph()
    machine.machine_status = MachineStatus.OFFLINE
    db_session.commit()

    with pytest.raises(NodeServiceError) as offline:
        container_tasks.set_long_term_container(container.id, True, operator_user_id=root.id)
    assert offline.value.reason == "container_host_offline"

    machine.machine_status = MachineStatus.ONLINE
    machine.is_maintenance = True
    db_session.commit()
    with pytest.raises(NodeServiceError) as maintenance:
        container_tasks.set_long_term_container(container.id, True, operator_user_id=root.id)
    assert maintenance.value.reason == "container_host_maintenance"

    machine.is_maintenance = False
    container.status_unknown_since = datetime.utcnow()
    container.status_source = "cold_start_verify"
    db_session.commit()
    with pytest.raises(NodeServiceError) as unknown:
        container_tasks.set_long_term_container(container.id, False, operator_user_id=root.id)
    assert unknown.value.reason == "container_status_unknown"


# ---------------------------------------------------------------------------
# 同目标 no-op 与单会话读取
# ---------------------------------------------------------------------------

def test_same_target_repeated_enable_has_no_side_effects(app, db_session):
    root, _machine, container = create_container_graph()
    _add_long_term(db_session, container, root.id)
    row = container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    row.first_frozen_at = datetime(2026, 10, 1, 12, 0, 0)
    row.grace_until = datetime(2026, 10, 4, 12, 0, 0)
    row.deferral_seconds = 17
    db_session.commit()
    before = _freeze_fields(db_session, container.id)

    result = container_tasks.set_long_term_container(container.id, True, operator_user_id=root.id)

    db_session.expire_all()
    assert result["is_long_term"] is True
    assert _long_term_count(db_session, container.id) == 1
    assert _success_audits(db_session, container.id) == []
    assert _freeze_fields(db_session, container.id) == before


def test_same_target_repeated_cancel_has_no_side_effects(app, db_session):
    root, _machine, container = create_container_graph()
    freeze = container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    freeze.deferral_seconds = 55
    db_session.commit()
    before = _freeze_fields(db_session, container.id)

    result = container_tasks.set_long_term_container(container.id, False, operator_user_id=root.id)

    db_session.expire_all()
    assert result["is_long_term"] is False
    assert _long_term_count(db_session, container.id) == 0
    assert _success_audits(db_session, container.id) == []
    assert _freeze_fields(db_session, container.id) == before


def test_repeated_switch_requests_keep_one_marker_and_one_success_audit(app, db_session):
    root, _machine, container = create_container_graph()

    first = container_tasks.set_long_term_container(container.id, True, operator_user_id=root.id)
    second = container_tasks.set_long_term_container(container.id, True, operator_user_id=root.id)

    assert first["is_long_term"] is True
    assert second["is_long_term"] is True
    assert _long_term_count(db_session, container.id) == 1
    assert len(_success_audits(db_session, container.id)) == 1
    assert [column.name for column in LongTermContainer.__table__.primary_key.columns] == ["container_id"]
    assert long_term_container_repo.add(container.id, session=db_session) is True
    db_session.commit()
    assert _long_term_count(db_session, container.id) == 1


def test_single_session_reread_rejudges_changed_status(app, db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    _add_long_term(db_session, container, root.id)
    paused = create_container(machine=container.machine, status=ContainerStatus.PAUSED)

    # 模拟写入前在同一事务重读到的最新事实：请求开始时的 online 不再被沿用。
    monkeypatch.setattr(
        container_tasks,
        "_read_long_term_target",
        lambda session, container_id: (paused, [{"user_id": root.id, "role": ROLE.ROOT}], True, container.machine),
    )
    with pytest.raises(NodeServiceError) as excinfo:
        container_tasks.set_long_term_container(paused.id, False, operator_user_id=root.id)

    assert excinfo.value.reason == "container_paused"


# ---------------------------------------------------------------------------
# API 原因 / 状态码
# ---------------------------------------------------------------------------

def test_api_maps_disk_hard_limit_to_409_and_logs_failure(app, client, monkeypatch, db_session):
    _auth(monkeypatch)
    root, machine, container = create_container_graph()
    machine.max_disk_size_gb = 512
    container.disk_total_bytes = 600 * 1024**3
    db_session.commit()

    resp = client.post("/api/containers/set_long_term_container", json={
        "container_id": container.id, "is_long_term": True,
    })

    assert resp.status_code == 409
    assert resp.json()["error_reason"] == "disk_usage_over_limit"
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is False
    failures = _failure_audits(db_session, container.id)
    assert [log.error_reason for log in failures] == ["disk_usage_over_limit"]
    assert _success_audits(db_session, container.id) == []


def test_api_maps_quota_to_409(app, client, monkeypatch, db_session):
    _auth(monkeypatch)
    root, machine, container = create_container_graph()
    _r2, _m2, other = create_container_graph(root_user=root, machine=machine)
    _add_long_term(db_session, other, root.id)

    resp = client.post("/api/containers/set_long_term_container", json={
        "container_id": container.id, "is_long_term": True,
    })

    assert resp.status_code == 409
    assert resp.json()["error_reason"] == "long_term_limit_reached"
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is False


def test_api_maps_frozen_cancel_to_409(app, client, monkeypatch, db_session):
    _auth(monkeypatch)
    root, _machine, container = create_container_graph()
    _add_long_term(db_session, container, root.id)
    container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    container.container_status = ContainerStatus.PAUSED
    db_session.commit()

    resp = client.post("/api/containers/set_long_term_container", json={
        "container_id": container.id, "is_long_term": False,
    })

    assert resp.status_code == 409
    assert resp.json()["error_reason"] == "container_paused"
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True


def test_api_keeps_host_unavailable_503(app, client, monkeypatch, db_session):
    _auth(monkeypatch)
    root, machine, container = create_container_graph()
    machine.machine_status = MachineStatus.OFFLINE
    db_session.commit()

    resp = client.post("/api/containers/set_long_term_container", json={
        "container_id": container.id, "is_long_term": True,
    })

    assert resp.status_code == 503
    assert resp.json()["error_reason"] == "container_host_offline"


def test_api_noop_returns_200_without_new_audit(app, client, monkeypatch, db_session):
    _auth(monkeypatch)
    root, _machine, container = create_container_graph()
    _add_long_term(db_session, container, root.id)

    resp = client.post("/api/containers/set_long_term_container", json={
        "container_id": container.id, "is_long_term": True,
    })

    assert resp.status_code == 200
    assert resp.json()["is_long_term"] is True
    assert _long_term_count(db_session, container.id) == 1
    assert _success_audits(db_session, container.id) == []


# ---------------------------------------------------------------------------
# Q74：删除重置冻结 / 恢复等同新建
# ---------------------------------------------------------------------------

def test_generic_soft_delete_clears_only_target_freeze_row(app, db_session):
    _root, machine, container = create_container_graph()
    _r2, _m2, other = create_container_graph(root_user=_root, machine=machine)
    row = container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    row.first_frozen_at = datetime(2026, 10, 1, 12, 0, 0)
    row.grace_until = datetime(2026, 10, 5, 12, 0, 0)
    row.deferral_seconds = 77
    other_row = container_disk_freeze_state_repo.upsert_first_frozen(other.id, session=db_session)
    other_before = (other_row.first_frozen_at, other_row.grace_until, other_row.deferral_seconds)
    db_session.commit()

    assert containers_repo.delete_container(
        container.id, deleted_trigger="api", session=db_session,
    ) is True
    db_session.commit()

    assert containers_repo.get_by_id(container.id, session=db_session) is None
    retained = containers_repo.get_by_id(container.id, session=db_session, include_invalid=True)
    assert retained is not None and retained.is_valid is False
    assert _freeze_row(db_session, container.id) is None
    assert _freeze_fields(db_session, other.id) == other_before


def test_generic_soft_delete_without_freeze_row_is_normal(app, db_session):
    _root, _machine, container = create_container_graph()

    assert containers_repo.delete_container(container.id, session=db_session) is True
    db_session.commit()

    assert containers_repo.get_by_id(container.id, session=db_session) is None
    assert _freeze_row(db_session, container.id) is None


def test_delete_rollback_keeps_container_and_freeze_row(app, db_session):
    _root, _machine, container = create_container_graph()
    row = container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    row.deferral_seconds = 12
    db_session.commit()
    before = _freeze_fields(db_session, container.id)

    with pytest.raises(RuntimeError):
        with session_scope() as session:
            containers_repo.delete_container(
                container.id, deleted_trigger="api", session=session,
            )
            raise RuntimeError("boom")

    db_session.expire_all()
    container_row = containers_repo.get_by_id(container.id, session=db_session)
    assert container_row is not None and container_row.is_valid is True
    assert _freeze_fields(db_session, container.id) == before


def test_repeated_soft_delete_is_idempotent(app, db_session):
    _root, _machine, container = create_container_graph()
    container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    db_session.commit()

    assert containers_repo.delete_container(container.id, session=db_session) is True
    db_session.commit()
    deleted_at = containers_repo.get_by_id(
        container.id, session=db_session, include_invalid=True,
    ).deleted_at
    assert containers_repo.delete_container(container.id, session=db_session) is True
    db_session.commit()

    retained = containers_repo.get_by_id(container.id, session=db_session, include_invalid=True)
    assert retained.deleted_at == deleted_at
    assert _freeze_row(db_session, container.id) is None


@pytest.mark.parametrize("operator", [1, None])
def test_api_and_cleanup_removal_clear_freeze_row(
    app, db_session, mock_node_send, operator,
):
    _root, _machine, container = create_container_graph()
    container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    db_session.commit()
    mock_node_send(NODE_REMOVE_SUCCESS)

    assert container_tasks.remove_container(container.id, operator_user_id=operator) is True

    db_session.expire_all()
    retained = containers_repo.get_by_id(container.id, session=db_session, include_invalid=True)
    assert retained.is_valid is False
    assert retained.deleted_trigger == ("api" if operator else "cleanup")
    assert _freeze_row(db_session, container.id) is None


def test_delete_then_restore_long_term_does_not_inherit_freeze_or_grace(
    app, db_session, mock_node_send,
):
    root, machine, container = create_container_graph()
    container.image_id = 1
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    container.bind_mount_path = f"/home/{root.username}/containers/{container.name}_data"
    _add_long_term(db_session, container, root.id)
    row = container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    row.first_frozen_at = datetime(2026, 10, 1, 12, 0, 0)
    container_disk_freeze_state_repo.set_grace(container.id, 3, session=db_session)
    db_session.commit()
    assert _freeze_row(db_session, container.id) is not None

    mock_node_send(NODE_REMOVE_SUCCESS)
    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    db_session.expire_all()
    assert _freeze_row(db_session, container.id) is None
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()

    restored = container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    db_session.expire_all()
    assert restored["container_id"] == container.id
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True
    assert _long_term_count(db_session, container.id) == 1
    assert _freeze_row(db_session, container.id) is None
    assert db_session.scalar(
        select(func.count()).select_from(ContainerDiskFreezeState)
    ) == 0
