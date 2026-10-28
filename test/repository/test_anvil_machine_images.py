"""Anvil 映射补测：images / machine_image / machines 的既有契约回归。

本文件只补 test-plan 中标记为 `[ ]` 的独立用例；不改变业务实现。
外部 Node/TLS 使用替身；数据库故障用 SQLite 触发器在真实写入边界注入。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

import pytest
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import IntegrityError

from ... import extensions
from ...api import deps
from ...constant import (
    ContainerStatus,
    ImageStatus,
    ImageValidRange,
    MachineStatus,
    MachineTypes,
    OperationType,
)
from ...extensions import session_scope
from ...models.container_ssh_login import ContainerSSHLogin
from ...models.image import Image
from ...models.machine import Machine
from ...models.machine_image import MachineImage
from ...models.operation_log import OperationLog
from ...repositories import (
    containers_repo,
    image_repo,
    machine_image_repo,
    machine_repo,
    userimage_repo,
)
from ...services import container_tasks, image_tasks, machine_tasks, settings_tasks
from ...services.container_module import node_comms
from ...services.container_module.exceptions import NodeServiceError
from ...services.container_module.node_comms_modules import (
    enrollment,
    link,
    snapshots,
    transport,
)
from ...services.container_module.node_comms_modules import websocket as websocket_module
from ...utils.Container import Container_info
from ..factories import (
    create_container,
    create_container_graph,
    create_machine,
    create_user,
)

ISO = "%Y-%m-%dT%H:%M:%S"


def _auth(monkeypatch, user_id: int) -> None:
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kw: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kw: user_id)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, kind, rid: True
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service._has_resource_manage_direct",
        lambda uid, kind: True,
    )


def _container_info(name: str, *, memory: int = 4, shared: int = 1) -> Container_info:
    return Container_info(
        gpu_list=[], cpu_number=1, memory=memory, shared_memory=shared, name=name, image="ignored",
    )


def _set_machine_offline_with_window(db_session, machine_id: int, *, hours: int = 2) -> None:
    with session_scope() as session:
        row = machine_repo.get_by_id(machine_id, session=session)
        row.machine_status = MachineStatus.OFFLINE
        row.unavailable_since = dt.datetime.utcnow() - dt.timedelta(hours=hours)
        session.flush()


def _add_ssh_record(db_session, machine_id: int, container_id: int) -> ContainerSSHLogin:
    row = ContainerSSHLogin(
        machine_id=machine_id,
        container_id=container_id,
        last_ssh_login_time="2026-01-01T00:00:00",
        deferral_seconds=0,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _create_trigger(db_session, name: str, ddl: str) -> None:
    db_session.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
    db_session.execute(text(ddl))
    db_session.commit()


# ---------------------------------------------------------------------------
# images
# ---------------------------------------------------------------------------


def test_image_model_roundtrip_preserves_id_and_null_semantics(db_session):
    image = Image(
        name="anvil-image-roundtrip",
        description=None,
        base_image="ubuntu:24.04",
        dockerfile_body="",
        entrypoint=None,
        created_by_user_id=None,
    )
    db_session.add(image)
    db_session.commit()

    row = image_repo.get_by_id(image.id, session=db_session)
    assert row.id == image.id
    assert row.name == "anvil-image-roundtrip"
    assert row.description is None
    assert row.base_image == "ubuntu:24.04"
    assert row.entrypoint is None
    assert row.created_by_user_id is None
    assert row.status == ImageStatus.DRAFT
    assert row.valid_range == ImageValidRange.CUSTOM
    assert row.created_at is not None
    assert row.updated_at is not None

    columns = {column.name: column for column in Image.__table__.columns}
    assert columns["description"].nullable is True
    assert columns["entrypoint"].nullable is True
    assert columns["created_by_user_id"].nullable is True
    assert columns["status"].nullable is False
    assert columns["valid_range"].nullable is False
    assert columns["created_at"].nullable is False
    assert columns["updated_at"].nullable is False
    assert not columns["name"].unique
    name_indexes = [
        index for index in inspect(extensions.engine).get_indexes("images")
        if "name" in index["column_names"]
    ]
    assert all(not index["unique"] for index in name_indexes)


def test_rename_checks_active_names_and_allows_disabled_name(db_session):
    first = image_tasks.Create_image(
        name="anvil-rename-first", base_image="ubuntu:24.04", dockerfile_body="",
    )
    second = image_tasks.Create_image(
        name="anvil-rename-second", base_image="ubuntu:24.04", dockerfile_body="",
    )

    with pytest.raises(ValueError, match="already in use"):
        image_tasks.Update_image(image_id=first, name="anvil-rename-second")
    assert image_repo.get_by_id(first, session=db_session).name == "anvil-rename-first"

    assert image_tasks.Delete_image(image_id=second) is True
    assert image_tasks.Update_image(image_id=first, name="anvil-rename-second") is True
    assert image_repo.get_by_id(first, session=db_session).name == "anvil-rename-second"

    # 改回自身当前名称不算撞名。
    assert image_tasks.Update_image(image_id=first, name="anvil-rename-second") is True


def test_machine_image_row_stays_readable_after_template_disabled(db_session):
    machine = create_machine()
    build = image_tasks.resolve_image_build(1, machine.id)
    assert image_tasks.Delete_image(image_id=1) is True

    db_session.expire_all()
    row = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    assert row is not None
    assert row.image_tag == build.payload["image_tag"]
    assert row.recipe_fingerprint == image_tasks.recipe_fingerprint(build.dockerfile_parts)


def test_seed_legacy_name_converges_in_place_without_overwriting_status(db_session):
    seed = image_repo.get_by_id(1, session=db_session)
    db_session.delete(seed)
    db_session.commit()

    legacy = Image(
        name="Ubuntu 22.04 · 基础",
        description="legacy",
        base_image="ubuntu:22.04",
        dockerfile_body="RUN echo legacy",
        status=ImageStatus.DISABLED,
        valid_range=ImageValidRange.EVERYONE,
        created_by_user_id=None,
    )
    db_session.add(legacy)
    db_session.commit()
    legacy_id = legacy.id
    before_count = len(db_session.scalars(select(Image)).all())

    image_tasks.seed_image_defaults()
    db_session.expire_all()
    row = image_repo.get_by_id(legacy_id, session=db_session)
    assert row is not None
    assert row.name == "Ubuntu 24.04 · 基础"
    assert row.base_image == "ubuntu:24.04"
    assert row.dockerfile_body == ""
    assert row.status == ImageStatus.DISABLED
    assert row.created_by_user_id is None
    assert len(db_session.scalars(select(Image)).all()) == before_count

    image_tasks.seed_image_defaults()
    assert len(db_session.scalars(select(Image)).all()) == before_count

    user = create_user()
    user_row = Image(
        name="Ubuntu 24.04 · 基础",
        description="user-owned",
        base_image="custom:1",
        dockerfile_body="RUN echo custom",
        status=ImageStatus.READY,
        valid_range=ImageValidRange.EVERYONE,
        created_by_user_id=user.id,
    )
    db_session.add(user_row)
    db_session.commit()
    user_row_id = user_row.id

    image_tasks.seed_image_defaults()
    db_session.expire_all()
    kept = image_repo.get_by_id(user_row_id, session=db_session)
    assert kept.description == "user-owned"
    assert kept.base_image == "custom:1"
    assert kept.dockerfile_body == "RUN echo custom"


def test_platform_injection_change_keeps_ownership_grants_and_old_container(db_session):
    owner = create_user()
    other = create_user()
    image_id = image_tasks.Create_image(
        name="anvil-inject-owner",
        base_image="ubuntu:24.04",
        dockerfile_body="RUN echo body",
        status=ImageStatus.READY,
        operator_user_id=owner.id,
    )
    userimage_repo.grant_image(other.id, image_id, session=db_session)
    db_session.commit()

    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    container = create_container(machine=machine, image_id=image_id, name="anvil_inject_old")
    before = (
        container.image_id,
        container.last_build_at,
        container.base_image,
        container.dockerfile_body,
        container.entrypoint,
    )

    settings_tasks.set_setting_value(
        settings_tasks.IMAGE_PLATFORM_INJECTION_KEY,
        "USER root\nRUN echo INJECTION_V2\nEXPOSE 22",
    )
    db_session.expire_all()

    image = image_repo.get_by_id(image_id, session=db_session)
    assert image.created_by_user_id == owner.id
    assert image_id in userimage_repo.list_image_ids_by_user(other.id, session=db_session)
    old = containers_repo.get_by_id(container.id, session=db_session)
    assert (old.image_id, old.last_build_at, old.base_image, old.dockerfile_body, old.entrypoint) == before


# ---------------------------------------------------------------------------
# machine_image
# ---------------------------------------------------------------------------


def test_machine_image_model_roundtrip_enforces_composite_identity(db_session):
    machine = create_machine()
    row = machine_image_repo.record_dispatch(
        machine.id, 1, "fuxi/image-1:20260101T000000Z", dt.datetime(2026, 1, 1), None,
        session=db_session,
    )
    db_session.commit()

    loaded = db_session.get(MachineImage, row.id)
    assert loaded is not None
    assert (loaded.machine_id, loaded.image_id) == (machine.id, 1)
    assert loaded.image_tag == "fuxi/image-1:20260101T000000Z"
    assert loaded.recipe_fingerprint is None
    assert loaded.created_at == dt.datetime(2026, 1, 1)

    columns = {column.name: column for column in MachineImage.__table__.columns}
    assert columns["image_tag"].nullable is False
    assert columns["created_at"].nullable is False
    assert columns["recipe_fingerprint"].nullable is True
    assert columns["machine_id"].nullable is False
    assert columns["image_id"].nullable is False

    unique_constraints = inspect(extensions.engine).get_unique_constraints("machine_image")
    assert any(
        constraint["column_names"] == ["machine_id", "image_id"]
        for constraint in unique_constraints
    )
    fks = inspect(extensions.engine).get_foreign_keys("machine_image")
    machine_fk = next(fk for fk in fks if fk["constrained_columns"] == ["machine_id"])
    assert machine_fk["options"].get("ondelete") == "CASCADE"

    duplicate = MachineImage(
        machine_id=machine.id,
        image_id=1,
        image_tag="fuxi/image-1:20260101T000001Z",
        created_at=dt.datetime(2026, 1, 1, 0, 0, 1),
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_base_image_change_changes_cached_recipe(db_session):
    machine = create_machine()
    first = image_tasks.resolve_image_build(1, machine.id)
    row = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    first_row = (row.id, row.image_tag, row.created_at, row.recipe_fingerprint)

    assert image_tasks.Update_image(image_id=1, base_image="ubuntu:22.04") is True
    second = image_tasks.resolve_image_build(1, machine.id)
    db_session.expire_all()
    replaced = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)

    assert second.payload["image_tag"] != first.payload["image_tag"]
    assert second.payload["dockerfile_text"].startswith("FROM ubuntu:22.04")
    assert replaced.id == first_row[0]
    assert replaced.image_tag == second.payload["image_tag"]
    assert replaced.recipe_fingerprint == image_tasks.recipe_fingerprint(second.dockerfile_parts)


def test_entrypoint_change_changes_cached_recipe(db_session):
    machine = create_machine()
    first = image_tasks.resolve_image_build(1, machine.id)
    row = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    first_row = (row.id, row.image_tag, row.created_at, row.recipe_fingerprint)

    assert image_tasks.Update_image(image_id=1, entrypoint="/app/boot.sh") is True
    second = image_tasks.resolve_image_build(1, machine.id)
    db_session.expire_all()
    replaced = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)

    assert second.payload["image_tag"] != first.payload["image_tag"]
    assert second.payload["dockerfile_text"].rstrip().endswith("ENTRYPOINT /app/boot.sh")
    assert replaced.id == first_row[0]
    assert replaced.image_tag == second.payload["image_tag"]
    assert replaced.recipe_fingerprint == image_tasks.recipe_fingerprint(second.dockerfile_parts)


def test_node_rejection_keeps_reserved_row_and_next_dispatch_still_sends_build(
    db_session, monkeypatch,
):
    owner = create_user()
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    build = image_tasks.resolve_image_build(1, machine.id)
    row = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    reserved = (row.id, row.image_tag, row.created_at, row.recipe_fingerprint)

    responses = [{"success": 0, "error_reason": "create_failed"}, {"success": 1}]
    calls = []

    def _send(url, payload, timeout=5.0):
        calls.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(node_comms, "send", _send)

    with pytest.raises(NodeServiceError) as exc:
        container_tasks.Create_container(
            owner_user_id=owner.id,
            machine_id=machine.id,
            container=_container_info("anvil_node_reject"),
            image_build=build.payload,
            image_id=1,
            image_version_at=build.version_at,
            dockerfile_parts=build.dockerfile_parts,
        )
    assert exc.value.reason == "create_failed"

    db_session.expire_all()
    kept = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    assert (kept.id, kept.image_tag, kept.created_at, kept.recipe_fingerprint) == reserved

    container_tasks.Create_container(
        owner_user_id=owner.id,
        machine_id=machine.id,
        container=_container_info("anvil_node_reject_retry"),
        image_build=build.payload,
        image_id=1,
        image_version_at=build.version_at,
        dockerfile_parts=build.dockerfile_parts,
    )
    assert len(calls) == 2
    assert calls[1]["image_build"]["image_tag"] == build.payload["image_tag"]


def test_reservation_write_failure_prevents_dispatch_without_cache_row(
    client, db_session, monkeypatch,
):
    owner = create_user(operator=True)
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    _auth(monkeypatch, owner.id)

    calls = []
    monkeypatch.setattr(
        node_comms, "send",
        lambda url, payload, timeout=5.0: calls.append(payload) or {"success": 1},
    )

    observed_errors = []

    def _observe_db_error(context):
        original = getattr(context, "original_exception", None)
        observed_errors.append(str(original or context.sqlalchemy_exception))

    event.listen(extensions.engine, "handle_error", _observe_db_error)
    try:
        _create_trigger(
            db_session,
            "anvil_machine_image_reservation_fail",
            "CREATE TRIGGER anvil_machine_image_reservation_fail "
            "BEFORE INSERT ON machine_image "
            "BEGIN SELECT RAISE(ABORT, 'reservation blocked'); END;",
        )
        assert db_session.execute(
            text(
                "SELECT count(*) FROM sqlite_master "
                "WHERE type='trigger' AND name='anvil_machine_image_reservation_fail'"
            )
        ).scalar() == 1

        response = client.post(
            "/api/containers/create_container",
            json={
                "owner_user_id": owner.id,
                "machine_id": machine.id,
                "image_id": 1,
                "container": {
                    "GPU_LIST": [],
                    "CPU_NUMBER": 1,
                    "MEMORY": 4,
                    "SHARED_MEM": 1,
                    "NAME": "anvil_reservation_fail",
                },
            },
        )

        assert response.status_code == 400
        assert response.json()["error_reason"] == "invalid_payload"
        assert calls == []
        assert any("reservation blocked" in message for message in observed_errors)
        db_session.expire_all()
        assert machine_image_repo.list_by_machine(machine.id, session=db_session) == []
    finally:
        event.remove(extensions.engine, "handle_error", _observe_db_error)
        db_session.rollback()
        db_session.execute(text("DROP TRIGGER IF EXISTS anvil_machine_image_reservation_fail"))
        db_session.commit()


def test_same_value_confirmation_is_idempotent_noop(db_session, monkeypatch):
    owner = create_user()
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    build = image_tasks.resolve_image_build(1, machine.id)
    row = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    reserved = (row.id, row.image_tag, row.created_at, row.recipe_fingerprint)

    monkeypatch.setattr(node_comms, "send", lambda *a, **kw: {"success": 1})
    container_tasks.Create_container(
        owner_user_id=owner.id,
        machine_id=machine.id,
        container=_container_info("anvil_confirmation_noop"),
        image_build=build.payload,
        image_id=1,
        image_version_at=build.version_at,
        dockerfile_parts=build.dockerfile_parts,
    )

    db_session.expire_all()
    rows = machine_image_repo.list_by_machine(machine.id, session=db_session)
    assert len(rows) == 1
    assert (rows[0].id, rows[0].image_tag, rows[0].created_at, rows[0].recipe_fingerprint) == reserved
    again = image_tasks.resolve_image_build(1, machine.id)
    assert again.payload["image_tag"] == reserved[1]
    assert again.version_at == reserved[2]


# ---------------------------------------------------------------------------
# machines: persistence / shared memory
# ---------------------------------------------------------------------------


def test_machine_model_roundtrip_preserves_columns_and_null_semantics(db_session):
    machine = Machine(
        machine_name="anvil-machine-roundtrip",
        machine_ip="10.44.0.1",
        machine_type=MachineTypes.CPU,
    )
    db_session.add(machine)
    db_session.commit()

    row = machine_repo.get_by_id(machine.id, session=db_session)
    assert row.machine_name == "anvil-machine-roundtrip"
    assert row.machine_ip == "10.44.0.1"
    assert row.port is None
    assert row.machine_status == MachineStatus.ONLINE
    assert row.is_maintenance is False
    assert row.gpu_list is None
    assert row.gpu_allow_list is None
    assert row.max_shared_gb is None
    assert row.node_uid is None
    assert row.node_cert_fingerprint is None

    columns = {column.name: column for column in Machine.__table__.columns}
    assert columns["machine_name"].unique is True
    assert columns["machine_name"].nullable is False
    assert columns["machine_ip"].unique is True
    assert columns["machine_ip"].nullable is False
    assert columns["node_uid"].unique is True
    assert columns["node_uid"].nullable is True
    assert columns["node_cert_fingerprint"].unique is True
    assert columns["node_cert_fingerprint"].nullable is True
    for name in ("port", "gpu_list", "gpu_allow_list", "max_shared_gb", "max_memory_gb"):
        assert columns[name].nullable is True


def test_null_shared_limit_with_known_memory_skips_comparison(db_session):
    machine = create_machine(max_shared_gb=None, max_memory_gb=8)

    assert machine_tasks.Update_machine(machine.id, max_memory_gb=16) is True
    db_session.expire_all()
    row = db_session.get(Machine, machine.id)
    assert row.max_shared_gb is None
    assert row.max_memory_gb == 16

    assert machine_tasks.Update_machine(
        machine.id, max_shared_gb=None, max_memory_gb=12,
    ) is True
    db_session.expire_all()
    row = db_session.get(Machine, machine.id)
    assert row.max_shared_gb is None
    assert row.max_memory_gb == 12


# ---------------------------------------------------------------------------
# machines: endpoint / renew
# ---------------------------------------------------------------------------


def test_endpoint_update_keeps_pin_fingerprint_without_probe(monkeypatch, db_session, tmp_path):
    machine = create_machine(machine_name="anvil_endpoint", machine_ip="10.0.0.7")
    with session_scope() as session:
        machine_repo.update_machine(
            machine.id, node_cert_fingerprint="fp-old", session=session,
        )
    monkeypatch.setattr(transport, "PINNED_CERTS_DIR", str(tmp_path))
    monkeypatch.setattr(enrollment, "der_cert_to_pem", lambda der: b"PEM-" + der)
    enrollment._persist_peer_pin("10.0.0.7", b"old-cert")
    pin_file = transport._pin_file("10.0.0.7")
    before = pin_file.read_bytes()

    probed = []

    def _must_not_probe(*args, **kwargs):
        probed.append((args, kwargs))
        raise AssertionError("endpoint registration must not probe")

    monkeypatch.setattr(machine_tasks, "_fetch_peer_cert", _must_not_probe)
    assert machine_tasks.Update_machine(machine.id, machine_ip="10.0.0.99") is True

    db_session.expire_all()
    row = db_session.get(Machine, machine.id)
    assert row.machine_ip == "10.0.0.99"
    assert row.node_cert_fingerprint == "fp-old"
    assert probed == []
    assert pin_file.read_bytes() == before


def test_renew_profile_failure_keeps_pin_and_credentials(monkeypatch, db_session):
    machine = create_machine(machine_name="anvil_renew_profile", machine_ip="10.0.0.8")
    with session_scope() as session:
        machine_repo.update_machine(
            machine.id, node_uid="old-uid", node_cert_fingerprint="fp-old", session=session,
        )

    monkeypatch.setattr(machine_tasks, "_get_enrollment_client_cert", lambda: None)
    monkeypatch.setattr(
        machine_tasks, "_fetch_peer_cert",
        lambda host, port, timeout=8.0: ("fp-new", b"new-cert"),
    )

    def _profile_fail(*args, **kwargs):
        raise OSError("profile unavailable")

    monkeypatch.setattr(machine_tasks, "_fetch_enrollment_profile", _profile_fail)
    pins = []
    monkeypatch.setattr(machine_tasks, "_persist_peer_pin", lambda *a: pins.append(a))

    with pytest.raises(NodeServiceError) as exc:
        machine_tasks.Renew_machine_trust(machine.id)
    assert exc.value.reason == "enrollment_failed"

    db_session.expire_all()
    row = db_session.get(Machine, machine.id)
    assert row.node_uid == "old-uid"
    assert row.node_cert_fingerprint == "fp-old"
    assert pins == []

    log = db_session.scalars(
        select(OperationLog).filter_by(operation=OperationType.RENEW_MACHINE_TRUST.value)
    ).one()
    assert log.success is False
    assert log.error_reason == "enrollment_failed"


def test_renew_persist_failure_keeps_pin_file_and_returns_persist_failed(
    monkeypatch, db_session, tmp_path,
):
    machine = create_machine(machine_name="anvil_renew_persist", machine_ip="10.0.0.9")
    with session_scope() as session:
        machine_repo.update_machine(
            machine.id, node_uid="old-uid", node_cert_fingerprint="fp-old", session=session,
        )

    monkeypatch.setattr(machine_tasks, "_get_enrollment_client_cert", lambda: None)
    monkeypatch.setattr(
        machine_tasks, "_fetch_peer_cert",
        lambda host, port, timeout=8.0: ("fp-new", b"new-cert"),
    )
    monkeypatch.setattr(
        machine_tasks, "_fetch_enrollment_profile",
        lambda *args, **kwargs: {"identity_initialized": True, "uid": "old-uid"},
    )
    monkeypatch.setattr(machine_tasks, "_issue_node_uid", lambda *args, **kwargs: None)
    monkeypatch.setattr(transport, "PINNED_CERTS_DIR", str(tmp_path))
    monkeypatch.setattr(enrollment, "der_cert_to_pem", lambda der: b"PEM-" + der)

    _create_trigger(
        db_session,
        "anvil_machine_persist_fail",
        "CREATE TRIGGER anvil_machine_persist_fail "
        "BEFORE UPDATE ON machines "
        "BEGIN SELECT RAISE(ABORT, 'persist blocked'); END;",
    )

    with pytest.raises(NodeServiceError) as exc:
        machine_tasks.Renew_machine_trust(machine.id)
    assert exc.value.reason == "persist_failed"

    db_session.expire_all()
    row = db_session.get(Machine, machine.id)
    assert row.node_cert_fingerprint == "fp-old"
    pin_file = transport._pin_file("10.0.0.9")
    assert pin_file.exists()
    assert pin_file.read_bytes() == b"PEM-new-cert"

    log = db_session.scalars(
        select(OperationLog).filter_by(operation=OperationType.RENEW_MACHINE_TRUST.value)
    ).one()
    assert log.success is False
    assert log.error_reason == "persist_failed"


# ---------------------------------------------------------------------------
# machines: window / heartbeat
# ---------------------------------------------------------------------------


def test_window_close_failure_keeps_window_open(db_session):
    control_root, control_machine, control_container = create_container_graph()
    fault_root, fault_machine, fault_container = create_container_graph()
    control_ssh = _add_ssh_record(db_session, control_machine.id, control_container.id)
    fault_ssh = _add_ssh_record(db_session, fault_machine.id, fault_container.id)
    _set_machine_offline_with_window(db_session, control_machine.id)
    _set_machine_offline_with_window(db_session, fault_machine.id)

    # 正常控制组：同一 SSH 行 + delta>0 路径无触发器时可成功结算。
    assert machine_tasks.Update_machine(control_machine.id, machine_status=MachineStatus.ONLINE) is True
    db_session.expire_all()
    control = db_session.get(Machine, control_machine.id)
    control_ssh = db_session.get(ContainerSSHLogin, (control_machine.id, control_container.id))
    assert control.machine_status == MachineStatus.ONLINE
    assert control.unavailable_since is None
    assert (control_ssh.deferral_seconds or 0) >= 7000

    _create_trigger(
        db_session,
        "anvil_window_settle_fail",
        "CREATE TRIGGER anvil_window_settle_fail "
        "BEFORE UPDATE OF deferral_seconds ON container_ssh_login_records "
        "BEGIN SELECT RAISE(ABORT, 'window settle blocked'); END;",
    )
    assert db_session.execute(
        text("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name='anvil_window_settle_fail'")
    ).scalar() == 1

    try:
        with pytest.raises(IntegrityError, match="window settle blocked"):
            machine_tasks.Update_machine(fault_machine.id, machine_status=MachineStatus.ONLINE)
    finally:
        db_session.rollback()
        db_session.execute(text("DROP TRIGGER IF EXISTS anvil_window_settle_fail"))
        db_session.commit()

    db_session.expire_all()
    fault = db_session.get(Machine, fault_machine.id)
    fault_ssh = db_session.get(ContainerSSHLogin, (fault_machine.id, fault_container.id))
    assert fault.machine_status == MachineStatus.OFFLINE
    assert fault.unavailable_since is not None
    assert (fault_ssh.deferral_seconds or 0) == 0


def test_last_seen_write_failure_does_not_block_snapshot_apply(
    monkeypatch, db_session, caplog,
):
    machine = create_machine()
    with session_scope() as session:
        machine_repo.update_machine(machine.id, node_uid="uid-last-seen", session=session)
    container = create_container(machine=machine)
    snapshots._last_seen_written.clear()

    _create_trigger(
        db_session,
        "anvil_last_seen_fail",
        "CREATE TRIGGER anvil_last_seen_fail "
        "BEFORE UPDATE OF last_seen_at ON machines "
        "BEGIN SELECT RAISE(ABORT, 'last seen blocked'); END;",
    )

    with caplog.at_level(logging.WARNING):
        result = node_comms.apply_snapshot_batch({
            "type": "snapshot_batch",
            "node_uid": "uid-last-seen",
            "payload": [{
                "type": "snapshot",
                "topic": "container_status",
                "payload": {container.name: {"status": "offline"}},
            }],
        })

    db_session.expire_all()
    assert result.get("container_status") is not None
    assert db_session.get(Machine, machine.id).last_seen_at is None
    assert db_session.get(type(container), container.id).container_status == ContainerStatus.OFFLINE
    assert any("touch last_seen failed" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# machines: link backoff
# ---------------------------------------------------------------------------


def test_link_backoff_is_per_machine_and_resets_on_connect(monkeypatch):
    import websockets

    real_sleep = asyncio.sleep
    delays: list[tuple[str, float]] = []
    statuses: list[tuple[int, MachineStatus]] = []
    attempts = {"fail": 0, "ok": 0}

    async def _fake_sleep(delay):
        task = asyncio.current_task()
        delays.append((task.get_name() if task else "", delay))
        await real_sleep(0)

    monkeypatch.setattr(link.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(link, "LINK_BACKOFF_INITIAL", 0.01)
    monkeypatch.setattr(link, "LINK_BACKOFF_MAX", 0.04)
    monkeypatch.setattr(link, "build_link_ssl_context", lambda host: object())
    monkeypatch.setattr(
        link, "_mark_machine_status",
        lambda machine_id, status: statuses.append((machine_id, status)),
    )

    class _Connection:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    def _connect(url, ssl=None, proxy=None):
        if "10.0.0.1" in url:
            attempts["fail"] += 1
            if attempts["fail"] == 3:
                return _Connection()
            raise OSError("refused")
        attempts["ok"] += 1
        return _Connection()

    async def _consume(websocket, uid, machine_id):
        if machine_id == 101:
            raise RuntimeError("closed after connect")
        await asyncio.Event().wait()

    monkeypatch.setattr(websockets, "connect", _connect)
    monkeypatch.setattr(websocket_module, "_consume_link", _consume)

    async def _main():
        fail_task = asyncio.create_task(
            link.run_machine_link(101, "10.0.0.1", 5789, "uid-fail"), name="fail",
        )
        ok_task = asyncio.create_task(
            link.run_machine_link(102, "10.0.0.2", 5789, "uid-ok"), name="ok",
        )
        for _ in range(300):
            await real_sleep(0.005)
            if attempts["fail"] >= 5 and any(
                machine_id == 102 and status == MachineStatus.ONLINE
                for machine_id, status in statuses
            ):
                break
        fail_task.cancel()
        ok_task.cancel()
        await asyncio.gather(fail_task, ok_task, return_exceptions=True)

    asyncio.run(_main())

    fail_delays = [delay for name, delay in delays if name == "fail"]
    ok_delays = [delay for name, delay in delays if name == "ok"]
    assert attempts["fail"] >= 5
    assert attempts["ok"] == 1
    assert ok_delays == []
    assert any(machine_id == 102 and status == MachineStatus.ONLINE for machine_id, status in statuses)
    assert fail_delays[:4] == [0.01, 0.02, 0.01, 0.02]
