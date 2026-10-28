"""RBAC 六张关联表的行为对账用例。

只使用隔离 SQLite（`db_session` 已开启 `PRAGMA foreign_keys=ON`）。本文件不反射
ORM 声明，约束/级联均通过真实写入、读回与故意违约后的 `IntegrityError` 断言。
"""

import pytest
from sqlalchemy import delete, func, null, select
from sqlalchemy.exc import IntegrityError

from ...constant import ImageStatus, ImageValidRange
from ...models.auth_group import AuthGroup, AuthGroupEntity
from ...models.image import Image
from ...models.machine_permission import MachinePermission
from ...models.user_group import UserGroup
from ...models.user_managed_user import UserManagedUser
from ...models.userimage import UserImage
from ...repositories import (
    auth_repo,
    image_repo,
    machine_permission_repo,
    user_managed_user_repo,
    userimage_repo,
)
from ...services import image_tasks, rbac_service, user_tasks
from ...services.rbac_service import AUTH_ENTITIES, _USER_DEFAULTS
from ..factories import create_machine, create_user


def _count(session, model, *conditions) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(model).where(*conditions)
        ).scalar_one()
    )


def _add_expect_integrity_error(session, row) -> None:
    session.add(row)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def _create_image(*, name: str, owner_id: int, valid_range=ImageValidRange.CUSTOM) -> Image:
    image = Image(
        name=name,
        description=None,
        base_image="ubuntu:24.04",
        dockerfile_body="",
        status=ImageStatus.READY,
        created_by_user_id=owner_id,
        valid_range=valid_range,
    )
    # 用显式 session 写，调用方负责 commit
    return image


#####################
# backend--table-auth-group-entities


def test_auth_group_entity_pk_read_returns_stable_code(db_session):
    user_group = auth_repo.get_group("user", session=db_session)
    auth_repo.ensure_group_entity(user_group.id, "machine:view", session=db_session)
    db_session.commit()
    db_session.expunge_all()

    row = db_session.get(AuthGroupEntity, (user_group.id, "machine:view"))
    assert row is not None
    assert row.entity_code == "machine:view"
    assert db_session.get(AuthGroupEntity, (user_group.id, "机器查看")) is None
    db_session.expunge_all()

    _add_expect_integrity_error(
        db_session, AuthGroupEntity(group_id=user_group.id, entity_code="machine:view")
    )
    _add_expect_integrity_error(
        db_session, AuthGroupEntity(group_id=user_group.id, entity_code=null())
    )
    _add_expect_integrity_error(
        db_session, AuthGroupEntity(group_id=999999, entity_code="machine:view")
    )


def test_auth_group_entity_rows_cascade_on_group_delete(db_session):
    group = auth_repo.create_group("anvil_cascade_entity_group", "t", session=db_session)
    other = auth_repo.create_group("anvil_cascade_entity_other", "t", session=db_session)
    auth_repo.ensure_group_entity(group.id, "machine:view", session=db_session)
    auth_repo.ensure_group_entity(other.id, "container:create", session=db_session)
    db_session.commit()

    db_session.delete(group)
    db_session.commit()

    assert _count(db_session, AuthGroupEntity, AuthGroupEntity.group_id == group.id) == 0
    assert _count(db_session, AuthGroupEntity, AuthGroupEntity.group_id == other.id) == 1


def test_replace_group_entities_returns_catalog_order_not_request_order(db_session):
    group = auth_repo.create_group("anvil_catalog_order_group", "t", session=db_session)
    db_session.commit()

    result = rbac_service.update_group_entities(group.id, ["image:view", "machine:view"])

    assert result["entity_codes"] == ["machine:view", "image:view"]
    assert auth_repo.list_group_entity_codes(session=db_session)[group.id] == {
        "machine:view",
        "image:view",
    }


def test_group_entity_rows_store_codes_not_matrix_ordinals(db_session):
    group = auth_repo.create_group("anvil_code_not_ordinal_group", "t", session=db_session)
    db_session.commit()
    requested = ["machine:view", "image:view"]
    rbac_service.update_group_entities(group.id, requested)

    codes = auth_repo.list_group_entity_codes(session=db_session)[group.id]
    catalog = {code for code, _ in AUTH_ENTITIES}
    ordinals = {str(item["id"]) for item in rbac_service.list_rbac_matrix()["entities"]}

    assert codes == set(requested)
    assert codes <= catalog
    assert codes.isdisjoint(ordinals)


def test_clearing_operator_group_keeps_locked_entities(db_session):
    operator = auth_repo.get_group("operator", session=db_session)

    result = rbac_service.update_group_entities(operator.id, [])

    locked = {"bypass_resource", "bypass_auth_entity"}
    assert set(result["entity_codes"]) == locked
    assert set(result["locked_entity_codes"]) == locked
    assert auth_repo.list_group_entity_codes(session=db_session)[operator.id] == locked


#####################
# backend--table-auth-groups


def test_auth_group_pk_read_preserves_identity_and_nulls(db_session):
    group = AuthGroup(name="anvil_probe_group", description=None)
    db_session.add(group)
    db_session.commit()

    assert group.id is not None
    loaded = db_session.get(AuthGroup, group.id)
    assert loaded is not None
    assert loaded.name == "anvil_probe_group"
    assert loaded.description is None

    _add_expect_integrity_error(db_session, AuthGroup(name=null()))


def test_auth_group_name_unique_constraint_blocks_second_row(db_session):
    auth_repo.create_group("anvil_duplicate_group", "t", session=db_session)
    db_session.commit()

    db_session.add(AuthGroup(name="anvil_duplicate_group"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    assert (
        _count(db_session, AuthGroup, AuthGroup.name == "anvil_duplicate_group") == 1
    )


def test_seed_rbac_defaults_is_idempotent(db_session):
    rbac_service.seed_rbac_defaults()
    first = {
        name: auth_repo.get_group(name, session=db_session).id
        for name in ("user", "operator")
    }

    rbac_service.seed_rbac_defaults()
    second = {
        name: auth_repo.get_group(name, session=db_session).id
        for name in ("user", "operator")
    }

    assert first == second
    assert _count(db_session, AuthGroup, AuthGroup.name == "user") == 1
    assert _count(db_session, AuthGroup, AuthGroup.name == "operator") == 1
    duplicates = db_session.execute(
        select(
            AuthGroupEntity.group_id,
            AuthGroupEntity.entity_code,
            func.count().label("n"),
        )
        .group_by(AuthGroupEntity.group_id, AuthGroupEntity.entity_code)
        .having(func.count() > 1)
    ).all()
    assert duplicates == []


def test_replacing_group_entities_keeps_user_bindings_intact(db_session):
    user = create_user()
    group = auth_repo.create_group("anvil_binding_scope_group", "t", session=db_session)
    auth_repo.ensure_group_entity(group.id, "container:create", session=db_session)
    auth_repo.ensure_user_group(user.id, group.id, session=db_session)
    db_session.commit()

    before_links = {
        (row.user_id, row.group_id)
        for row in db_session.scalars(
            select(UserGroup).where(UserGroup.user_id == user.id)
        ).all()
    }
    before_ids = auth_repo.list_user_group_ids(user.id, session=db_session)

    auth_repo.replace_group_entities(group.id, {"machine:view"}, session=db_session)
    db_session.commit()

    after_links = {
        (row.user_id, row.group_id)
        for row in db_session.scalars(
            select(UserGroup).where(UserGroup.user_id == user.id)
        ).all()
    }
    assert auth_repo.list_user_group_ids(user.id, session=db_session) == before_ids
    assert after_links == before_links
    assert auth_repo.list_group_entity_codes(session=db_session)[group.id] == {"machine:view"}


#####################
# backend--table-user-groups


def test_user_group_composite_pk_read(db_session):
    user = create_user()
    group = auth_repo.create_group("anvil_user_group_pk_group", "t", session=db_session)
    db_session.commit()

    auth_repo.ensure_user_group(user.id, group.id, session=db_session)
    auth_repo.ensure_user_group(user.id, group.id, session=db_session)
    db_session.commit()
    db_session.expunge_all()

    row = db_session.get(UserGroup, (user.id, group.id))
    assert row is not None
    assert row.user_id == user.id
    assert row.group_id == group.id
    assert _count(db_session, UserGroup, UserGroup.user_id == user.id) == 1
    db_session.expunge_all()

    _add_expect_integrity_error(
        db_session, UserGroup(user_id=user.id, group_id=group.id)
    )
    _add_expect_integrity_error(
        db_session, UserGroup(user_id=null(), group_id=group.id)
    )
    _add_expect_integrity_error(
        db_session, UserGroup(user_id=user.id, group_id=999999)
    )


def test_user_group_rows_cascade_on_user_and_group_delete(db_session):
    user_a = create_user()
    user_b = create_user()
    group_a = auth_repo.create_group("anvil_ug_cascade_a", "t", session=db_session)
    group_b = auth_repo.create_group("anvil_ug_cascade_b", "t", session=db_session)
    for user, group in (
        (user_a, group_a),
        (user_a, group_b),
        (user_b, group_a),
        (user_b, group_b),
    ):
        auth_repo.ensure_user_group(user.id, group.id, session=db_session)
    db_session.commit()

    db_session.delete(user_a)
    db_session.commit()

    assert _count(db_session, UserGroup, UserGroup.user_id == user_a.id) == 0
    assert _count(db_session, UserGroup, UserGroup.user_id == user_b.id) == 2

    db_session.delete(group_a)
    db_session.commit()

    assert _count(db_session, UserGroup, UserGroup.group_id == group_a.id) == 0
    assert _count(db_session, UserGroup, UserGroup.user_id == user_b.id) == 1


def test_set_user_groups_dedupes_duplicate_group_ids(db_session):
    user = create_user()
    user_group = auth_repo.get_group("user", session=db_session)
    operator_group = auth_repo.get_group("operator", session=db_session)

    settled = rbac_service.set_user_groups(
        user.id,
        [user_group.id, operator_group.id, user_group.id, operator_group.id],
    )

    expected_ids = sorted([user_group.id, operator_group.id])
    assert settled == expected_ids
    assert auth_repo.list_user_group_ids(user.id, session=db_session) == expected_ids

    direct = auth_repo.list_group_entity_codes(session=db_session)
    union = direct[user_group.id] | direct[operator_group.id]
    expected_union = set(_USER_DEFAULTS) | {"bypass_resource", "bypass_auth_entity"}
    assert union == expected_union
    assert "container:create" in union
    assert "bypass_auth_entity" in union

    # operator 的 bypass_auth_entity 会让 list_user_entities 扩到全量；
    # 这里只做子集校验，不用 user_has_entity/list_user_entities 等值反证 user 组侧。
    assert union <= set(rbac_service.list_user_entities(user.id))


def test_unbound_user_falls_back_to_default_user_group(db_session):
    user = create_user()
    rbac_service.seed_rbac_defaults()

    assert auth_repo.list_user_group_ids(user.id, session=db_session) == []
    assert auth_repo.user_has_any_group(user.id, session=db_session) is False
    assert rbac_service.user_has_entity(user.id, "container:create") is True
    assert rbac_service.user_has_entity(user.id, "rbac:manage") is False

    operator = auth_repo.get_group("operator", session=db_session)
    auth_repo.ensure_user_group(user.id, operator.id, session=db_session)
    db_session.commit()

    assert auth_repo.user_has_any_group(user.id, session=db_session) is True
    assert rbac_service.user_has_entity(user.id, "bypass_auth_entity") is True

    db_session.execute(delete(UserGroup).where(UserGroup.user_id == user.id))
    db_session.commit()

    assert auth_repo.list_user_group_ids(user.id, session=db_session) == []
    assert auth_repo.user_has_any_group(user.id, session=db_session) is False
    assert rbac_service.user_has_entity(user.id, "container:create") is True
    assert rbac_service.user_has_entity(user.id, "rbac:manage") is False


#####################
# backend--table-machine-permissions


def test_machine_permission_pk_read_and_columns(db_session):
    machine = create_machine()
    user = create_user()
    record = machine_permission_repo.add_permission(machine.id, user.id, session=db_session)
    db_session.commit()

    assert record.id is not None
    loaded = db_session.get(MachinePermission, record.id)
    assert loaded is not None
    assert loaded.machine_id == machine.id
    assert loaded.user_id == user.id

    _add_expect_integrity_error(
        db_session, MachinePermission(machine_id=null(), user_id=user.id)
    )
    _add_expect_integrity_error(
        db_session, MachinePermission(machine_id=machine.id, user_id=null())
    )


def test_add_machine_permission_twice_keeps_single_pair(db_session):
    machine = create_machine()
    user = create_user()
    machine_permission_repo.add_permission(machine.id, user.id, session=db_session)
    machine_permission_repo.add_permission(machine.id, user.id, session=db_session)
    db_session.commit()

    assert (
        _count(
            db_session,
            MachinePermission,
            MachinePermission.machine_id == machine.id,
            MachinePermission.user_id == user.id,
        )
        == 1
    )
    assert machine_permission_repo.list_user_ids_by_machine(
        machine.id, session=db_session
    ) == [user.id]

    _add_expect_integrity_error(
        db_session, MachinePermission(machine_id=machine.id, user_id=user.id)
    )


def test_remove_machine_permission_immediately_denies_resource(db_session):
    machine = create_machine()
    user = create_user()

    assert rbac_service.user_has_resource(user.id, "machine", machine.id) is False

    machine_permission_repo.add_permission(machine.id, user.id, session=db_session)
    db_session.commit()
    assert rbac_service.user_has_resource(user.id, "machine", machine.id) is True

    machine_permission_repo.remove_permission(machine.id, user.id, session=db_session)
    db_session.commit()
    assert rbac_service.user_has_resource(user.id, "machine", machine.id) is False


def test_machine_permission_rows_cascade_on_machine_and_user_delete(db_session):
    machine_a = create_machine()
    machine_b = create_machine()
    machine_c = create_machine()
    user_a = create_user()
    user_b = create_user()
    user_c = create_user()
    for machine, user in ((machine_a, user_a), (machine_b, user_b), (machine_c, user_c)):
        machine_permission_repo.add_permission(machine.id, user.id, session=db_session)
    db_session.commit()

    db_session.delete(machine_a)
    db_session.commit()

    assert (
        _count(db_session, MachinePermission, MachinePermission.machine_id == machine_a.id)
        == 0
    )
    assert (
        _count(db_session, MachinePermission, MachinePermission.machine_id == machine_b.id)
        == 1
    )
    assert (
        _count(db_session, MachinePermission, MachinePermission.machine_id == machine_c.id)
        == 1
    )

    db_session.delete(user_b)
    db_session.commit()

    assert _count(db_session, MachinePermission, MachinePermission.user_id == user_b.id) == 0
    assert _count(db_session, MachinePermission, MachinePermission.user_id == user_c.id) == 1


#####################
# backend--table-user-images


def test_user_image_pk_read_and_granted_at(db_session):
    owner = create_user()
    viewer = create_user()
    image = _create_image(name="anvil_user_image_pk", owner_id=owner.id)
    db_session.add(image)
    db_session.commit()

    record = userimage_repo.grant_image(viewer.id, image.id, session=db_session)
    db_session.commit()

    assert record.id is not None
    loaded = db_session.get(UserImage, record.id)
    assert loaded is not None
    assert loaded.user_id == viewer.id
    assert loaded.image_id == image.id
    assert loaded.granted_at is not None

    _add_expect_integrity_error(
        db_session,
        UserImage(user_id=viewer.id, image_id=image.id, granted_at=null()),
    )
    _add_expect_integrity_error(
        db_session, UserImage(user_id=viewer.id, image_id=image.id)
    )


def test_user_image_rows_cascade_on_user_and_image_delete(db_session):
    owner = create_user()
    viewer = create_user()
    other = create_user()
    image_one = _create_image(name="anvil_user_image_cascade_one", owner_id=owner.id)
    image_two = _create_image(name="anvil_user_image_cascade_two", owner_id=owner.id)
    db_session.add_all([image_one, image_two])
    db_session.commit()

    userimage_repo.grant_image(viewer.id, image_one.id, session=db_session)
    userimage_repo.grant_image(other.id, image_one.id, session=db_session)
    userimage_repo.grant_image(other.id, image_two.id, session=db_session)
    db_session.commit()

    db_session.delete(viewer)
    db_session.commit()

    assert (
        _count(db_session, UserImage, UserImage.image_id == image_one.id) == 1
    )
    assert (
        _count(db_session, UserImage, UserImage.image_id == image_two.id) == 1
    )

    # 用 Core DELETE 绕开 ORM relationship 级联，直证 DB 的 ON DELETE CASCADE。
    db_session.execute(delete(Image).where(Image.id == image_two.id))
    db_session.commit()

    assert _count(db_session, UserImage, UserImage.image_id == image_two.id) == 0
    assert _count(db_session, UserImage, UserImage.image_id == image_one.id) == 1
    assert db_session.get(Image, image_one.id) is not None


def test_set_image_visible_users_dedupes_and_replaces(db_session):
    owner = create_user()
    first = create_user()
    second = create_user()
    granted = create_user()
    outsider = create_user()
    image = _create_image(name="anvil_visible_dedupe", owner_id=owner.id)
    everyone = _create_image(
        name="anvil_visible_everyone",
        owner_id=owner.id,
        valid_range=ImageValidRange.EVERYONE,
    )
    db_session.add_all([image, everyone])
    db_session.commit()

    settled = image_tasks.Set_image_visible_users(
        image_id=image.id,
        user_ids=[first.id, second.id, first.id],
    )
    assert settled == sorted([first.id, second.id])
    assert userimage_repo.list_user_ids_by_image(image.id, session=db_session) == sorted(
        [first.id, second.id]
    )

    replaced = image_tasks.Set_image_visible_users(
        image_id=image.id,
        user_ids=[second.id],
    )
    assert replaced == [second.id]
    assert userimage_repo.list_user_ids_by_image(image.id, session=db_session) == [
        second.id
    ]

    # everyone 态直接写入一行授权：名单存在，但未授权用户的列表/点判定仍按 everyone 成立。
    db_session.add(UserImage(user_id=granted.id, image_id=everyone.id))
    db_session.commit()
    scope = image_repo.ImageScope(
        unrestricted=False,
        viewer_user_id=outsider.id,
        granted_ids=frozenset(),
    )
    listed_ids = {
        img.id for img in image_repo.list_images(scope=scope, session=db_session)
    }
    assert everyone.id in listed_ids
    assert (
        image_repo.image_is_visible_to(
            everyone, viewer_user_id=outsider.id, granted=False
        )
        is True
    )
    assert rbac_service.user_has_resource(outsider.id, "image", everyone.id) is True


def test_granted_viewer_reads_original_owner(client, monkeypatch, db_session):
    from ...api import deps

    owner = create_user()
    granted = create_user()
    image = _create_image(name="anvil_granted_viewer", owner_id=owner.id)
    db_session.add(image)
    db_session.commit()
    before_owner = image_repo.get_by_id(image.id, session=db_session).created_by_user_id

    settled = image_tasks.Set_image_visible_users(
        image_id=image.id, user_ids=[granted.id]
    )
    assert settled == [granted.id]
    after_owner = image_repo.get_by_id(image.id, session=db_session).created_by_user_id
    assert before_owner == after_owner == owner.id
    assert rbac_service.user_has_resource(granted.id, "image:owner", image.id) is False

    monkeypatch.setattr(
        deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True
    )
    monkeypatch.setattr(
        deps.authentications_repo,
        "get_user_id_by_token",
        lambda token, **kwargs: granted.id,
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_entity",
        lambda uid, code: True,
    )

    resp = client.get(
        f"/api/images/get_image_detail_information?image_id={image.id}"
    )
    assert resp.status_code == 200
    assert resp.json()["image"]["created_by_user_id"] == owner.id


#####################
# backend--table-user-managed-users


def test_user_managed_user_pk_read_and_unique_pair(db_session):
    manager = create_user()
    student = create_user()
    row = UserManagedUser(manager_user_id=manager.id, managed_user_id=student.id)
    db_session.add(row)
    db_session.commit()

    assert row.id is not None
    loaded = db_session.get(UserManagedUser, row.id)
    assert loaded is not None
    assert loaded.manager_user_id == manager.id
    assert loaded.managed_user_id == student.id
    assert loaded.granted_at is not None

    _add_expect_integrity_error(
        db_session,
        UserManagedUser(manager_user_id=manager.id, managed_user_id=student.id),
    )

    other_manager = create_user()
    other_student = create_user()
    _add_expect_integrity_error(
        db_session,
        UserManagedUser(
            manager_user_id=null(),
            managed_user_id=other_student.id,
        ),
    )
    _add_expect_integrity_error(
        db_session,
        UserManagedUser(
            manager_user_id=other_manager.id,
            managed_user_id=null(),
        ),
    )
    _add_expect_integrity_error(
        db_session,
        UserManagedUser(
            manager_user_id=other_manager.id,
            managed_user_id=other_student.id,
            granted_at=null(),
        ),
    )


def test_list_managed_ids_and_user_scope_includes_self(db_session):
    manager = create_user()
    student = create_user()
    stranger = create_user()
    db_session.add(
        UserManagedUser(manager_user_id=manager.id, managed_user_id=student.id)
    )
    db_session.commit()

    assert user_managed_user_repo.list_managed_ids(
        manager_user_id=manager.id, session=db_session
    ) == {student.id}
    assert user_managed_user_repo.list_managed_ids(
        manager_user_id=stranger.id, session=db_session
    ) == set()

    visible = user_tasks.List_all_user_bref_information(
        page_number=1,
        page_size=10,
        viewer_user_id=manager.id,
    )
    visible_ids = {item.user_id for item in visible}
    assert visible_ids == {manager.id, student.id}
    assert student.id in visible_ids
    assert stranger.id not in visible_ids

    operator = create_user(operator=True)
    unrestricted = user_tasks.List_all_user_bref_information(
        page_number=1,
        page_size=10,
        viewer_user_id=operator.id,
    )
    unrestricted_ids = {item.user_id for item in unrestricted}
    assert {manager.id, student.id, stranger.id, operator.id} <= unrestricted_ids
