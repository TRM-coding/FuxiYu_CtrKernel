"""Anvil freeze/membership 映射补测。

隔离 SQLite + 外部 Node 替身；不连接真实 Node、邮件或生产库。
本文件只覆盖已审 test-plan 中 19 个 unique planned test。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, update

from ...api import deps
from ...constant import ContainerStatus, OperationType, ROLE
from ...extensions import session_scope
from ...models.container_disk_freeze_state import ContainerDiskFreezeState
from ...models.container_ssh_login import ContainerSSHLogin
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...models.long_term_container import LongTermContainer
from ...models.operation_log import OperationLog
from ...models.usercontainer import UserContainer
from ...repositories import (
    container_disk_freeze_state_repo,
    containers_repo,
    image_repo,
    long_term_container_repo,
    usercontainer_repo,
)
from ...schedulers import container_cleanup_task, container_disk_check_task
from ...services import container_tasks, user_tasks
from ...services.container_module import collaborators as collaborator_utils
from ...services.container_module.exceptions import NodeServiceError
from ..factories import bind_user_container, create_container_graph, create_user
from .conftest import NODE_REMOVE_SUCCESS


_REAL_GET_MACHINE_ID_BY_CONTAINER_ID = containers_repo.get_machine_id_by_container_id


# ---------------------------------------------------------------------------
# 本地 helper：不新增 conftest / 共享 fixture
# ---------------------------------------------------------------------------


def _auth(monkeypatch, user_id, *, entity_ok=True, resource_fn=None, stub_machine=True):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_entity",
        lambda uid, code: entity_ok,
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_resource",
        resource_fn or (lambda uid, rtype, rid: True),
    )
    if stub_machine:
        monkeypatch.setattr(
            "FuxiYu_CtrKernel.repositories.containers_repo.get_machine_id_by_container_id",
            lambda cid, session: 1,
        )
    else:
        monkeypatch.setattr(
            "FuxiYu_CtrKernel.repositories.containers_repo.get_machine_id_by_container_id",
            _REAL_GET_MACHINE_ID_BY_CONTAINER_ID,
        )


def _error_reason(resp):
    body = resp.json()
    return body.get("error_reason") or body.get("detail", {}).get("error_reason")


def _install_node(monkeypatch, responses=None):
    calls = []
    sequence = list(responses or [{"success": 1}])

    def _send(url, payload, timeout=5.0):
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        item = sequence[min(len(calls) - 1, len(sequence) - 1)]
        if isinstance(item, Exception):
            raise item
        return dict(item)

    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_module.node_comms.send", _send)
    return calls


def _run_now(_name, target, *args):
    target(*args)
    return SimpleNamespace(join=lambda: None)


def _capture_background(monkeypatch):
    captured = {}

    def _capture(_name, target, *args):
        captured["target"] = target
        captured["args"] = args
        return SimpleNamespace(join=lambda: None)

    monkeypatch.setattr(collaborator_utils, "spawn_background", _capture)
    return captured


def _freeze_fields(db_session, container_id):
    row = container_disk_freeze_state_repo.get(
        container_id, session=db_session, include_invalid=True,
    )
    if row is None:
        return None
    return (row.first_frozen_at, row.grace_until, row.deferral_seconds)


def _seed_freeze(db_session, container_id, *, deferral=321):
    row = container_disk_freeze_state_repo.upsert_first_frozen(container_id, session=db_session)
    row.first_frozen_at = datetime(2026, 10, 1, 12, 0, 0)
    row.grace_until = datetime(2026, 10, 5, 12, 0, 0)
    row.deferral_seconds = deferral
    db_session.commit()
    return (row.first_frozen_at, row.grace_until, row.deferral_seconds)


def _long_term_count(db_session, container_id):
    return int(db_session.scalar(
        select(func.count()).select_from(LongTermContainer).where(
            LongTermContainer.container_id == container_id,
        )
    ) or 0)


def _success_audits(db_session, container_id):
    db_session.expire_all()
    return list(db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == OperationType.SET_LONG_TERM,
            OperationLog.target_id == container_id,
            OperationLog.success.is_(True),
        )
    ).all())


def _failure_audits(db_session, container_id):
    db_session.expire_all()
    return list(db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == OperationType.SET_LONG_TERM,
            OperationLog.target_id == container_id,
            OperationLog.success.is_(False),
        )
    ).all())


def _role_value(binding):
    return getattr(binding["role"], "value", binding["role"])


def _binding(db_session, user_id, container_id):
    return usercontainer_repo.get_binding(user_id, container_id, session=db_session)


def _root_ids(db_session, container_id):
    db_session.expire_all()
    rows = db_session.scalars(
        select(UserContainer).where(UserContainer.container_id == container_id)
    ).all()
    return sorted(
        row.user_id for row in rows
        if getattr(row.role, "value", row.role) == ROLE.ROOT.value
    )


def _role_logs(db_session, *, success=None, container_id=None):
    db_session.expire_all()
    stmt = select(OperationLog).where(
        OperationLog.operation == OperationType.UPDATE_COLLABORATOR_ROLE,
    )
    if success is not None:
        stmt = stmt.where(OperationLog.success.is_(success))
    if container_id is not None:
        stmt = stmt.where(OperationLog.target_id == container_id)
    return list(db_session.scalars(stmt).all())


def _assert_no_password_in_logs(db_session, passwords):
    db_session.expire_all()
    for log in db_session.scalars(select(OperationLog)).all():
        text = f"{log.detail}|{log.error_reason}"
        for password in passwords:
            assert password not in text


def _enable_disk_settings(monkeypatch):
    settings = {
        "get_container_disk_check_enabled": True,
        "get_container_disk_response_enabled": True,
        "get_container_disk_soft_limit_percent": 80,
        "get_container_disk_hard_limit_percent": 100,
        "get_container_disk_freeze_reset_percent": 95,
        "get_container_disk_freeze_escalation_days": 7,
        "get_container_disk_freeze_grace_days": 3,
    }
    for name, value in settings.items():
        monkeypatch.setattr(
            container_disk_check_task.settings_tasks, name, lambda value=value: value,
        )
    monkeypatch.setattr(container_disk_check_task, "_DISK_CHECK_CACHE", {})


# ---------------------------------------------------------------------------
# long-term 能力
# ---------------------------------------------------------------------------


def test_anvil_lt01_long_term_readback_contract(app, db_session):
    root, _machine, with_owner = create_container_graph()
    _other_root, _other_machine, without_owner = create_container_graph()
    before = datetime.utcnow()

    long_term_container_repo.add(
        with_owner.id, created_by_user_id=root.id, session=db_session,
    )
    long_term_container_repo.add(
        without_owner.id, created_by_user_id=None, session=db_session,
    )
    db_session.commit()
    after = datetime.utcnow()

    with session_scope(commit=False) as session:
        owned = session.get(LongTermContainer, with_owner.id)
        unowned = session.get(LongTermContainer, without_owner.id)

        assert owned is not None and unowned is not None
        assert isinstance(owned.container_id, int)
        assert owned.container_id == with_owner.id
        assert isinstance(owned.created_by_user_id, int)
        assert owned.created_by_user_id == root.id
        assert unowned.created_by_user_id is None
        assert isinstance(owned.created_at, datetime)
        assert before <= owned.created_at <= after
        assert before <= unowned.created_at <= after
        assert session.scalar(
            select(func.count()).select_from(LongTermContainer).where(
                LongTermContainer.container_id == with_owner.id,
            )
        ) == 1


def test_anvil_lt02_extra_client_fields_do_not_change_guard(client, monkeypatch, db_session):
    base = {"container_id": None, "is_long_term": None}
    extra_fields = {
        "page": "detail",
        "source": "manage-machine",
        "can_enable": False,
        "force": True,
    }

    def _post(container_id, is_long_term, *, extra=False):
        body = {**base, "container_id": container_id, "is_long_term": is_long_term}
        if extra:
            body.update(extra_fields)
        return client.post("/api/containers/set_long_term_container", json=body)

    # 1) 配额已满
    quota_root, quota_machine, quota_target = create_container_graph()
    _r2, _m2, quota_other = create_container_graph(
        root_user=quota_root, machine=quota_machine,
    )
    long_term_container_repo.add(
        quota_other.id, created_by_user_id=quota_root.id, session=db_session,
    )
    quota_freeze = _seed_freeze(db_session, quota_target.id)
    _auth(monkeypatch, quota_root.id)

    baseline = _post(quota_target.id, True)
    extra = _post(quota_target.id, True, extra=True)
    assert baseline.status_code == extra.status_code == 409
    assert _error_reason(baseline) == _error_reason(extra) == "long_term_limit_reached"
    assert long_term_container_repo.is_long_term(quota_target.id, session=db_session) is False
    assert _freeze_fields(db_session, quota_target.id) == quota_freeze
    quota_logs = _failure_audits(db_session, quota_target.id)
    assert [log.error_reason for log in quota_logs] == ["long_term_limit_reached"] * 2
    assert _success_audits(db_session, quota_target.id) == []

    # 2) 磁盘硬超限
    disk_root, disk_machine, disk_target = create_container_graph()
    disk_machine.max_disk_size_gb = 512
    disk_target.disk_total_bytes = 600 * 1024**3
    db_session.commit()
    disk_freeze = _seed_freeze(db_session, disk_target.id)
    _auth(monkeypatch, disk_root.id)

    baseline = _post(disk_target.id, True)
    extra = _post(disk_target.id, True, extra=True)
    assert baseline.status_code == extra.status_code == 409
    assert _error_reason(baseline) == _error_reason(extra) == "disk_usage_over_limit"
    assert long_term_container_repo.is_long_term(disk_target.id, session=db_session) is False
    assert _freeze_fields(db_session, disk_target.id) == disk_freeze
    disk_logs = _failure_audits(db_session, disk_target.id)
    assert [log.error_reason for log in disk_logs] == ["disk_usage_over_limit"] * 2
    assert _success_audits(db_session, disk_target.id) == []

    # 3) 冻结中取消
    frozen_root, _frozen_machine, frozen_target = create_container_graph()
    long_term_container_repo.add(
        frozen_target.id, created_by_user_id=frozen_root.id, session=db_session,
    )
    frozen_freeze = _seed_freeze(db_session, frozen_target.id)
    frozen_target.container_status = ContainerStatus.PAUSED
    db_session.commit()
    _auth(monkeypatch, frozen_root.id)

    baseline = _post(frozen_target.id, False)
    extra = _post(frozen_target.id, False, extra=True)
    assert baseline.status_code == extra.status_code == 409
    assert _error_reason(baseline) == _error_reason(extra) == "container_paused"
    assert long_term_container_repo.is_long_term(frozen_target.id, session=db_session) is True
    assert _freeze_fields(db_session, frozen_target.id) == frozen_freeze
    frozen_logs = _failure_audits(db_session, frozen_target.id)
    assert [log.error_reason for log in frozen_logs] == ["container_paused"] * 2
    assert _success_audits(db_session, frozen_target.id) == []


def test_anvil_lt03_permission_and_not_found_contract(client, monkeypatch, db_session):
    root, _machine, container = create_container_graph()
    body = {"container_id": container.id, "is_long_term": True}

    _auth(monkeypatch, root.id, entity_ok=False)
    denied_entity = client.post("/api/containers/set_long_term_container", json=body)
    assert denied_entity.status_code == 403
    assert _error_reason(denied_entity) == "insufficient_permission"

    _auth(
        monkeypatch, root.id,
        resource_fn=lambda uid, rtype, rid: rtype != "container:root",
    )
    denied_resource = client.post("/api/containers/set_long_term_container", json=body)
    assert denied_resource.status_code == 403
    assert _error_reason(denied_resource) == "resource_access_denied"

    _auth(
        monkeypatch, root.id,
        resource_fn=lambda uid, rtype, rid: rtype != "machine",
    )
    denied_machine = client.post("/api/containers/set_long_term_container", json=body)
    assert denied_machine.status_code == 403
    assert _error_reason(denied_machine) == "machine_access_denied"

    _auth(monkeypatch, root.id, stub_machine=False)
    missing = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": 999999, "is_long_term": True},
    )
    assert missing.status_code == 404
    assert _error_reason(missing) == "container_not_found"

    assert long_term_container_repo.is_long_term(container.id, session=db_session) is False
    assert _freeze_fields(db_session, container.id) is None
    assert db_session.scalar(select(func.count()).select_from(OperationLog)) == 0


def test_anvil_lt04_guard_rejections_keep_freeze_and_audit(client, monkeypatch, db_session):
    # 配额拒绝
    quota_root, quota_machine, quota_target = create_container_graph()
    _r2, _m2, quota_other = create_container_graph(
        root_user=quota_root, machine=quota_machine,
    )
    long_term_container_repo.add(
        quota_other.id, created_by_user_id=quota_root.id, session=db_session,
    )
    quota_freeze = _seed_freeze(db_session, quota_target.id)
    _auth(monkeypatch, quota_root.id)

    resp = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": quota_target.id, "is_long_term": True},
    )
    assert resp.status_code == 409
    assert resp.json()["error_reason"] == "long_term_limit_reached"
    assert long_term_container_repo.is_long_term(quota_target.id, session=db_session) is False
    assert _freeze_fields(db_session, quota_target.id) == quota_freeze
    quota_logs = _failure_audits(db_session, quota_target.id)
    assert len(quota_logs) == 1
    assert quota_logs[0].error_reason == "long_term_limit_reached"
    assert _success_audits(db_session, quota_target.id) == []

    # 磁盘硬限制拒绝
    disk_root, disk_machine, disk_target = create_container_graph()
    disk_machine.max_disk_size_gb = 512
    disk_target.disk_total_bytes = 600 * 1024**3
    db_session.commit()
    disk_freeze = _seed_freeze(db_session, disk_target.id)
    _auth(monkeypatch, disk_root.id)

    resp = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": disk_target.id, "is_long_term": True},
    )
    assert resp.status_code == 409
    assert resp.json()["error_reason"] == "disk_usage_over_limit"
    assert long_term_container_repo.is_long_term(disk_target.id, session=db_session) is False
    assert _freeze_fields(db_session, disk_target.id) == disk_freeze
    disk_logs = _failure_audits(db_session, disk_target.id)
    assert len(disk_logs) == 1
    assert disk_logs[0].error_reason == "disk_usage_over_limit"
    assert _success_audits(db_session, disk_target.id) == []


def test_anvil_lt05_cancel_rejection_keeps_freeze_and_writes_failure(
    client, monkeypatch, db_session,
):
    root, _machine, container = create_container_graph()
    long_term_container_repo.add(
        container.id, created_by_user_id=root.id, session=db_session,
    )
    before = _seed_freeze(db_session, container.id)
    container.container_status = ContainerStatus.PAUSED
    db_session.commit()
    _auth(monkeypatch, root.id)

    resp = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": container.id, "is_long_term": False},
    )
    assert resp.status_code == 409
    assert resp.json()["error_reason"] == "container_paused"
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True
    assert _freeze_fields(db_session, container.id) == before
    failure = _failure_audits(db_session, container.id)
    assert len(failure) == 1
    assert failure[0].error_reason == "container_paused"
    assert _success_audits(db_session, container.id) == []


def test_anvil_lt06_reread_changed_facts_rejudged(monkeypatch, db_session):
    # 启用方向：模拟另一请求已把目标改成长期
    enable_root, enable_machine, enable_target = create_container_graph()
    long_term_container_repo.add(
        enable_target.id, created_by_user_id=enable_root.id, session=db_session,
    )
    enable_freeze = _seed_freeze(db_session, enable_target.id)
    enable_bindings = [{"user_id": enable_root.id, "role": ROLE.ROOT}]
    monkeypatch.setattr(
        container_tasks, "_read_long_term_target",
        lambda session, cid: (enable_target, enable_bindings, True, enable_machine),
    )

    result = container_tasks.set_long_term_container(
        enable_target.id, True, operator_user_id=enable_root.id,
    )
    assert result["is_long_term"] is True
    db_session.expire_all()
    assert _long_term_count(db_session, enable_target.id) == 1
    assert _success_audits(db_session, enable_target.id) == []
    assert _freeze_fields(db_session, enable_target.id) == enable_freeze

    # 取消方向：模拟另一请求已把目标改成非长期
    cancel_root, cancel_machine, cancel_target = create_container_graph()
    cancel_freeze = _seed_freeze(db_session, cancel_target.id)
    cancel_bindings = [{"user_id": cancel_root.id, "role": ROLE.ROOT}]
    monkeypatch.setattr(
        container_tasks, "_read_long_term_target",
        lambda session, cid: (cancel_target, cancel_bindings, False, cancel_machine),
    )

    result = container_tasks.set_long_term_container(
        cancel_target.id, False, operator_user_id=cancel_root.id,
    )
    assert result["is_long_term"] is False
    db_session.expire_all()
    assert _long_term_count(db_session, cancel_target.id) == 0
    assert _success_audits(db_session, cancel_target.id) == []
    assert _freeze_fields(db_session, cancel_target.id) == cancel_freeze

    # 状态冻结方向：模拟写入前读取到 paused
    paused_root, paused_machine, paused_target = create_container_graph()
    long_term_container_repo.add(
        paused_target.id, created_by_user_id=paused_root.id, session=db_session,
    )
    paused_freeze = _seed_freeze(db_session, paused_target.id)
    paused_target.container_status = ContainerStatus.PAUSED
    db_session.commit()
    paused_bindings = [{"user_id": paused_root.id, "role": ROLE.ROOT}]
    monkeypatch.setattr(
        container_tasks, "_read_long_term_target",
        lambda session, cid: (paused_target, paused_bindings, True, paused_machine),
    )

    with pytest.raises(NodeServiceError) as excinfo:
        container_tasks.set_long_term_container(
            paused_target.id, False, operator_user_id=paused_root.id,
        )
    assert excinfo.value.reason == "container_paused"
    db_session.expire_all()
    assert _long_term_count(db_session, paused_target.id) == 1
    assert _success_audits(db_session, paused_target.id) == []
    assert _freeze_fields(db_session, paused_target.id) == paused_freeze


def test_anvil_lt07_marker_removal_restores_short_term_cleanup(
    app, db_session, mock_node_send,
):
    root, machine, container = create_container_graph()
    db_session.add(ContainerSSHLogin(
        machine_id=machine.id,
        container_id=container.id,
        last_ssh_login_time=(datetime.utcnow() - timedelta(days=8)).isoformat(),
    ))
    long_term_container_repo.add(
        container.id, created_by_user_id=root.id, session=db_session,
    )
    db_session.commit()
    calls = mock_node_send(NODE_REMOVE_SUCCESS)

    container_cleanup_task.cleanup_expired_containers_once(7)
    db_session.expire_all()
    retained = containers_repo.get_by_id(
        container.id, session=db_session, include_invalid=True,
    )
    assert retained is not None and retained.is_valid is True
    assert calls == []

    long_term_container_repo.remove(container.id, session=db_session)
    db_session.commit()
    container_cleanup_task.cleanup_expired_containers_once(7)
    db_session.expire_all()
    retained = containers_repo.get_by_id(
        container.id, session=db_session, include_invalid=True,
    )
    assert retained is not None and retained.is_valid is False
    assert calls and calls[-1]["url"].endswith("/remove_container")
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is False


def test_anvil_lt08_repeated_cancel_keeps_container_valid(app, db_session):
    root, _machine, container = create_container_graph()
    freeze = _seed_freeze(db_session, container.id)
    before_row = containers_repo.get_by_id(
        container.id, session=db_session, include_invalid=True,
    )
    assert before_row is not None
    before_valid = before_row.is_valid
    before_deleted_at = before_row.deleted_at

    result = container_tasks.set_long_term_container(
        container.id, False, operator_user_id=root.id,
    )

    db_session.expire_all()
    assert result["is_long_term"] is False
    assert _long_term_count(db_session, container.id) == 0
    assert _success_audits(db_session, container.id) == []
    assert _freeze_fields(db_session, container.id) == freeze
    retained = containers_repo.get_by_id(
        container.id, session=db_session, include_invalid=True,
    )
    assert retained is not None
    assert retained.is_valid is before_valid is True
    assert retained.deleted_at == before_deleted_at
    delete_logs = list(db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == OperationType.DELETE_CONTAINER,
            OperationLog.target_id == container.id,
        )
    ).all())
    assert delete_logs == []


# ---------------------------------------------------------------------------
# freeze-state 能力
# ---------------------------------------------------------------------------


def test_anvil_dfs01_freeze_readback_contract(app, db_session):
    _r1, _m1, default_container = create_container_graph()
    _r2, _m2, full_container = create_container_graph()
    _r3, _m3, null_container = create_container_graph()
    before = datetime.utcnow()

    default_row = container_disk_freeze_state_repo.upsert_first_frozen(
        default_container.id, session=db_session,
    )
    db_session.commit()

    container_disk_freeze_state_repo.upsert_first_frozen(
        full_container.id, session=db_session,
    )
    container_disk_freeze_state_repo.set_grace(full_container.id, 3, session=db_session)
    full_row = container_disk_freeze_state_repo.get(
        full_container.id, session=db_session, include_invalid=True,
    )
    full_row.deferral_seconds = 321
    db_session.commit()

    container_disk_freeze_state_repo.upsert_first_frozen(
        null_container.id, session=db_session,
    )
    db_session.commit()
    db_session.execute(
        update(ContainerDiskFreezeState).where(
            ContainerDiskFreezeState.container_id == null_container.id,
        ).values(deferral_seconds=None)
    )
    db_session.commit()
    after = datetime.utcnow()

    with session_scope(commit=False) as session:
        default = session.get(ContainerDiskFreezeState, default_container.id)
        full = session.get(ContainerDiskFreezeState, full_container.id)
        null = session.get(ContainerDiskFreezeState, null_container.id)

        assert default is not None and full is not None and null is not None
        for row, container in (
            (default, default_container),
            (full, full_container),
            (null, null_container),
        ):
            assert isinstance(row.container_id, int)
            assert row.container_id == container.id
            assert isinstance(row.first_frozen_at, datetime)
            assert before <= row.first_frozen_at <= after
            assert isinstance(row.created_at, datetime)
            assert before <= row.created_at <= after
            assert session.scalar(
                select(func.count()).select_from(ContainerDiskFreezeState).where(
                    ContainerDiskFreezeState.container_id == container.id,
                )
            ) == 1

        assert default.deferral_seconds == 0
        assert default.grace_until is None
        assert isinstance(full.deferral_seconds, int) and full.deferral_seconds == 321
        assert isinstance(full.grace_until, datetime)
        assert null.deferral_seconds is None
        assert null.grace_until is None


def test_anvil_dfs02_restore_then_new_freeze_starts_new_cycle(
    app, db_session, monkeypatch, mock_node_send,
):
    root, machine, container = create_container_graph()
    container.image_id = 1
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    container.bind_mount_path = f"/home/{root.username}/containers/{container.name}_data"
    long_term_container_repo.add(
        container.id, created_by_user_id=root.id, session=db_session,
    )
    old_anchor = datetime(2020, 1, 1, 12, 0, 0)
    row = container_disk_freeze_state_repo.upsert_first_frozen(
        container.id, session=db_session,
    )
    row.first_frozen_at = old_anchor
    row.deferral_seconds = 321
    container_disk_freeze_state_repo.set_grace(container.id, 3, session=db_session)
    db_session.commit()

    mock_node_send(NODE_REMOVE_SUCCESS)
    assert container_tasks.remove_container(
        container.id, operator_user_id=root.id,
    ) is True
    db_session.expire_all()
    assert _freeze_fields(db_session, container.id) is None
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()

    restored = container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)
    assert restored["container_id"] == container.id
    db_session.expire_all()
    assert _freeze_fields(db_session, container.id) is None
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True

    machine.max_disk_size_gb = 512
    db_session.commit()
    target = containers_repo.get_by_id(container.id, session=db_session)
    assert target is not None
    _enable_disk_settings(monkeypatch)
    hard_calls = []
    monkeypatch.setattr(
        container_disk_check_task, "_handle_hard_limit",
        lambda c, u, a: hard_calls.append(c.id),
    )
    monkeypatch.setattr(
        container_disk_check_task, "_handle_freeze_escalation",
        lambda c, u, a, days_frozen=0: None,
    )
    usage = {
        "container": {
            "overlay_rw_bytes": 400 * 1024**3,
            "bind_mount_bytes": 300 * 1024**3,
            "total_bytes": 700 * 1024**3,
        },
    }
    container_disk_check_task._evaluate_limits(target, usage)

    db_session.expire_all()
    state = container_disk_freeze_state_repo.get(
        container.id, session=db_session, include_invalid=True,
    )
    assert state is not None
    assert state.first_frozen_at > old_anchor
    assert state.deferral_seconds == 0
    assert state.grace_until is None
    assert hard_calls == [container.id]


# ---------------------------------------------------------------------------
# user-container 能力
# ---------------------------------------------------------------------------


def test_anvil_uc01_user_container_readback_contract(app, db_session):
    root, _machine, container = create_container_graph()
    full_user = create_user()
    minimal_user = create_user()
    before = datetime.utcnow()

    bind_user_container(
        full_user, container, role=ROLE.ADMIN,
        username="anvil_full_user", public_key="ssh-rsa AAAAANVIL",
    )
    bind_user_container(
        minimal_user, container, role=ROLE.COLLABORATOR,
        username="anvil_minimal_user",
    )
    after = datetime.utcnow()

    with session_scope(commit=False) as session:
        full = session.get(UserContainer, (full_user.id, container.id))
        minimal = session.get(UserContainer, (minimal_user.id, container.id))

        assert full is not None and minimal is not None
        assert isinstance(full.user_id, int) and full.user_id == full_user.id
        assert isinstance(full.container_id, int) and full.container_id == container.id
        assert getattr(full.role, "value", full.role) == ROLE.ADMIN.value
        assert isinstance(full.granted_at, datetime)
        assert before <= full.granted_at <= after
        assert full.public_key == "ssh-rsa AAAAANVIL"
        assert full.username == "anvil_full_user"
        assert minimal.user_id == minimal_user.id
        assert minimal.container_id == container.id
        assert getattr(minimal.role, "value", minimal.role) == ROLE.COLLABORATOR.value
        assert minimal.public_key is None
        assert minimal.username == "anvil_minimal_user"
        assert isinstance(minimal.granted_at, datetime)
        for user_id in (full_user.id, minimal_user.id):
            assert session.scalar(
                select(func.count()).select_from(UserContainer).where(
                    UserContainer.user_id == user_id,
                    UserContainer.container_id == container.id,
                )
            ) == 1


def test_anvil_uc02_update_role_persists_binding(app, db_session, monkeypatch):
    collaborator = create_user()
    root, _machine, container = create_container_graph(
        collaborator_user=collaborator,
        collaborator_username=collaborator.username,
    )
    calls = _install_node(monkeypatch, [{"success": 1}])

    assert container_tasks.update_role(
        container.id, collaborator.id, ROLE.ADMIN, root.id,
    ) is True

    db_session.expire_all()
    binding = _binding(db_session, collaborator.id, container.id)
    assert binding is not None
    assert _role_value(binding) == ROLE.ADMIN.value
    assert binding["username"] == collaborator.username
    assert len(calls) == 1
    config = calls[0]["payload"]["config"]
    assert config["updated_role"] == "admin"
    assert config["user_name"] == collaborator.username
    assert "password" not in config and "root_password" not in config
    logs = _role_logs(db_session, success=True, container_id=container.id)
    assert logs
    assert logs[-1].detail["old_role"] == ROLE.COLLABORATOR.value
    assert logs[-1].detail["new_role"] == ROLE.ADMIN.value


def test_anvil_uc02_user_binding_changes_keep_other_bindings(app, db_session, monkeypatch):
    collaborator = create_user()
    root, _machine, container = create_container_graph(
        collaborator_user=collaborator,
        collaborator_username=collaborator.username,
    )
    calls = _install_node(monkeypatch, [{"success": 1}])
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)

    result = container_tasks.start_root_demotion(container.id, root.id, root.id)
    assert len(result["credentials"]) == 1
    credential = result["credentials"][0]
    assert credential["login_name"] == root.username

    db_session.expire_all()
    old_root = _binding(db_session, root.id, container.id)
    other = _binding(db_session, collaborator.id, container.id)
    assert old_root is not None and other is not None
    assert _role_value(old_root) == ROLE.ADMIN.value
    assert old_root["username"] == root.username
    assert _role_value(other) == ROLE.COLLABORATOR.value
    assert other["username"] == collaborator.username
    assert len(calls) == 1
    assert calls[0]["payload"]["config"]["password"] == credential["password"]


def test_anvil_uc07_direct_root_demotion_api_returns_credential(
    client, app, db_session, monkeypatch,
):
    collaborator = create_user()
    root, _machine, container = create_container_graph(
        collaborator_user=collaborator,
        collaborator_username=collaborator.username,
    )
    calls = _install_node(monkeypatch, [{"success": 1}])
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)
    _auth(monkeypatch, root.id)

    resp = client.post(
        "/api/containers/update_role",
        json={"container_id": container.id, "user_id": root.id, "updated_role": "ADMIN"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] is True
    assert resp.headers["Cache-Control"] == "no-store"
    assert len(body["credentials"]) == 1
    credential = body["credentials"][0]
    assert credential["login_name"] == root.username
    assert len(calls) == 1
    assert calls[0]["payload"]["config"]["password"] == credential["password"]
    assert "root_password" not in calls[0]["payload"]["config"]

    db_session.expire_all()
    old_root = _binding(db_session, root.id, container.id)
    other = _binding(db_session, collaborator.id, container.id)
    assert _role_value(old_root) == ROLE.ADMIN.value
    assert old_root["username"] == root.username
    assert _role_value(other) == ROLE.COLLABORATOR.value


def test_anvil_uc08_handover_preflight_api_maps_409(client, monkeypatch, db_session):
    def _post(container_id, user_id):
        return client.post(
            "/api/containers/update_role",
            json={"container_id": container_id, "user_id": user_id, "updated_role": "ROOT"},
        )

    def _assert_case(root, container_id, user_id, expected_reason):
        calls = _install_node(monkeypatch, [{"success": 1}])
        generated = []
        jobs = []
        monkeypatch.setattr(
            collaborator_utils, "generate_container_password",
            lambda: generated.append(True) or "NeverUsedPwd_123",
        )
        monkeypatch.setattr(
            collaborator_utils, "spawn_background",
            lambda name, target, *args: jobs.append((name, target, args)),
        )
        _auth(monkeypatch, root.id)

        resp = _post(container_id, user_id)
        assert resp.status_code == 409, resp.text
        assert resp.json()["error_reason"] == expected_reason
        assert "credentials" not in resp.json()
        assert generated == []
        assert calls == []
        assert jobs == []

    # 目标未绑定
    root, _machine, container = create_container_graph()
    target = create_user()
    _assert_case(root, container.id, target.id, "target_not_bound")

    # 目标系统用户名为 root
    root, _machine, container = create_container_graph()
    target = create_user(username="root")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username="root")
    _assert_case(root, container.id, target.id, "invalid_target_account")

    # 目标系统用户名前导 -
    root, _machine, container = create_container_graph()
    target = create_user(username="-anvil_bad_target")
    bind_user_container(
        target, container, role=ROLE.COLLABORATOR, username=target.username,
    )
    _assert_case(root, container.id, target.id, "invalid_target_account")

    # 旧 ROOT 系统用户名前导 -
    bad_root = create_user(username="-anvil_bad_root")
    root, _machine, container = create_container_graph(root_user=bad_root)
    target = create_user()
    bind_user_container(
        target, container, role=ROLE.COLLABORATOR, username=target.username,
    )
    _assert_case(bad_root, container.id, target.id, "invalid_root_owner_account")


def test_anvil_uc03_multi_root_demotion_failure_writes_failure(
    app, db_session, monkeypatch,
):
    root, _machine, container = create_container_graph()
    target = create_user()
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    historic_root = create_user(username="anvil_historic_root")
    bind_user_container(historic_root, container, role=ROLE.ROOT, username="root")
    calls = _install_node(monkeypatch, [
        {"success": 1},
        {"success": 0, "error_reason": "anvil_second_admin_failed"},
    ])
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)

    result = container_tasks.start_root_handover(container.id, target.id, root.id)

    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin", "admin"]
    db_session.expire_all()
    assert _role_value(_binding(db_session, target.id, container.id)) == ROLE.COLLABORATOR.value
    assert len(_root_ids(db_session, container.id)) == 1
    failures = _role_logs(db_session, success=False, container_id=container.id)
    successes = _role_logs(db_session, success=True, container_id=container.id)
    assert len(failures) == 1
    assert failures[0].error_reason
    assert len(successes) == 1
    assert successes[0].detail.get("user_id") != target.id
    assert all(
        log.detail.get("user_id") != target.id
        for log in successes
    )
    _assert_no_password_in_logs(db_session, [c["password"] for c in result["credentials"]])


def test_anvil_uc04_binding_failure_writes_failure_oplog(app, db_session, monkeypatch):
    # 降级步骤绑定失败
    with monkeypatch.context() as m:
        root, _machine, container = create_container_graph()
        target = create_user()
        bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
        calls = _install_node(m, [{"success": 1}])
        m.setattr(collaborator_utils, "spawn_background", _run_now)
        m.setattr(collaborator_utils, "_update_collaborator_binding", lambda *args, **kwargs: False)

        result = container_tasks.start_root_handover(container.id, target.id, root.id)

        assert len(calls) == 1
        db_session.expire_all()
        assert _root_ids(db_session, container.id) == [root.id]
        assert _role_value(_binding(db_session, target.id, container.id)) == ROLE.COLLABORATOR.value
        assert _role_logs(db_session, success=True, container_id=container.id) == []
        failures = _role_logs(db_session, success=False, container_id=container.id)
        assert len(failures) == 1
        assert failures[0].error_reason == "role_binding_failed"
        _assert_no_password_in_logs(db_session, [c["password"] for c in result["credentials"]])

    # 目标升级步骤绑定失败
    with monkeypatch.context() as m:
        root, _machine, container = create_container_graph()
        target = create_user()
        bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
        calls = _install_node(m, [{"success": 1}, {"success": 1}])
        m.setattr(collaborator_utils, "spawn_background", _run_now)
        original_update = collaborator_utils._update_collaborator_binding
        counter = {"n": 0}

        def _fail_second(*args, **kwargs):
            counter["n"] += 1
            if counter["n"] >= 2:
                return False
            return original_update(*args, **kwargs)

        m.setattr(collaborator_utils, "_update_collaborator_binding", _fail_second)

        result = container_tasks.start_root_handover(container.id, target.id, root.id)

        assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin", "root"]
        db_session.expire_all()
        assert _role_value(_binding(db_session, root.id, container.id)) == ROLE.ADMIN.value
        assert _role_value(_binding(db_session, target.id, container.id)) == ROLE.COLLABORATOR.value
        assert len(_role_logs(db_session, success=True, container_id=container.id)) == 1
        failures = _role_logs(db_session, success=False, container_id=container.id)
        assert len(failures) == 1
        assert failures[0].error_reason == "role_binding_failed"
        _assert_no_password_in_logs(db_session, [c["password"] for c in result["credentials"]])


def test_anvil_uc05_background_guard_failure_writes_failure_oplog(
    app, db_session, monkeypatch,
):
    root, _machine, container = create_container_graph()
    target = create_user()
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    calls = _install_node(monkeypatch, [{"success": 1}])
    captured = _capture_background(monkeypatch)

    result = container_tasks.start_root_handover(container.id, target.id, root.id)
    assert captured["target"] is not None
    container.container_status = ContainerStatus.OFFLINE
    db_session.commit()
    captured["target"](*captured["args"])

    db_session.expire_all()
    assert calls == []
    assert _role_value(_binding(db_session, target.id, container.id)) == ROLE.COLLABORATOR.value
    assert _root_ids(db_session, container.id) == [root.id]
    assert _role_logs(db_session, success=True, container_id=container.id) == []
    failures = _role_logs(db_session, success=False, container_id=container.id)
    assert len(failures) == 1
    assert failures[0].error_reason == "container_offline"
    _assert_no_password_in_logs(db_session, [c["password"] for c in result["credentials"]])


def test_anvil_uc06_delete_user_internal_promotion_failure_no_retry(
    app, db_session, monkeypatch,
):
    root, _machine, container = create_container_graph()
    target = create_user()
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    calls = _install_node(monkeypatch, [
        {"success": 0, "error": "raw node body SECRET", "error_reason": "anvil_transfer_failed"},
    ])

    assert user_tasks.Delete_user(root.id) is False

    db_session.expire_all()
    assert len(calls) == 1
    config = calls[0]["payload"]["config"]
    assert config["updated_role"] == "root"
    password = config["root_password"]
    assert password
    assert password != f"{root.username}123"
    assert _role_value(_binding(db_session, root.id, container.id)) == ROLE.ROOT.value
    assert _role_value(_binding(db_session, target.id, container.id)) == ROLE.COLLABORATOR.value
    assert any(
        log.operation == OperationType.DELETE_USER and not log.success
        for log in db_session.scalars(select(OperationLog)).all()
    )
    for log in db_session.scalars(select(OperationLog)).all():
        text = f"{log.detail}|{log.error_reason}"
        assert password not in text
        assert "SECRET" not in text
