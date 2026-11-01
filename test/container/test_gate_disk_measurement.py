"""磁盘路径与测量接收、评估年龄、旧 Node 兼容。

覆盖：resolved 修正、no_bind 清空、unresolved 保留、旧 Node 不覆盖已校正路径、
路径变化清旧测量、失败/缺组成/无效时间不写 0、重复缓存帧不推进、过期测量不动作、
手动刷新不再写回。全部用隔离 SQLite 与帧级 mock，不连接真实 Node/Docker。
"""

from datetime import datetime, timedelta

import pytest

from ...api import container_api, deps
from ...models.containers import Container
from ...repositories import containers_repo, container_disk_freeze_state_repo, long_term_container_repo
from ...schedulers import container_disk_check_task
from ...services.container_module import node_comms
from ...services.container_module.information import _build_disk_usage_response
from ...services.container_module.node_comms_modules import snapshots as disk_snapshots
from ..factories import create_container_graph


@pytest.fixture(autouse=True)
def _reset_no_bind_markers():
    disk_snapshots._clear_no_bind_disk_markers()
    yield
    disk_snapshots._clear_no_bind_disk_markers()


pytestmark = pytest.mark.usefixtures("ensure_auth_users")


def _auth(monkeypatch, *, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)


def _frame(container, *, status, path, total=100, overlay=40, bind=60, measured_at=None, **extra):
    container_payload = {
        "mount_path_status": status,
        "bind_mount_path": path,
        "total_bytes": total,
        "overlay_rw_bytes": overlay,
        "bind_mount_bytes": bind,
        "measured_at": measured_at,
    }
    container_payload.update(extra)
    return {"containers": {container.name: container_payload}}


def _apply(container, machine_id, payload):
    return node_comms.apply_disk_usage_snapshot(payload, machine_id)


def _row(db_session, container_id):
    db_session.expire_all()
    return db_session.get(Container, container_id)


def _set_disk(db_session, container, *, path="/home/u/containers/a/", checked_at=None):
    container.bind_mount_path = path
    container.disk_overlay_rw_bytes = 11
    container.disk_bind_mount_bytes = 22
    container.disk_total_bytes = 33
    container.disk_checked_at = checked_at or (datetime.utcnow() - timedelta(minutes=5))
    db_session.commit()


def test_resolved_path_updates_and_accepts_same_frame(app, db_session):
    _root, machine, container = create_container_graph()
    _set_disk(db_session, container)
    measured = datetime.utcnow().replace(microsecond=0)
    new_path = "/home/u/containers/b/"

    result = _apply(container, machine.id, _frame(
        container, status="resolved", path=new_path,
        total=1000, overlay=400, bind=600, measured_at=measured.isoformat() + "Z",
    ))

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == new_path
    assert row.disk_total_bytes == 1000
    assert row.disk_overlay_rw_bytes == 400
    assert row.disk_bind_mount_bytes == 600
    assert row.disk_checked_at == measured


def test_no_bind_clears_path_and_old_measurement_then_accepts_overlay_only(app, db_session):
    _root, machine, container = create_container_graph()
    _set_disk(db_session, container)
    measured = datetime.utcnow().replace(microsecond=0)

    result = _apply(container, machine.id, _frame(
        container, status="no_bind", path=None, total=700, overlay=700, bind=None,
        measured_at=measured.isoformat(),
    ))

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path is None
    assert row.disk_bind_mount_bytes is None
    assert row.disk_total_bytes == 700
    assert row.disk_overlay_rw_bytes == 700
    assert row.disk_checked_at == measured


def test_unresolved_preserves_path_and_accepts_same_path_measurement(app, db_session):
    _root, machine, container = create_container_graph()
    _set_disk(db_session, container)
    measured = datetime.utcnow().replace(microsecond=0)

    result = _apply(container, machine.id, _frame(
        container, status="unresolved", path=container.bind_mount_path,
        total=900, overlay=300, bind=600, measured_at=measured.isoformat(),
    ))

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == "/home/u/containers/a/"
    assert row.disk_total_bytes == 900
    assert row.disk_checked_at == measured


def test_not_running_preserves_path_and_accepts_same_path_measurement(app, db_session):
    _root, machine, container = create_container_graph()
    _set_disk(db_session, container)
    measured = datetime.utcnow().replace(microsecond=0)

    result = _apply(container, machine.id, _frame(
        container, status="not_running", path=container.bind_mount_path,
        total=910, overlay=310, bind=600, measured_at=measured.isoformat(),
    ))

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == "/home/u/containers/a/"
    assert row.disk_total_bytes == 910
    assert row.disk_checked_at == measured


def test_dev_inode_pid_are_not_consumed_or_persisted(app, db_session):
    _root, machine, container = create_container_graph()
    _set_disk(db_session, container)
    measured = datetime.utcnow().replace(microsecond=0)

    result = _apply(container, machine.id, _frame(
        container, status="resolved", path=container.bind_mount_path,
        total=920, overlay=320, bind=600, measured_at=measured.isoformat(),
        st_dev=2049, st_ino=123456, pid=4242, source="/proc/4242/root/root",
    ))

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.disk_total_bytes == 920
    assert row.bind_mount_path == "/home/u/containers/a/"
    assert not {c.name for c in Container.__table__.columns} & {
        "st_dev", "st_ino", "pid", "disk_identity", "disk_identity_status",
    }


def test_legacy_frame_does_not_overwrite_corrected_path(app, db_session):
    _root, machine, container = create_container_graph()
    _set_disk(db_session, container, path="/home/u/containers/b/")
    old_checked = datetime.utcnow() - timedelta(hours=2)
    container.disk_checked_at = old_checked
    db_session.commit()
    before = (container.disk_total_bytes, container.disk_overlay_rw_bytes, container.disk_bind_mount_bytes)

    result = _apply(container, machine.id, {
        "containers": {container.name: {
            "bind_mount_path": "/home/u/containers/a/",
            "total_bytes": 950, "overlay_rw_bytes": 350, "bind_mount_bytes": 600,
        }},
    })

    row = _row(db_session, container.id)
    assert result == {"updated": 0, "skipped": 1}
    assert row.bind_mount_path == "/home/u/containers/b/"
    assert (row.disk_total_bytes, row.disk_overlay_rw_bytes, row.disk_bind_mount_bytes) == before
    assert row.disk_checked_at == old_checked


def test_legacy_frame_establishes_path_only_when_current_path_empty(app, db_session):
    _root, machine, container = create_container_graph()

    result = _apply(container, machine.id, {
        "containers": {container.name: {
            "bind_mount_path": "/home/u/containers/legacy/",
            "total_bytes": 100, "overlay_rw_bytes": 40, "bind_mount_bytes": 60,
        }},
    })

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == "/home/u/containers/legacy/"
    assert row.disk_total_bytes == 100
    assert row.disk_checked_at is not None


def test_no_bind_marker_blocks_legacy_path_rebuild(app, db_session):
    _root, machine, container = create_container_graph()
    measured = datetime.utcnow().replace(microsecond=0)
    _apply(container, machine.id, _frame(
        container, status="no_bind", path=None, total=500, overlay=500, bind=None,
        measured_at=measured.isoformat(),
    ))
    assert _row(db_session, container.id).bind_mount_path is None

    result = _apply(container, machine.id, {
        "containers": {container.name: {
            "bind_mount_path": "/home/u/containers/legacy/",
            "total_bytes": 100, "overlay_rw_bytes": 40, "bind_mount_bytes": 60,
        }},
    })

    row = _row(db_session, container.id)
    assert result == {"updated": 0, "skipped": 1}
    assert row.bind_mount_path is None
    assert row.disk_total_bytes == 500
    assert row.disk_checked_at == measured


def test_no_bind_then_resolved_allows_legacy_same_path_after_marker_clear(app, db_session):
    _root, machine, container = create_container_graph()
    first_measured = datetime.utcnow().replace(microsecond=0) - timedelta(seconds=10)
    _apply(container, machine.id, _frame(
        container, status="no_bind", path=None, total=500, overlay=500, bind=None,
        measured_at=first_measured.isoformat(),
    ))
    measured = datetime.utcnow().replace(microsecond=0)
    _apply(container, machine.id, _frame(
        container, status="resolved", path="/home/u/containers/new/",
        total=600, overlay=100, bind=500, measured_at=measured.isoformat(),
    ))

    result = _apply(container, machine.id, {
        "containers": {container.name: {
            "bind_mount_path": "/home/u/containers/new/",
            "total_bytes": 650, "overlay_rw_bytes": 150, "bind_mount_bytes": 500,
        }},
    })

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == "/home/u/containers/new/"
    assert row.disk_total_bytes == 650


def test_path_change_clears_old_measurement_and_late_old_sample_is_rejected(app, db_session):
    _root, machine, container = create_container_graph()
    _set_disk(db_session, container)

    first = _apply(container, machine.id, {
        "containers": {container.name: {
            "mount_path_status": "resolved",
            "bind_mount_path": "/home/u/containers/b/",
            "total_bytes": None, "overlay_rw_bytes": 50,
        }},
    })

    row = _row(db_session, container.id)
    assert first == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == "/home/u/containers/b/"
    assert row.disk_total_bytes is None
    assert row.disk_overlay_rw_bytes is None
    assert row.disk_bind_mount_bytes is None
    assert row.disk_checked_at is None

    second = _apply(container, machine.id, {
        "containers": {container.name: {
            "bind_mount_path": "/home/u/containers/a/",
            "total_bytes": 33, "overlay_rw_bytes": 11, "bind_mount_bytes": 22,
        }},
    })
    row = _row(db_session, container.id)
    assert second == {"updated": 0, "skipped": 1}
    assert row.bind_mount_path == "/home/u/containers/b/"
    assert row.disk_total_bytes is None


def test_invalid_measured_at_rejects_measurement_but_still_applies_path(app, db_session):
    _root, machine, container = create_container_graph()
    _set_disk(db_session, container)

    result = _apply(container, machine.id, _frame(
        container, status="resolved", path="/home/u/containers/b/",
        total=1000, overlay=400, bind=600, measured_at="not-a-timestamp",
    ))

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == "/home/u/containers/b/"
    assert row.disk_total_bytes is None
    assert row.disk_checked_at is None


def test_new_protocol_missing_measured_at_rejects_measurement_but_keeps_path(app, db_session):
    _root, machine, container = create_container_graph()
    _set_disk(db_session, container)

    result = _apply(container, machine.id, _frame(
        container, status="resolved", path="/home/u/containers/b/",
        total=1000, overlay=400, bind=600, measured_at=None,
    ))

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == "/home/u/containers/b/"
    assert row.disk_total_bytes is None
    assert row.disk_checked_at is None


def test_future_measured_at_is_rejected_without_touching_existing_facts(app, db_session):
    _root, machine, container = create_container_graph()
    checked = datetime.utcnow() - timedelta(minutes=5)
    _set_disk(db_session, container, checked_at=checked)
    future = datetime.utcnow() + timedelta(minutes=30)

    result = _apply(container, machine.id, _frame(
        container, status="resolved", path=container.bind_mount_path,
        total=999, overlay=333, bind=666, measured_at=future.isoformat(),
    ))

    row = _row(db_session, container.id)
    assert result == {"updated": 0, "skipped": 1}
    assert row.disk_total_bytes == 33
    assert row.disk_checked_at == checked


def test_repeated_cached_frame_does_not_advance_measurement_time(app, db_session):
    _root, machine, container = create_container_graph()
    measured = datetime.utcnow().replace(microsecond=0)
    payload = _frame(
        container, status="resolved", path="/home/u/containers/b/",
        total=1000, overlay=400, bind=600, measured_at=measured.isoformat(),
    )

    _apply(container, machine.id, payload)
    first = _row(db_session, container.id)
    _apply(container, machine.id, payload)
    second = _row(db_session, container.id)

    assert first.disk_checked_at == measured
    assert second.disk_checked_at == measured
    assert second.disk_total_bytes == 1000


def test_measured_at_older_than_checkpoint_rejects_path_and_measurement(app, db_session):
    _root, machine, container = create_container_graph()
    checked = datetime.utcnow()
    _set_disk(db_session, container, checked_at=checked)
    older = (checked - timedelta(hours=1)).isoformat()

    result = _apply(container, machine.id, _frame(
        container, status="resolved", path="/home/u/containers/b/",
        total=1000, overlay=400, bind=600, measured_at=older,
    ))

    row = _row(db_session, container.id)
    assert result == {"updated": 0, "skipped": 1}
    assert row.bind_mount_path == "/home/u/containers/a/"
    assert row.disk_total_bytes == 33
    assert row.disk_checked_at == checked


def test_legacy_frame_with_both_paths_empty_does_not_claim_no_bind(app, db_session):
    _root, machine, container = create_container_graph()

    result = _apply(container, machine.id, {
        "containers": {container.name: {
            "total_bytes": 100, "overlay_rw_bytes": 100, "bind_mount_bytes": None,
        }},
    })

    row = _row(db_session, container.id)
    assert result == {"updated": 0, "skipped": 1}
    assert row.bind_mount_path is None
    assert row.disk_total_bytes is None
    assert row.disk_checked_at is None


def test_update_container_none_does_not_clear_disk_facts(app, db_session):
    _root, _machine, container = create_container_graph()
    _set_disk(db_session, container)

    containers_repo.update_container(
        container.id, bind_mount_path=None, disk_total_bytes=None, session=db_session,
    )
    db_session.commit()
    row = _row(db_session, container.id)
    assert row.bind_mount_path == "/home/u/containers/a/"
    assert row.disk_total_bytes == 33

    containers_repo.update_container(
        container.id,
        clear_fields={"disk_total_bytes", "disk_checked_at"},
        session=db_session,
    )
    db_session.commit()
    row = _row(db_session, container.id)
    assert row.disk_total_bytes is None
    assert row.disk_checked_at is None
    assert row.bind_mount_path == "/home/u/containers/a/"


def test_usage_from_db_requires_fresh_measurement(app, db_session):
    _root, _machine, container = create_container_graph()
    container.disk_total_bytes = 100
    container.disk_overlay_rw_bytes = 40
    container.disk_bind_mount_bytes = 60
    container.bind_mount_path = "/home/u/containers/a/"
    db_session.commit()

    assert container_disk_check_task._usage_from_db(container) is None

    container.disk_checked_at = datetime.utcnow() - timedelta(
        seconds=container_disk_check_task.CONTAINER_DISK_MEASUREMENT_MAX_AGE_SECONDS + 1,
    )
    db_session.commit()
    assert container_disk_check_task._usage_from_db(container) is None

    container.disk_checked_at = datetime.utcnow() - timedelta(
        seconds=container_disk_check_task.CONTAINER_DISK_MEASUREMENT_MAX_AGE_SECONDS - 1,
    )
    db_session.commit()
    assert container_disk_check_task._usage_from_db(container) is not None


def test_scheduler_skips_all_actions_when_measurement_stale(app, db_session, monkeypatch):
    _root, machine, container = create_container_graph()
    machine.max_disk_size_gb = 512
    container.disk_total_bytes = 600 * 1024**3
    container.disk_overlay_rw_bytes = 600 * 1024**3
    container.disk_checked_at = datetime.utcnow() - timedelta(hours=2)
    long_term_container_repo.add(container.id, session=db_session)
    db_session.commit()

    calls = []
    monkeypatch.setattr(container_disk_check_task, "machine_in_scope", lambda _id: True)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_check_enabled", lambda: True)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_response_enabled", lambda: True)
    monkeypatch.setattr(
        container_disk_check_task, "_handle_hard_limit_with_escalation",
        lambda c, _usage, _cache: calls.append(c.id),
    )

    container_disk_check_task.check_all_containers_disk_usage_once()

    assert calls == []
    assert container_disk_freeze_state_repo.get(container.id, session=db_session) is None


def test_manual_refresh_does_not_rewrite_disk_facts(app, client, monkeypatch, db_session):
    _auth(monkeypatch)
    _root, _machine, container = create_container_graph()
    checked = datetime.utcnow() - timedelta(minutes=5)
    _set_disk(db_session, container, checked_at=checked)
    monkeypatch.setattr(
        container_api.container_service,
        "get_container_cleanup_state",
        lambda _container: {
            "last_ssh_login_time": "2026-05-25T10:00:00",
            "cleanup_after_days": 7,
            "cleanup_at": "2026-06-01T10:00:00",
            "seconds_until_cleanup": 123,
            "cleanup_status": "countdown",
        },
    )

    resp = client.post(
        "/api/containers/refresh_last_ssh_login_time",
        json={"container_id": container.id},
    )

    row = _row(db_session, container.id)
    assert resp.status_code == 200
    assert row.bind_mount_path == "/home/u/containers/a/"
    assert (row.disk_overlay_rw_bytes, row.disk_bind_mount_bytes, row.disk_total_bytes) == (11, 22, 33)
    assert row.disk_checked_at == checked


def test_no_bind_marker_lost_after_restart_is_documented_residual(app, db_session):
    """进程内 no_bind 标记不持久化：模拟重启后旧帧可重建路径（已写明的兼容边界）。"""

    _root, machine, container = create_container_graph()
    _apply(container, machine.id, _frame(
        container, status="no_bind", path=None, total=500, overlay=500, bind=None,
        measured_at=datetime.utcnow().replace(microsecond=0).isoformat(),
    ))
    assert _row(db_session, container.id).bind_mount_path is None

    disk_snapshots._clear_no_bind_disk_markers()
    result = _apply(container, machine.id, {
        "containers": {container.name: {
            "bind_mount_path": "/home/u/containers/legacy/",
            "total_bytes": 600, "overlay_rw_bytes": 100, "bind_mount_bytes": 500,
        }},
    })

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == "/home/u/containers/legacy/"
    assert row.disk_total_bytes == 600


def test_legacy_cache_heartbeat_advances_receipt_time_compat(app, db_session):
    _root, machine, container = create_container_graph()
    old_checked = datetime.utcnow() - timedelta(minutes=30)
    _set_disk(db_session, container, checked_at=old_checked)

    result = _apply(container, machine.id, {
        "containers": {container.name: {
            "bind_mount_path": "/home/u/containers/a/",
            "total_bytes": 44, "overlay_rw_bytes": 44, "bind_mount_bytes": 0,
        }},
    })

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.disk_total_bytes == 44
    assert row.disk_checked_at > old_checked
    assert (datetime.utcnow() - row.disk_checked_at).total_seconds() < 60


def test_old_node_rollback_after_correction_stops_actions_once_stale(app, db_session, monkeypatch):
    """已校正路径 B 后回滚旧 Node：A 样本持续被拒；B 的测量过期后不再驱动动作。"""

    _root, machine, container = create_container_graph()
    machine.max_disk_size_gb = 512
    container.bind_mount_path = "/home/u/containers/b/"
    container.disk_total_bytes = 600 * 1024**3
    container.disk_overlay_rw_bytes = 600 * 1024**3
    container.disk_checked_at = datetime.utcnow() - timedelta(minutes=5)
    long_term_container_repo.add(container.id, session=db_session)
    db_session.commit()

    rejected = _apply(container, machine.id, {
        "containers": {container.name: {
            "bind_mount_path": "/home/u/containers/a/",
            "total_bytes": 600 * 1024**3,
            "overlay_rw_bytes": 600 * 1024**3,
            "bind_mount_bytes": 0,
        }},
    })
    assert rejected == {"updated": 0, "skipped": 1}
    assert _row(db_session, container.id).bind_mount_path == "/home/u/containers/b/"

    container.disk_checked_at = datetime.utcnow() - timedelta(hours=2)
    db_session.commit()
    assert container_disk_check_task._usage_from_db(container) is None
    calls = []
    monkeypatch.setattr(container_disk_check_task, "machine_in_scope", lambda _id: True)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_check_enabled", lambda: True)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_response_enabled", lambda: True)
    monkeypatch.setattr(
        container_disk_check_task, "_handle_hard_limit_with_escalation",
        lambda c, _usage, _cache: calls.append(c.id),
    )
    container_disk_check_task.check_all_containers_disk_usage_once()
    assert calls == []


def test_api_output_uses_only_existing_disk_fields(app, db_session):
    _root, _machine, container = create_container_graph()
    _set_disk(db_session, container)

    response = _build_disk_usage_response(container)
    payload = response["container"]

    assert set(payload) == {
        "overlay_rw_bytes", "bind_mount_bytes", "total_bytes", "bind_mount_path",
    }


def test_no_new_disk_observation_columns(app, db_session):
    columns = {column.name for column in Container.__table__.columns}
    forbidden = {
        "disk_measurement_status", "disk_measured_at", "disk_received_at",
        "disk_observation", "disk_identity_status", "disk_identity_checked_at",
        "disk_identity",
    }

    assert columns.isdisjoint(forbidden)
    assert {
        "disk_overlay_rw_bytes", "disk_bind_mount_bytes", "disk_total_bytes",
        "disk_checked_at", "bind_mount_path",
    } <= columns
