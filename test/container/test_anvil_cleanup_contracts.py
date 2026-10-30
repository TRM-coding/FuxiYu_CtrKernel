"""Anvil cleanup/container contract tests (planned gaps only).

Each test maps to a Scenario in
openspec/changes/complete-anvil-container-cleanup-mappings/test-plan.md.
Only isolated SQLite and external-boundary doubles (Node send, mail, time)
are used; no business service is replaced to fake a result.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError

from ...constant import ContainerStatus, MachineStatus, MachineTypes, ROLE
from ...extensions import db, session_scope
from ...models.container_cleanup_reminder import NEVER_REMINDED, ContainerCleanupReminder
from ...models.container_mount_cleanup import ContainerMountCleanup
from ...models.containers import Container
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...models.operation_log import OperationLog
from ...repositories import (
    auth_repo,
    container_cleanup_reminder_repo,
    container_disk_freeze_state_repo,
    container_mount_cleanup_repo,
    containers_repo,
    deleted_container_restore_snapshot_repo,
    image_repo,
    long_term_container_repo,
    machine_image_repo,
    machine_permission_repo,
)
from ...schedulers import container_disk_check_task
from ...services import container_tasks, settings_tasks
from ...services.container_module import collaborators as collaborator_utils
from ...services.container_module import mount_cleanup as mount_cleanup_mod
from ...services.container_module import node_comms
from ...services.container_module import passwords as password_utils
from ...services.container_module import restore as restore_mod
from ...services.container_module.node_comms_modules import snapshots as disk_snapshots
from ...services.image_tasks import (
    DockerfileParts,
    format_image_build_tag,
    recipe_fingerprint,
    resolve_image_build,
    resolve_image_build_tag,
)
from ...utils.Container import Container_info
from ..factories import (
    bind_user_container,
    create_auth,
    create_container,
    create_container_graph,
    create_machine,
    create_user,
)
from .conftest import NODE_REMOVE_SUCCESS

ANVIL_MOUNT = "/home/anvil/containers/shared_data"
OLD_BODY = "RUN echo old"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _parts(base_image: str = "ubuntu:22.04", body: str | None = None) -> DockerfileParts:
    return DockerfileParts(
        base_image=base_image,
        platform_injection=settings_tasks.get_image_platform_injection_content() or "",
        dockerfile_body=body,
    )


def _set_recipe(container, parts: DockerfileParts) -> None:
    container.base_image = parts.base_image
    container.dockerfile_body = parts.dockerfile_body


def _login(client, user) -> str:
    token = f"anvil-{uuid.uuid4().hex}"
    create_auth(user, token=token)
    client.cookies.set("auth_token", token)
    return token


def _grant(user, *codes: str) -> None:
    name = f"anvil_{uuid.uuid4().hex[:10]}"
    with session_scope() as session:
        group = auth_repo.ensure_group(name, "anvil contract test", session=session)
        for code in codes:
            auth_repo.ensure_group_entity(group.id, code, session=session)
        auth_repo.ensure_user_group(user.id, group.id, session=session)


def _run_now(_name, target, *args):
    target(*args)
    return SimpleNamespace(join=lambda: None)


def _capture_background(monkeypatch, module):
    captured = {}

    def _spawn(name, target, *args):
        captured.update(name=name, target=target, args=args)
        return SimpleNamespace(join=lambda: None)

    monkeypatch.setattr(module, "spawn_background", _spawn)
    return captured


@contextmanager
def _capture_sql(db_session):
    statements = []
    engine = db_session.get_bind()

    def _before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def _dml(statements):
    return [
        s for s in statements
        if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]


def _frame(container, *, status="resolved", path=None, total=100, overlay=40,
           bind=60, measured_at=None, **extra):
    payload = {
        "mount_path_status": status,
        "bind_mount_path": path,
        "total_bytes": total,
        "overlay_rw_bytes": overlay,
        "bind_mount_bytes": bind,
        "measured_at": measured_at,
    }
    payload.update(extra)
    return {"containers": {container.name: payload}}


def _apply_disk(container, machine_id, payload):
    return node_comms.apply_disk_usage_snapshot(payload, machine_id)


def _row(db_session, container_id):
    db_session.expire_all()
    return containers_repo.get_by_id(container_id, session=db_session, include_invalid=True)


def _two_deleted_pair(db_session, mock_node_send, *, prefix="anvil_pair"):
    root = create_user()
    machine = create_machine()
    containers = []
    for index in range(2):
        _r, _m, container = create_container_graph(root_user=root, machine=machine)
        container.name = f"{prefix}_{index}"
        container.bind_mount_path = ANVIL_MOUNT
        container.image_id = 1
        container.last_build_at = dt.datetime(2020, 1, 1)
        _set_recipe(container, _parts(body=OLD_BODY))
        db_session.commit()
        containers.append(container)
    sent = mock_node_send({"success": 1})
    for container in containers:
        assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    db_session.expire_all()
    snapshots = list(db_session.scalars(
        select(DeletedContainerRestoreSnapshot).order_by(DeletedContainerRestoreSnapshot.id)
    ).all())
    assert len(snapshots) == 2
    return root, machine, [row.id for row in snapshots]


def _deleted_behind(db_session, mock_node_send, name="anvil_behind"):
    root, machine, container = create_container_graph()
    container.name = name
    container.bind_mount_path = f"/home/{root.username}/containers/{name}_data"
    container.image_id = 1
    container.last_build_at = dt.datetime(2020, 1, 1)
    _set_recipe(container, _parts(body=OLD_BODY))
    db_session.commit()
    sent = mock_node_send({"success": 1})
    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()
    return root, machine, container, snapshot, sent


# ---------------------------------------------------------------------------
# containers: persistence, schema, create limits, wire
# ---------------------------------------------------------------------------

def test_anvil_c01_container_readback_and_defaults(db_session):
    machine = create_machine()
    container = create_container(machine=machine, name=f"anvil_read_{uuid.uuid4().hex[:8]}")
    db_session.commit()

    with session_scope(commit=False) as session:
        row = containers_repo.get_by_id(container.id, session=session)
        assert row is not None
        assert isinstance(row.id, int)
        assert isinstance(row.name, str)
        assert isinstance(row.port, int)
        assert row.is_valid is True
        assert row.container_status == ContainerStatus.ONLINE
        assert row.created_at is None
        assert row.image_id is None
        assert row.disk_total_bytes is None
        assert row.bind_mount_path is None

    # Database server_default, not just the ORM Python default.
    raw_name = f"anvil_raw_{uuid.uuid4().hex[:8]}"
    db_session.execute(text(
        "INSERT INTO containers "
        "(name, machine_id, container_status, port, memory_gb, shared_gb, gpu_number, cpu_number) "
        "VALUES (:name, :mid, 'online', :port, 1, 0, 0, 1)"
    ), {"name": raw_name, "mid": machine.id, "port": 26000})
    db_session.commit()
    raw_valid = db_session.execute(
        text("SELECT is_valid FROM containers WHERE name = :name"), {"name": raw_name}
    ).scalar_one()
    assert bool(raw_valid) is True


def test_anvil_c29_disk_facts_use_only_container_columns(db_session):
    columns = {column.name for column in Container.__table__.columns}
    assert {
        "disk_overlay_rw_bytes", "disk_bind_mount_bytes", "disk_total_bytes",
        "disk_checked_at", "bind_mount_path",
    } <= columns
    assert not {
        "disk_measurement_status", "disk_measured_at", "disk_received_at",
        "disk_observation", "disk_identity_status", "disk_identity_checked_at",
        "disk_identity",
    } & columns
    assert not {name for name in columns if name.startswith("disk_")} - {
        "disk_overlay_rw_bytes", "disk_bind_mount_bytes", "disk_total_bytes", "disk_checked_at",
    }
    forbidden_tables = {
        name for name in Container.metadata.tables
        if "usage" in name.lower() or "observation" in name.lower()
    }
    assert forbidden_tables == set()


def test_anvil_c30_rendered_dockerfile_and_injection_not_persisted(db_session):
    columns = {column.name for column in Container.__table__.columns}
    assert {"base_image", "dockerfile_body", "entrypoint"} <= columns
    forbidden = {
        "dockerfile_text", "rendered_dockerfile", "platform_injection",
        "image_platform_injection", "dockerfile",
    }
    assert not forbidden & columns


def test_anvil_c02_create_resource_limits_report_specific_values(
    db_session, monkeypatch, mock_node_send,
):
    owner = create_user()
    machine = create_machine(
        machine_type=MachineTypes.GPU,
        gpu_number=4,
        gpu_allow_list=[0, 1],
        max_cpu_core_number=2,
        max_memory_gb=16,
        max_shared_gb=8,
    )
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()

    calls = mock_node_send({"success": 1})
    gpu_info = Container_info(
        gpu_list=[0, 1, 2], cpu_number=1, memory=1, shared_memory=0,
        name=f"anvil_gpu_{uuid.uuid4().hex[:6]}", image="ubuntu:22.04",
    )
    with pytest.raises(container_tasks.NodeServiceError) as gpu_exc:
        container_tasks.Create_container(owner.id, machine.id, gpu_info)
    assert gpu_exc.value.reason == "invalid_config"
    assert "3" in str(gpu_exc.value) and "2" in str(gpu_exc.value)
    assert calls == []

    cpu_info = Container_info(
        gpu_list=[], cpu_number=3, memory=1, shared_memory=0,
        name=f"anvil_cpu_{uuid.uuid4().hex[:6]}", image="ubuntu:22.04",
    )
    with pytest.raises(container_tasks.NodeServiceError) as cpu_exc:
        container_tasks.Create_container(owner.id, machine.id, cpu_info)
    assert cpu_exc.value.reason == "invalid_config"
    assert "3" in str(cpu_exc.value) and "2" in str(cpu_exc.value)
    assert calls == []


def test_anvil_c39_create_wire_config_image_uses_platform_tag(
    client, monkeypatch, db_session, mock_node_send,
):
    owner = create_user(operator=True)
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    _login(client, owner)
    build = resolve_image_build(1, machine.id)
    assert build is not None
    calls = mock_node_send({"success": 1})

    resp = client.post(
        "/api/containers/create_container",
        json={
            "owner_user_id": owner.id,
            "machine_id": machine.id,
            "image_id": 1,
            "container": {
                "NAME": f"anvil_wire_{uuid.uuid4().hex[:6]}",
                "CPU_NUMBER": 1,
                "MEMORY": 1,
                "image": "evil:1.0",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    create = next(call for call in calls if call["url"].endswith("/create_container"))
    assert create["payload"]["config"]["image"] == build.payload["image_tag"]
    assert "evil" not in create["payload"]["config"]["image"]


# ---------------------------------------------------------------------------
# containers: image/restore/build
# ---------------------------------------------------------------------------

def test_anvil_c03_restore_ignores_client_image_name(
    client, db_session, mock_node_send,
):
    root, machine, container = create_container_graph()
    operator = create_user(operator=True)
    container.name = f"anvil_restore_name_{uuid.uuid4().hex[:6]}"
    container.bind_mount_path = f"/home/{root.username}/containers/{container.name}_data"
    container.image_id = 1
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    _set_recipe(container, resolve_image_build(1).dockerfile_parts)
    db_session.commit()
    mock_node_send(NODE_REMOVE_SUCCESS)
    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()
    _login(client, operator)
    calls = mock_node_send({"success": 1})

    resp = client.post(
        "/api/containers/resurrect_container",
        json={"deleted_id": snapshot.id, "content_source": "snapshot", "image": "evil:1.0"},
    )
    assert resp.status_code == 200, resp.text
    create = next(call for call in calls if call["url"].endswith("/create_container"))
    # Restore persists a new build stamp; the pre-request ORM object can be stale.
    with session_scope(commit=False) as session:
        restored = containers_repo.get_by_id(container.id, session=session)
        assert restored is not None
        assert restored.image_id == 1
        expected_tag = image_repo_image_tag(restored)
    assert create["payload"]["config"]["image"] == expected_tag
    assert "evil" not in create["payload"]["config"]["image"]


def image_repo_image_tag(container) -> str:
    return format_image_build_tag(container.image_id, container.last_build_at)


def test_anvil_c04_future_stamp_recipe_change_still_marks_choice(db_session):
    from ...services.container_module.restore import _RestoreTarget, _resolve_restore_image

    machine = create_machine()
    old_parts = _parts(base_image="ubuntu:22.04", body=OLD_BODY)
    image_repo.update_image(1, dockerfile_body="RUN echo new", session=db_session)
    db_session.commit()
    target = _RestoreTarget(
        snapshot={"container_name": "future"},
        container_id=1,
        machine_id=machine.id,
        mount_path=ANVIL_MOUNT,
        mount_cleanup_id=None,
        removed_at=dt.datetime.utcnow(),
        image_id=1,
        image_version_at=dt.datetime(2999, 1, 1),
        dockerfile_parts=old_parts,
    )
    resolved = _resolve_restore_image(target)
    assert resolved.needs_choice is True
    assert resolved.mode == "snapshot"


def test_anvil_c05_restore_source_uses_current_injection_and_refreshes_stamp(
    db_session, mock_node_send,
):
    root, _machine, snapshot_ids = _two_deleted_pair(db_session, mock_node_send, prefix="anvil_c05")
    image_repo.update_image(
        1, base_image="ubuntu:24.04", dockerfile_body="RUN echo new", session=db_session,
    )
    settings_tasks.set_setting_value(
        settings_tasks.IMAGE_PLATFORM_INJECTION_KEY, "RUN echo INJ_V2",
    )
    db_session.commit()
    sent = mock_node_send({"success": 1})

    first = container_tasks.resurrect_container(
        snapshot_ids[0], operator_user_id=root.id, content_source="snapshot",
    )
    second = container_tasks.resurrect_container(
        snapshot_ids[1], operator_user_id=root.id, content_source="template",
    )
    creates = [call for call in sent if call["url"].endswith("/create_container")]
    assert len(creates) == 2
    snapshot_text = creates[0]["payload"]["image_build"]["dockerfile_text"]
    template_text = creates[1]["payload"]["image_build"]["dockerfile_text"]
    assert OLD_BODY in snapshot_text and "INJ_V2" in snapshot_text
    assert "FROM ubuntu:24.04" in template_text and "INJ_V2" in template_text
    for result, call in zip((first, second), creates):
        db_session.expire_all()
        restored = containers_repo.get_by_id(result["container_id"], session=db_session)
        assert restored.last_build_at is not None
        assert format_image_build_tag(restored.image_id, restored.last_build_at) == (
            call["payload"]["image_build"]["image_tag"]
        )


def test_anvil_c06_restore_mount_same_path_across_sources(db_session, mock_node_send):
    root, _machine, snapshot_ids = _two_deleted_pair(db_session, mock_node_send, prefix="anvil_c06")
    sent = mock_node_send({"success": 1})
    container_tasks.resurrect_container(
        snapshot_ids[0], operator_user_id=root.id, content_source="snapshot",
    )
    container_tasks.resurrect_container(
        snapshot_ids[1], operator_user_id=root.id, content_source="template",
    )
    creates = [call for call in sent if call["url"].endswith("/create_container")]
    assert len(creates) == 2
    assert {call["payload"]["restore_mount_path"] for call in creates} == {ANVIL_MOUNT}


def test_anvil_c07_old_container_version_survives_new_cache_dispatch(db_session):
    machine = create_machine()
    container = create_container(machine=machine, name=f"anvil_old_{uuid.uuid4().hex[:6]}", image_id=1)
    container.last_build_at = dt.datetime(2020, 1, 1)
    old_parts = _parts(base_image="ubuntu:22.04", body=OLD_BODY)
    _set_recipe(container, old_parts)
    db_session.commit()
    old_tag = format_image_build_tag(container.image_id, container.last_build_at)

    new_version = dt.datetime(2026, 10, 28, 12, 0, 0)
    new_tag = format_image_build_tag(1, new_version)
    machine_image_repo.record_dispatch(
        machine.id, 1, new_tag, new_version, recipe_fingerprint(_parts(
            base_image="ubuntu:24.04", body="RUN echo new",
        )), session=db_session,
    )
    db_session.commit()
    db_session.expire_all()
    current = containers_repo.get_by_id(container.id, session=db_session)
    assert current.image_id == 1
    assert current.last_build_at == dt.datetime(2020, 1, 1)
    assert (current.base_image, current.dockerfile_body) == ("ubuntu:22.04", OLD_BODY)
    assert format_image_build_tag(current.image_id, current.last_build_at) == old_tag
    assert old_tag != new_tag


# ---------------------------------------------------------------------------
# containers: password create/restore
# ---------------------------------------------------------------------------

def test_anvil_c14_create_password_absent_and_message_preserved(
    client, db_session, mock_node_send,
):
    owner = create_user(operator=True)
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    _login(client, owner)
    calls = mock_node_send({"success": 1})
    name = f"anvil_pwd_{uuid.uuid4().hex[:6]}"
    resp = client.post(
        "/api/containers/create_container",
        json={
            "owner_user_id": owner.id,
            "machine_id": machine.id,
            "image_id": 1,
            "container": {"NAME": name, "CPU_NUMBER": 1, "MEMORY": 1},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    password = body["credentials"][0]["password"]
    assert body["message"] == "Create container request sent"
    assert calls[0]["payload"]["root_password"] == password

    db_session.expire_all()
    row = db_session.scalars(select(Container).where(Container.name == name)).one()
    assert password not in json.dumps({
        column.name: str(getattr(row, column.name)) for column in Container.__table__.columns
    }, ensure_ascii=False)
    logs = list(db_session.scalars(select(OperationLog)).all())
    assert all(password not in f"{log.detail}|{log.error_reason}" for log in logs)


def test_anvil_c15_create_failure_sends_password_but_redacts(
    db_session, mock_node_send,
):
    owner = create_user()
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    info = Container_info(
        gpu_list=[], cpu_number=1, memory=1, shared_memory=0,
        name=f"anvil_fail_{uuid.uuid4().hex[:6]}", image="ubuntu:22.04",
    )
    calls = mock_node_send({"success": 0, "error": "node boom", "error_reason": "create_failed"})
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.Create_container(owner.id, machine.id, info)
    password = calls[0]["payload"]["root_password"]
    assert password
    assert password not in str(excinfo.value)
    assert password not in str(excinfo.value.reason)
    assert db_session.scalars(
        select(Container).where(Container.name == info.NAME)
    ).first() is None


def test_anvil_c16_restore_password_differs_from_creation(
    client, db_session, mock_node_send,
):
    owner = create_user(operator=True)
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    _login(client, owner)
    name = f"anvil_repwd_{uuid.uuid4().hex[:6]}"
    create_calls = mock_node_send({"success": 1})
    resp = client.post(
        "/api/containers/create_container",
        json={
            "owner_user_id": owner.id,
            "machine_id": machine.id,
            "image_id": 1,
            "container": {"NAME": name, "CPU_NUMBER": 1, "MEMORY": 1},
        },
    )
    assert resp.status_code == 200, resp.text
    old_password = resp.json()["credentials"][0]["password"]
    db_session.expire_all()
    container = db_session.scalars(select(Container).where(Container.name == name)).one()
    container.container_status = ContainerStatus.ONLINE
    container.bind_mount_path = f"/home/{owner.username}/containers/{name}_data"
    db_session.commit()
    assert container_tasks.remove_container(container.id, operator_user_id=owner.id) is True
    db_session.expire_all()
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()

    restore_calls = mock_node_send({"success": 1})
    result = container_tasks.resurrect_container(
        snapshot.id, operator_user_id=owner.id, content_source="snapshot",
    )
    new_password = result["root_password"]
    assert new_password and new_password != old_password
    create = next(call for call in restore_calls if call["url"].endswith("/create_container"))
    assert create["payload"]["root_password"] == new_password


def test_anvil_c17_requires_choice_no_password_delivery(
    db_session, mock_node_send,
):
    root, _machine, _container, snapshot, _sent = _deleted_behind(
        db_session, mock_node_send, name=f"anvil_choice_{uuid.uuid4().hex[:6]}",
    )
    image_repo.update_image(1, dockerfile_body="RUN echo new", session=db_session)
    db_session.commit()
    calls = mock_node_send({"success": 1})
    result = container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)
    assert result["requires_choice"] is True
    assert result.get("container_id") is None
    assert "root_password" not in result
    assert "credentials" not in result
    assert not [call for call in calls if call["url"].endswith("/create_container")]

# ---------------------------------------------------------------------------
# containers: reset / add collaborator
# ---------------------------------------------------------------------------

def test_anvil_c18_reset_allows_container_manage_and_bypass_resource(
    client, db_session, monkeypatch, mock_node_send,
):
    _root, machine, container = create_container_graph()
    target = create_user(username=f"anvil_target_{uuid.uuid4().hex[:6]}")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    db_session.commit()
    monkeypatch.setattr(password_utils, "spawn_background", _run_now)
    calls = mock_node_send({"success": 1})

    for codes in (("container:manage",), ("container:operation", "bypass_resource")):
        caller = create_user()
        _grant(caller, *codes)
        machine_permission_repo.add_permission(machine.id, caller.id, session=db_session)
        db_session.commit()
        _login(client, caller)
        resp = client.post(
            "/api/containers/reset_container_password",
            json={"container_id": container.id, "user_id": target.id},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["accepted"] is True
        assert body["credentials"][0]["login_name"] == target.username
        assert body["credentials"][0]["password"]
    assert len(calls) == 2
    assert all(call["url"].endswith("/reset_container_password") for call in calls)


def test_anvil_c19_reset_rejects_admin_and_collaborator_bindings(
    client, db_session, monkeypatch, mock_node_send,
):
    root, machine, container = create_container_graph()
    admin = create_user(username=f"anvil_admin_{uuid.uuid4().hex[:6]}")
    collaborator = create_user(username=f"anvil_collab_{uuid.uuid4().hex[:6]}")
    bind_user_container(admin, container, role=ROLE.ADMIN, username=admin.username)
    bind_user_container(collaborator, container, role=ROLE.COLLABORATOR, username=collaborator.username)
    for user in (admin, collaborator):
        machine_permission_repo.add_permission(machine.id, user.id, session=db_session)
    db_session.commit()
    calls = mock_node_send({"success": 1})
    monkeypatch.setattr(
        password_utils, "generate_container_password",
        lambda: (_ for _ in ()).throw(AssertionError("password must not be generated")),
    )
    for user in (admin, collaborator):
        _login(client, user)
        resp = client.post(
            "/api/containers/reset_container_password",
            json={"container_id": container.id, "user_id": user.id},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error_reason"] == "resource_access_denied"
    assert calls == []


def test_anvil_c20_reset_rejects_empty_and_illegal_usernames(
    db_session, monkeypatch, mock_node_send,
):
    root, machine, container = create_container_graph()
    monkeypatch.setattr(
        password_utils, "generate_container_password",
        lambda: (_ for _ in ()).throw(AssertionError("password must not be generated")),
    )
    calls = mock_node_send({"success": 1})
    from ...repositories import usercontainer_repo
    for username in ("", "root", "bad name", "bad;name"):
        target = create_user(username=f"anvil_bad_{uuid.uuid4().hex[:6]}")
        bind_user_container(
            target, container, role=ROLE.COLLABORATOR,
            username=username or f"placeholder_{uuid.uuid4().hex[:6]}",
        )
        if username == "":
            usercontainer_repo.update_binding(
                target.id, container.id, username="", session=db_session,
            )
        db_session.commit()
        with pytest.raises(container_tasks.NodeServiceError) as excinfo:
            container_tasks.start_reset_container_password(container.id, target.id, root.id)
        assert excinfo.value.reason == "invalid_target_account"
    assert calls == []


def test_anvil_c21_reset_rejects_paused_failed_and_transition_states(
    db_session, monkeypatch, mock_node_send,
):
    root, machine, container = create_container_graph()
    target = create_user(username=f"anvil_status_{uuid.uuid4().hex[:6]}")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    db_session.commit()
    monkeypatch.setattr(
        password_utils, "generate_container_password",
        lambda: (_ for _ in ()).throw(AssertionError("password must not be generated")),
    )
    calls = mock_node_send({"success": 1})
    cases = (
        (ContainerStatus.PAUSED, "container_offline"),
        (ContainerStatus.FAILED, "container_offline"),
        (ContainerStatus.STARTING, "container_busy"),
    )
    for status, reason in cases:
        container.container_status = status
        db_session.commit()
        with pytest.raises(container_tasks.NodeServiceError) as excinfo:
            container_tasks.start_reset_container_password(container.id, target.id, root.id)
        assert excinfo.value.reason == reason
    assert calls == []


def test_anvil_c22_reset_failure_writes_only_failed_oplog(
    db_session, monkeypatch, mock_node_send,
):
    root, _machine, container = create_container_graph()
    target = create_user(username=f"anvil_reset_fail_{uuid.uuid4().hex[:6]}")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    db_session.commit()
    monkeypatch.setattr(password_utils, "spawn_background", _run_now)
    mock_node_send({"success": 0, "error": "boom", "error_reason": "reset_failed"})
    result = container_tasks.start_reset_container_password(container.id, target.id, root.id)
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password")
    ).all())
    assert logs
    assert all(log.success is False for log in logs)
    assert all(result["password"] not in str(log.detail) for log in logs)


def _deleted_with_collaborator(db_session, mock_node_send, name):
    collaborator = create_user(username=f"alice_{uuid.uuid4().hex[:6]}")
    root, _machine, container = create_container_graph(
        collaborator_user=collaborator, collaborator_username=collaborator.username,
    )
    container.name = name
    container.bind_mount_path = f"/home/{root.username}/containers/{name}_data"
    container.image_id = 1
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    _set_recipe(container, resolve_image_build(1).dockerfile_parts)
    db_session.commit()
    mock_node_send(NODE_REMOVE_SUCCESS)
    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()
    return root, container, collaborator, snapshot


def test_anvil_c23_add_admin_binding_and_no_success_on_failure(
    db_session, monkeypatch, mock_node_send,
):
    root, _machine, container = create_container_graph()
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)
    calls = mock_node_send({"success": 1})
    admin = create_user(username=f"anvil_add_admin_{uuid.uuid4().hex[:6]}")
    result = container_tasks.start_add_collaborator(container.id, admin.id, ROLE.ADMIN, root.id)
    assert result["login_name"] == admin.username
    assert calls[0]["payload"]["config"]["password"] == result["password"]
    db_session.expire_all()
    from ...repositories import usercontainer_repo
    binding = usercontainer_repo.get_binding(admin.id, container.id, session=db_session)
    assert getattr(binding["role"], "value", binding["role"]) == ROLE.ADMIN.value
    success = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "add_collaborator", OperationLog.success.is_(True))
    ).all())
    assert len(success) == 1
    assert result["password"] not in str(success[0].detail)

    failed_user = create_user(username=f"anvil_add_fail_{uuid.uuid4().hex[:6]}")
    mock_node_send({"success": 0, "error_reason": "add_failed"})
    failed = container_tasks.start_add_collaborator(container.id, failed_user.id, ROLE.COLLABORATOR, root.id)
    db_session.expire_all()
    assert usercontainer_repo.get_binding(failed_user.id, container.id, session=db_session) is None
    failed_logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "add_collaborator", OperationLog.success.is_(False))
    ).all())
    assert failed_logs
    assert all(failed["password"] not in str(log.detail) for log in failed_logs)
    success_logs = list(db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == "add_collaborator",
            OperationLog.success.is_(True),
            OperationLog.target_id == container.id,
        )
    ).all())
    for log in success_logs:
        detail = log.detail if isinstance(log.detail, dict) else json.loads(log.detail)
        assert detail.get("user_id") != failed_user.id


def test_anvil_c24_add_precheck_no_password_delivery(
    db_session, monkeypatch, mock_node_send,
):
    root, _machine, container = create_container_graph()
    target = create_user(username=f"anvil_pre_{uuid.uuid4().hex[:6]}")
    container.container_status = ContainerStatus.OFFLINE
    db_session.commit()
    calls = mock_node_send({"success": 1})
    monkeypatch.setattr(
        collaborator_utils, "generate_container_password",
        lambda: (_ for _ in ()).throw(AssertionError("password must not be generated")),
    )
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.start_add_collaborator(container.id, target.id, ROLE.COLLABORATOR, root.id)
    assert excinfo.value.reason == "container_offline"
    assert calls == []


def test_anvil_c25_add_background_guard_failure_writes_only_failed_oplog(
    db_session, monkeypatch, mock_node_send,
):
    root, _machine, container = create_container_graph()
    target = create_user(username=f"anvil_guard_{uuid.uuid4().hex[:6]}")
    captured = _capture_background(monkeypatch, collaborator_utils)
    calls = mock_node_send({"success": 1})
    result = container_tasks.start_add_collaborator(container.id, target.id, ROLE.COLLABORATOR, root.id)
    container.container_status = ContainerStatus.OFFLINE
    db_session.commit()
    captured["target"](*captured["args"])
    assert calls == []
    from ...repositories import usercontainer_repo
    assert usercontainer_repo.get_binding(target.id, container.id, session=db_session) is None
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "add_collaborator")
    ).all())
    assert logs
    assert all(log.success is False for log in logs)
    assert all(result["password"] not in str(log.detail) for log in logs)


def test_anvil_c31_add_collaborator_survives_response_disconnect(
    db_session, monkeypatch, mock_node_send,
):
    root, _machine, container = create_container_graph()
    target = create_user(username=f"anvil_disc_{uuid.uuid4().hex[:6]}")
    captured = _capture_background(monkeypatch, collaborator_utils)
    calls = mock_node_send({"success": 1})
    result = container_tasks.start_add_collaborator(container.id, target.id, ROLE.COLLABORATOR, root.id)
    assert result["password"]
    assert calls == []
    # Simulated disconnect: run the accepted background target after the response.
    captured["target"](*captured["args"])
    assert calls and calls[0]["url"].endswith("/add_collaborator")
    from ...repositories import usercontainer_repo
    assert usercontainer_repo.get_binding(target.id, container.id, session=db_session) is not None


def test_anvil_c35_reset_rejections_do_not_deliver_credentials_or_call_node(
    client, db_session, monkeypatch, mock_node_send,
):
    calls = mock_node_send({"success": 1})
    monkeypatch.setattr(
        password_utils, "generate_container_password",
        lambda: (_ for _ in ()).throw(AssertionError("password must not be generated")),
    )

    # bypass_auth_entity only: method passes, resource layer rejects.
    _root, machine_a, container_a = create_container_graph()
    caller = create_user()
    _grant(caller, "bypass_auth_entity")
    machine_permission_repo.add_permission(machine_a.id, caller.id, session=db_session)
    db_session.commit()
    _login(client, caller)
    resp = client.post(
        "/api/containers/reset_container_password",
        json={"container_id": container_a.id, "user_id": caller.id},
    )
    assert resp.status_code == 403
    assert resp.json()["error_reason"] == "resource_access_denied"
    assert "credentials" not in resp.json()

    # target_not_bound
    root, machine_b, container_b = create_container_graph()
    target_unbound = create_user(username=f"anvil_unbound_{uuid.uuid4().hex[:6]}")
    machine_permission_repo.add_permission(machine_b.id, target_unbound.id, session=db_session)
    db_session.commit()
    _login(client, root)
    resp = client.post(
        "/api/containers/reset_container_password",
        json={"container_id": container_b.id, "user_id": target_unbound.id},
    )
    assert resp.status_code == 409
    assert resp.json()["error_reason"] == "target_not_bound"
    assert "credentials" not in resp.json()

    # extra field
    resp = client.post(
        "/api/containers/reset_container_password",
        json={"container_id": container_b.id, "user_id": root.id, "login_name": "x"},
    )
    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_payload"
    assert "credentials" not in resp.json()

    # machine_offline
    target_bound = create_user(username=f"anvil_offline_{uuid.uuid4().hex[:6]}")
    bind_user_container(target_bound, container_b, role=ROLE.COLLABORATOR, username=target_bound.username)
    machine_b.machine_status = MachineStatus.OFFLINE
    db_session.commit()
    resp = client.post(
        "/api/containers/reset_container_password",
        json={"container_id": container_b.id, "user_id": target_bound.id},
    )
    assert resp.status_code in (409, 503)
    assert resp.json()["error_reason"] == "machine_offline"
    assert "credentials" not in resp.json()
    assert calls == []


# ---------------------------------------------------------------------------
# containers: detail read-only, paths and disk rejects
# ---------------------------------------------------------------------------

def test_anvil_c13_detail_non_null_bind_path_readonly_without_node(
    db_session, monkeypatch,
):
    machine = create_machine()
    container = create_container(machine=machine, name=f"anvil_detail_{uuid.uuid4().hex[:6]}")
    container.bind_mount_path = "/home/anvil/containers/detail_data"
    db_session.commit()
    monkeypatch.setattr(
        node_comms, "send",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("detail must not contact Node")),
    )
    with _capture_sql(db_session) as statements:
        info = container_tasks.get_container_detail_information(container.id)
    assert info["bind_mount_path"] == "/home/anvil/containers/detail_data"
    assert _dml(statements) == []


def test_anvil_c08_path_correction_does_not_rewrite_history(db_session):
    machine = create_machine()
    container = create_container(machine=machine, name=f"anvil_hist_{uuid.uuid4().hex[:6]}")
    container.bind_mount_path = "/home/anvil/containers/old_data"
    db_session.commit()
    cleanup = container_mount_cleanup_repo.insert(
        container.id, container.name, machine.id, "/home/anvil/containers/old_data",
        session=db_session,
    )
    snapshot = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": container.id,
            "container_name": container.name,
            "machine_id": machine.id,
            "bind_mount_path": "/home/anvil/containers/old_data",
        },
        session=db_session,
        mount_cleanup_id=cleanup.id,
    )
    other_machine = create_machine()
    other = create_container(machine=other_machine, name=f"anvil_other_{uuid.uuid4().hex[:6]}")
    other.bind_mount_path = "/home/anvil/containers/old_data"
    db_session.commit()

    result = _apply_disk(container, machine.id, _frame(
        container, status="resolved", path="/home/anvil/containers/new_data",
        total=300, overlay=100, bind=200,
        measured_at=dt.datetime.utcnow().replace(microsecond=0).isoformat(),
    ))
    assert result == {"updated": 1, "skipped": 0}
    db_session.expire_all()
    assert containers_repo.get_by_id(container.id, session=db_session).bind_mount_path == (
        "/home/anvil/containers/new_data"
    )
    assert deleted_container_restore_snapshot_repo.get_by_id(snapshot.id, session=db_session).snapshot[
        "bind_mount_path"
    ] == "/home/anvil/containers/old_data"
    assert container_mount_cleanup_repo.get_by_id(cleanup.id, session=db_session).mount_path == (
        "/home/anvil/containers/old_data"
    )
    assert containers_repo.get_by_id(other.id, session=db_session).bind_mount_path == (
        "/home/anvil/containers/old_data"
    )


def test_anvil_c09_repeated_frame_same_timestamp_conflicting_path_rejected(db_session):
    machine = create_machine()
    container = create_container(machine=machine, name=f"anvil_conflict_{uuid.uuid4().hex[:6]}")
    measured = dt.datetime.utcnow().replace(microsecond=0)
    container.bind_mount_path = "/home/anvil/containers/a"
    container.disk_total_bytes = 33
    container.disk_checked_at = measured
    db_session.commit()
    result = _apply_disk(container, machine.id, _frame(
        container, status="resolved", path="/home/anvil/containers/b",
        total=999, overlay=333, bind=666, measured_at=measured.isoformat(),
    ))
    db_session.expire_all()
    row = containers_repo.get_by_id(container.id, session=db_session)
    assert result == {"updated": 0, "skipped": 1}
    assert row.bind_mount_path == "/home/anvil/containers/a"
    assert row.disk_total_bytes == 33
    assert row.disk_checked_at == measured


def test_anvil_c10_unresolved_fresh_measurement_reaches_evaluation(db_session):
    machine = create_machine()
    container = create_container(machine=machine, name=f"anvil_unres_{uuid.uuid4().hex[:6]}")
    container.bind_mount_path = "/home/anvil/containers/a"
    db_session.commit()
    _apply_disk(container, machine.id, _frame(
        container, status="unresolved", path=container.bind_mount_path,
        total=900, overlay=300, bind=600,
        measured_at=dt.datetime.utcnow().replace(microsecond=0).isoformat(),
    ))
    db_session.expire_all()
    row = containers_repo.get_by_id(container.id, session=db_session)
    assert container_disk_check_task._usage_from_db(row) is not None


def test_anvil_c11_resolved_failed_measurement_does_not_drive_scheduler(
    db_session, monkeypatch,
):
    machine = create_machine(max_disk_size_gb=1)
    container = create_container(machine=machine, name=f"anvil_failed_{uuid.uuid4().hex[:6]}")
    container.bind_mount_path = "/home/anvil/containers/a"
    container.disk_total_bytes = 2 * 1024**3
    container.disk_overlay_rw_bytes = 2 * 1024**3
    container.disk_checked_at = dt.datetime.utcnow() - dt.timedelta(hours=2)
    long_term_container_repo.add(container.id, session=db_session)
    db_session.commit()
    _apply_disk(container, machine.id, _frame(
        container, status="resolved", path=container.bind_mount_path,
        total=999, overlay=999, bind=0, measured_at="not-a-time",
    ))
    db_session.expire_all()
    row = containers_repo.get_by_id(container.id, session=db_session)
    assert row.disk_total_bytes == 2 * 1024**3
    assert row.disk_checked_at is not None
    monkeypatch.setattr(container_disk_check_task, "machine_in_scope", lambda _id: True)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_check_enabled", lambda: True)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_response_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(
        container_disk_check_task, "_handle_hard_limit_with_escalation",
        lambda c, _usage, _cache: calls.append(c.id),
    )
    container_disk_check_task.check_all_containers_disk_usage_once()
    assert calls == []
    assert container_disk_freeze_state_repo.get(container.id, session=db_session) is None


def test_anvil_c12_path_correction_does_not_authorize_remove_or_cleanup(
    db_session, monkeypatch,
):
    machine = create_machine()
    container = create_container(machine=machine, name=f"anvil_auth_{uuid.uuid4().hex[:6]}")
    container.bind_mount_path = "/home/anvil/containers/a"
    db_session.commit()
    calls = []
    monkeypatch.setattr(node_comms, "send", lambda *a, **k: calls.append((a, k)) or {"success": 1})
    _apply_disk(container, machine.id, _frame(
        container, status="resolved", path="/home/anvil/containers/b",
        total=100, overlay=40, bind=60,
        measured_at=dt.datetime.utcnow().replace(microsecond=0).isoformat(),
    ))
    db_session.expire_all()
    row = containers_repo.get_by_id(container.id, session=db_session)
    assert row.is_valid is True
    assert calls == []
    assert db_session.scalars(select(ContainerMountCleanup)).all() == []
    assert db_session.scalars(select(DeletedContainerRestoreSnapshot)).all() == []

def test_anvil_c26_restore_account_password_not_persisted(
    db_session, mock_node_send,
):
    root, _container, collaborator, snapshot = _deleted_with_collaborator(
        db_session, mock_node_send, f"anvil_c26_{uuid.uuid4().hex[:6]}",
    )
    snapshot_json = json.dumps(snapshot.snapshot, ensure_ascii=False, default=str)
    assert "password" not in snapshot_json
    sent = mock_node_send({"success": 1})
    result = container_tasks.resurrect_container(
        snapshot.id, operator_user_id=root.id, content_source="snapshot",
    )
    create = next(call for call in sent if call["url"].endswith("/create_container"))
    accounts = create["payload"]["restore_accounts"]
    password = accounts[0]["password"]
    assert password and password != f"{collaborator.username}123"
    assert password not in json.dumps(result, ensure_ascii=False, default=str)
    db_session.expire_all()
    logs = list(db_session.scalars(select(OperationLog)).all())
    assert all(password not in str(log.detail) for log in logs)
    from ...repositories import usercontainer_repo
    for binding in usercontainer_repo.get_container_bindings(result["container_id"], session=db_session):
        for column in binding:
            assert password not in str(binding[column])


def test_anvil_c27_restore_account_failure_no_retry_or_credentials(
    db_session, mock_node_send,
):
    root, _container, collaborator, snapshot = _deleted_with_collaborator(
        db_session, mock_node_send, f"anvil_c27_{uuid.uuid4().hex[:6]}",
    )
    sent = mock_node_send({"success": 0, "error": "node boom", "error_reason": "restore_failed"})
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.resurrect_container(
            snapshot.id, operator_user_id=root.id, content_source="snapshot",
        )
    assert len(sent) == 1
    password = sent[0]["payload"]["restore_accounts"][0]["password"]
    assert password and password != f"{collaborator.username}123"
    assert password not in str(excinfo.value)
    assert "credentials" not in str(excinfo.value)


def test_anvil_c28_detail_and_list_do_not_return_password(
    client, db_session,
):
    root, machine, container = create_container_graph()
    operator = create_user(operator=True)
    machine_permission_repo.add_permission(machine.id, operator.id, session=db_session)
    container.bind_mount_path = "/home/anvil/containers/c28_data"
    db_session.commit()
    _login(client, operator)
    detail = client.post(
        "/api/containers/get_container_detail_information",
        json={"container_id": container.id},
    )
    assert detail.status_code == 200, detail.text
    listed = client.post(
        "/api/containers/list_all_container_bref_information",
        json={"page_number": 1, "page_size": 10, "machine_id": machine.id},
    )
    assert listed.status_code == 200, listed.text
    assert "password" not in json.dumps(detail.json(), ensure_ascii=False).lower()
    assert "password" not in json.dumps(listed.json(), ensure_ascii=False).lower()


def test_anvil_c32_password_not_in_wire_env_labels_or_wss(
    client, db_session, monkeypatch, mock_node_send,
):
    owner = create_user(operator=True)
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    _login(client, owner)
    calls = mock_node_send({"success": 1})
    name = f"anvil_c32_{uuid.uuid4().hex[:6]}"
    resp = client.post(
        "/api/containers/create_container",
        json={
            "owner_user_id": owner.id, "machine_id": machine.id, "image_id": 1,
            "container": {"NAME": name, "CPU_NUMBER": 1, "MEMORY": 1},
        },
    )
    assert resp.status_code == 200, resp.text
    create = calls[0]["payload"]
    assert create["root_password"]
    assert "password" not in create["config"].get("env", {})
    assert "password" not in create["config"].get("labels", {})
    assert "root_password" not in create["config"]

    node_comms.clear_runtime_buffers()
    assert node_comms.get_cached_machine_runtime_snapshot(machine.id) is None
    assert node_comms.get_cached_container_runtime_metrics(machine.id, name) is None

    # WSS payloads from the real Node probe must not contain password material.
    payloads = _node_protocol_payloads()
    assert "password" not in json.dumps(payloads, ensure_ascii=False).lower()


def _node_protocol_payloads():
    node_root = Path(__file__).resolve().parents[3] / "FuxiYu_NodeKernel"
    if not node_root.is_dir():
        pytest.skip("FuxiYu_NodeKernel is not available")
    probe = Path(__file__).with_name("_node_protocol_probe.py")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(node_root.parent), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("DATABASE_URL", None)
    proc = subprocess.run(
        [sys.executable, str(probe)], cwd=str(node_root.parent), env=env,
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        pytest.fail(f"Node payload probe failed: {proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout)


def test_anvil_c33_starting_transition_snapshot_absence_is_protected(db_session):
    root, machine, container = create_container_graph()
    other = create_container(machine=machine, name=f"anvil_present_{uuid.uuid4().hex[:6]}")
    long_term_container_repo.add(container.id, created_by_user_id=root.id, session=db_session)
    container.container_status = ContainerStatus.STARTING
    db_session.commit()
    result = node_comms.apply_container_status_snapshot(
        {other.name: {"status": "online"}}, machine.id,
    )
    db_session.expire_all()
    row = _row(db_session, container.id)
    assert result["vanished"] == 1
    assert row.is_valid is True
    assert row.status_source == "snapshot_missing"
    assert row.status_unknown_since is not None
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True


def test_anvil_c34_wrong_machine_or_inactive_container_frame_is_ignored(db_session):
    machine_a = create_machine()
    machine_b = create_machine()
    container = create_container(machine=machine_a, name=f"anvil_scope_{uuid.uuid4().hex[:6]}")
    container.bind_mount_path = "/home/anvil/containers/a"
    container.disk_total_bytes = 33
    db_session.commit()
    wrong = _apply_disk(container, machine_b.id, _frame(
        container, status="resolved", path="/home/anvil/containers/b",
        total=100, overlay=40, bind=60,
        measured_at=dt.datetime.utcnow().replace(microsecond=0).isoformat(),
    ))
    db_session.expire_all()
    row = _row(db_session, container.id)
    assert wrong == {"updated": 0, "skipped": 1}
    assert row.bind_mount_path == "/home/anvil/containers/a"
    assert row.disk_total_bytes == 33

    containers_repo.delete_container(container.id, deleted_trigger="api", session=db_session)
    db_session.commit()
    before = _row(db_session, container.id)
    after_frame = _apply_disk(container, machine_a.id, _frame(
        container, status="resolved", path="/home/anvil/containers/b",
        total=100, overlay=40, bind=60,
        measured_at=dt.datetime.utcnow().replace(microsecond=0).isoformat(),
    ))
    db_session.expire_all()
    after = _row(db_session, container.id)
    assert after_frame == {"updated": 0, "skipped": 1}
    assert after.bind_mount_path == before.bind_mount_path
    assert after.disk_total_bytes == before.disk_total_bytes


def test_anvil_c36_delete_frame_preserves_accounts_and_long_term(db_session):
    root, machine, container = create_container_graph()
    long_term_container_repo.add(container.id, created_by_user_id=root.id, session=db_session)
    db_session.commit()
    node_comms._handle_container_vanish(container.name, machine.id)
    db_session.expire_all()
    row = _row(db_session, container.id)
    assert row.is_valid is True
    assert row.status_source == "delete_frame"
    from ...repositories import usercontainer_repo
    bindings = usercontainer_repo.get_container_bindings(container.id, session=db_session)
    assert [binding["user_id"] for binding in bindings] == [root.id]
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True
    assert db_session.scalars(select(DeletedContainerRestoreSnapshot)).all() == []


def test_anvil_c37_disk_rejection_logs_reason_without_zero(db_session, caplog):
    machine = create_machine()
    container = create_container(machine=machine, name=f"anvil_reject_{uuid.uuid4().hex[:6]}")
    container.bind_mount_path = "/home/anvil/containers/a"
    container.disk_total_bytes = 33
    container.disk_overlay_rw_bytes = 11
    container.disk_bind_mount_bytes = 22
    container.disk_checked_at = dt.datetime.utcnow() - dt.timedelta(minutes=5)
    db_session.commit()
    caplog.set_level(logging.WARNING)

    cases = [
        ({"bind_mount_path": container.bind_mount_path, "overlay_rw_bytes": 50,
          "bind_mount_bytes": 50, "measured_at": dt.datetime.utcnow().isoformat()},
         "total_bytes_missing"),
        ({"bind_mount_path": container.bind_mount_path, "total_bytes": 100,
          "overlay_rw_bytes": 40, "measured_at": dt.datetime.utcnow().isoformat()},
         "bind_bytes_missing"),
        ({"bind_mount_path": container.bind_mount_path, "total_bytes": 100,
          "overlay_rw_bytes": None, "bind_mount_bytes": 60,
          "measured_at": dt.datetime.utcnow().isoformat()},
         "overlay_incomplete"),
        ({"bind_mount_path": "/home/anvil/containers/b",
          "total_bytes": 100, "overlay_rw_bytes": 40, "bind_mount_bytes": 60,
          "measured_at": dt.datetime.utcnow().isoformat()},
         "path_inconsistent"),
    ]
    for payload, reason in cases:
        result = _apply_disk(container, machine.id, {"containers": {container.name: payload}})
        assert result == {"updated": 0, "skipped": 1}
        assert f"reason={reason}" in caplog.text
    db_session.expire_all()
    row = _row(db_session, container.id)
    assert row.disk_total_bytes == 33
    assert row.disk_overlay_rw_bytes == 11
    assert row.disk_bind_mount_bytes == 22


def test_anvil_c38_stale_measurement_does_not_reopen_or_extend_freeze_cycle(
    db_session, monkeypatch,
):
    machine = create_machine(max_disk_size_gb=1)
    container = create_container(machine=machine, name=f"anvil_stale_{uuid.uuid4().hex[:6]}")
    container.disk_total_bytes = 2 * 1024**3
    container.disk_overlay_rw_bytes = 2 * 1024**3
    container.disk_checked_at = dt.datetime.utcnow() - dt.timedelta(hours=2)
    long_term_container_repo.add(container.id, session=db_session)
    freeze = container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    freeze.first_frozen_at = dt.datetime(2026, 10, 1, 12, 0, 0)
    freeze.grace_until = dt.datetime(2026, 10, 5, 12, 0, 0)
    freeze.deferral_seconds = 77
    db_session.commit()
    before = (freeze.first_frozen_at, freeze.grace_until, freeze.deferral_seconds)

    monkeypatch.setattr(container_disk_check_task, "machine_in_scope", lambda _id: True)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_check_enabled", lambda: True)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_response_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(
        container_disk_check_task, "_handle_hard_limit_with_escalation",
        lambda c, _usage, _cache: calls.append(c.id),
    )
    container_disk_check_task.check_all_containers_disk_usage_once()
    assert calls == []
    db_session.expire_all()
    after = container_disk_freeze_state_repo.get(container.id, session=db_session)
    assert (after.first_frozen_at, after.grace_until, after.deferral_seconds) == before


# ---------------------------------------------------------------------------
# deleted restore snapshot / mount usage
# ---------------------------------------------------------------------------

def test_anvil_d01_restore_snapshot_readback_and_defaults(db_session):
    machine = create_machine()
    row = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": 99,
            "container_name": "anvil_snapshot",
            "machine_id": machine.id,
            "bind_mount_path": "/home/anvil/containers/snapshot_data",
        },
        session=db_session,
    )
    db_session.commit()
    with session_scope(commit=False) as session:
        loaded = deleted_container_restore_snapshot_repo.get_by_id(row.id, session=session)
        assert isinstance(loaded.id, int)
        assert loaded.original_container_id == 99
        assert loaded.container_name == "anvil_snapshot"
        assert loaded.machine_id == machine.id
        assert loaded.mount_cleanup_id is None
        assert loaded.removed_trigger == "api"
        assert loaded.snapshot["bind_mount_path"] == "/home/anvil/containers/snapshot_data"
        assert isinstance(loaded.removed_at, dt.datetime)
        assert loaded.mount_cleaned is False
        assert loaded.deferral_seconds == 0

    db_session.execute(text(
        "INSERT INTO deleted_container_restore_snapshot "
        "(original_container_id, container_name, removed_trigger, snapshot, removed_at) "
        "VALUES (:cid, :name, 'api', :snapshot, :removed_at)"
    ), {
        "cid": 100, "name": "raw_snapshot", "snapshot": '{"x": 1}',
        "removed_at": dt.datetime.utcnow().isoformat(sep=" "),
    })
    db_session.commit()
    defaults = db_session.execute(text(
        "SELECT mount_cleaned, deferral_seconds FROM deleted_container_restore_snapshot "
        "WHERE original_container_id = 100"
    )).one()
    assert bool(defaults[0]) is False
    assert int(defaults[1]) == 0


def test_anvil_d02_mount_usage_query_adds_no_schema(db_session):
    for model in (DeletedContainerRestoreSnapshot, ContainerMountCleanup):
        columns = {column.name for column in model.__table__.columns}
        assert not {"bytes", "measured_at", "pending", "usage", "path"} & columns
    forbidden = {
        name for name in Container.metadata.tables
        if "mount_usage" in name.lower() or "usage" in name.lower()
    }
    assert forbidden == set()


def test_anvil_d03_node_unsupported_does_not_change_list_or_restore_eligibility(
    db_session, mock_node_send,
):
    machine = create_machine()
    cleanup = container_mount_cleanup_repo.insert(
        501, "deleted_usage", machine.id, "/home/anvil/containers/deleted_usage",
        session=db_session,
    )
    snapshot = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": 501,
            "container_name": "deleted_usage",
            "machine_id": machine.id,
            "bind_mount_path": "/home/anvil/containers/deleted_usage",
        },
        session=db_session,
        mount_cleanup_id=cleanup.id,
    )
    db_session.commit()
    mock_node_send({"success": 0, "status_code": 404, "error": "not found"})
    result = container_tasks.get_deleted_container_mount_usage([snapshot.id])
    assert result["usages"][0]["error"] == "node_unsupported"
    listed = container_tasks.list_deleted_containers(page_number=1, page_size=20)
    assert listed["total_number"] == 1
    assert listed["records"][0]["data_recoverable"] is True
    db_session.expire_all()
    assert deleted_container_restore_snapshot_repo.get_by_id(snapshot.id, session=db_session) is not None
    assert container_mount_cleanup_repo.get_by_id(cleanup.id, session=db_session).cleaned_at is None


# ---------------------------------------------------------------------------
# cleanup reminders / mount cleanup
# ---------------------------------------------------------------------------

def test_anvil_r01_cleanup_reminder_readback_and_unique(db_session):
    cleanup_at = dt.datetime.utcnow() + dt.timedelta(hours=12)
    assert container_cleanup_reminder_repo.mark_sent(
        41, "12h", cleanup_at, "anvil@example.test", session=db_session,
    ) is True
    db_session.commit()
    with session_scope(commit=False) as session:
        rows = list(session.scalars(select(ContainerCleanupReminder)).all())
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row.id, int)
        assert row.container_id == 41
        assert row.reminder_key == "12h"
        assert row.cleanup_at == cleanup_at
        assert row.recipient_email == "anvil@example.test"
        assert isinstance(row.sent_at, dt.datetime)

    db_session.add(ContainerCleanupReminder(
        container_id=41,
        reminder_key="24h",
        cleanup_at=cleanup_at,
        recipient_email="anvil@example.test",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_anvil_r02_reminder_audit_snapshot_fields(db_session, monkeypatch):
    _root, _machine, container = create_container_graph()
    cleanup_at = dt.datetime.utcnow().replace(microsecond=0) + dt.timedelta(hours=1)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.repositories.containers_repo.get_container_root_owner_emails",
        lambda container_id, **kwargs: ["anvil@example.test"],
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.container_tasks.build_container_restore_snapshot",
        lambda *args, **kwargs: {"container_name": "c"},
    )
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp", lambda **kwargs: {"ok": True})
    from ...schedulers import container_cleanup_task
    container_cleanup_task._send_cleanup_reminders_if_needed(
        container.id,
        {
            "cleanup_status": "countdown",
            "seconds_until_cleanup": 3600,
            "cleanup_at": cleanup_at.isoformat(),
        },
    )
    db_session.expire_all()
    row = db_session.scalars(select(ContainerCleanupReminder)).one()
    assert row.recipient_email == "anvil@example.test"
    assert row.cleanup_at == cleanup_at
    assert abs((dt.datetime.utcnow() - row.sent_at).total_seconds()) < 5


def test_anvil_m01_mount_cleanup_readback_and_defaults(db_session):
    removed_at = dt.datetime.utcnow().replace(microsecond=0)
    row = container_mount_cleanup_repo.insert(
        71, "anvil_mount", 3, "/home/anvil/containers/mount_data",
        removed_at=removed_at, session=db_session,
    )
    db_session.commit()
    with session_scope(commit=False) as session:
        loaded = container_mount_cleanup_repo.get_by_id(row.id, session=session)
        assert isinstance(loaded.id, int)
        assert loaded.container_id == 71
        assert loaded.container_name == "anvil_mount"
        assert loaded.machine_id == 3
        assert loaded.mount_path == "/home/anvil/containers/mount_data"
        assert loaded.escalation is False
        assert loaded.removed_at == removed_at
        assert loaded.cleaned_at is None


class _InjectedFault(RuntimeError):
    pass


def test_anvil_m02_clean_success_syncs_snapshot_in_transaction(
    db_session, monkeypatch, mock_node_send,
):
    root, machine, container = create_container_graph()
    container.bind_mount_path = "/home/anvil/containers/m02_data"
    db_session.commit()
    mock_node_send({"success": 1})
    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    db_session.expire_all()
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()
    cleanup = container_mount_cleanup_repo.get_by_id(snapshot.mount_cleanup_id, session=db_session)
    mock_node_send({"success": 1})
    result = mount_cleanup_mod.clean_mount_path(cleanup.id)
    assert result["cleaned"] is True
    db_session.expire_all()
    assert container_mount_cleanup_repo.get_by_id(cleanup.id, session=db_session).cleaned_at is not None
    assert deleted_container_restore_snapshot_repo.get_by_id(snapshot.id, session=db_session).mount_cleaned is True

    root2, machine2, container2 = create_container_graph()
    container2.bind_mount_path = "/home/anvil/containers/m02_fault"
    db_session.commit()
    mock_node_send({"success": 1})
    assert container_tasks.remove_container(container2.id, operator_user_id=root2.id) is True
    db_session.expire_all()
    snapshot2 = db_session.scalars(
        select(DeletedContainerRestoreSnapshot).where(
            DeletedContainerRestoreSnapshot.original_container_id == container2.id,
        )
    ).one()
    cleanup2 = container_mount_cleanup_repo.get_by_id(snapshot2.mount_cleanup_id, session=db_session)
    calls = {"n": 0}

    def _fail_snapshot(*args, **kwargs):
        calls["n"] += 1
        raise _InjectedFault("snapshot write failed")

    monkeypatch.setattr(
        "FuxiYu_CtrKernel.repositories.deleted_container_restore_snapshot_repo.mark_mount_cleaned",
        _fail_snapshot,
    )
    mock_node_send({"success": 1})
    with pytest.raises(_InjectedFault):
        mount_cleanup_mod.clean_mount_path(cleanup2.id)
    assert calls["n"] == 1
    db_session.expire_all()
    assert container_mount_cleanup_repo.get_by_id(cleanup2.id, session=db_session).cleaned_at is None
    assert deleted_container_restore_snapshot_repo.get_by_id(snapshot2.id, session=db_session).mount_cleaned is False
