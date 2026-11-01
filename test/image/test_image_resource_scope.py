"""镜像资源范围与两层 RBAC 的一致回归（Q14）。

真实 RBAC 跑真实 FastAPI + 内存 SQLite：组绑定、user_has_entity、user_has_resource
全部走生产代码，只替身认证令牌与 Node 通信。矩阵覆盖：默认 operator / 直持
image:manage / 仅资源通配 + 方法权限 / 仅实体通配 / 普通创建者 / 授权查看者 /
完全无权限。

要点：资源通配（bypass_resource 或直持 image:manage）只扩**资源范围**，不凭空授予
方法权限；bypass_auth_entity 只放行方法级权限点，MUST NOT 被读成资源通配。
"""

from ...api import deps
from ...constant import ImageStatus, ImageValidRange
from ...extensions import session_scope
from ...repositories import auth_repo, userimage_repo
from ...services import image_tasks
from ...services.container_module import node_comms
from ...services.rbac_service import user_has_resource
from .. import mocks
from ..factories import create_auth, create_machine, create_user

SCENE_NAMES = {"scope-private", "scope-everyone", "scope-custom"}


def test_explicit_mine_filter_precedes_unrestricted_scope(db_session):
    from ...repositories import image_repo

    owner, other = create_user(), create_user()
    own_id = _make_image(name="explicit-own", owner=owner)
    other_id = _make_image(name="explicit-other", owner=other)
    scope = image_repo.ImageScope(True, owner.id, frozenset({other_id}), mine_only=True)
    rows = image_repo.list_images(scope=scope, session=db_session)
    assert [row.id for row in rows] == [own_id]
    assert image_repo.count_images(scope=scope, session=db_session) == 1


def _auth(monkeypatch, user_id: int) -> None:
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)


def _bind_entities(user, codes, *, group_name: str) -> None:
    with session_scope() as session:
        group = auth_repo.ensure_group(group_name, group_name, session=session)
        for code in codes:
            auth_repo.ensure_group_entity(group.id, code, session=session)
        auth_repo.ensure_user_group(user.id, group.id, session=session)


def _make_image(*, name, owner, valid_range=ImageValidRange.CUSTOM, status=ImageStatus.READY) -> int:
    image_id = image_tasks.Create_image(
        name=name,
        base_image="ubuntu:24.04",
        dockerfile_body="",
        status=status,
        operator_user_id=owner.id,
    )
    if valid_range != ImageValidRange.CUSTOM:
        assert image_tasks.Set_image_valid_range(
            image_id=image_id, valid_range=valid_range, operator_user_id=owner.id
        ) is True
    return image_id


def _list_response(client, monkeypatch, user_id, *, mine_only: bool = False):
    _auth(monkeypatch, user_id)
    suffix = "&mine_only=true" if mine_only else ""
    return client.get(f"/api/images/list_image_bref_information?page_size=100{suffix}")


def _scene() -> dict:
    """一套固定样本：owner 的三态模板 + 七种观众。"""
    owner = create_user()
    _bind_entities(owner, ("image:view", "image:edit"), group_name="img_scope_owner")
    granted = create_user()
    _bind_entities(granted, ("image:view", "image:edit"), group_name="img_scope_granted")
    viewer = create_user()
    _bind_entities(viewer, ("image:view",), group_name="img_scope_viewer")
    operator = create_user(operator=True)  # operator 组 = bypass_resource + bypass_auth_entity
    manager = create_user()
    _bind_entities(manager, ("image:manage",), group_name="img_scope_manager")
    wildcard = create_user()
    _bind_entities(
        wildcard, ("bypass_resource", "image:view", "image:edit"), group_name="img_scope_wildcard"
    )
    entity_only = create_user()
    _bind_entities(entity_only, ("bypass_auth_entity",), group_name="img_scope_entity_only")
    nobody = create_user()
    _bind_entities(nobody, (), group_name="img_scope_nobody")

    private_id = _make_image(name="scope-private", owner=owner, valid_range=ImageValidRange.PRIVATE)
    everyone_id = _make_image(name="scope-everyone", owner=owner, valid_range=ImageValidRange.EVERYONE)
    custom_id = _make_image(name="scope-custom", owner=owner)
    with session_scope() as session:
        userimage_repo.grant_image(granted.id, custom_id, session=session)

    return {
        "owner": owner,
        "granted": granted,
        "viewer": viewer,
        "operator": operator,
        "manager": manager,
        "wildcard": wildcard,
        "entity_only": entity_only,
        "nobody": nobody,
        "private_id": private_id,
        "everyone_id": everyone_id,
        "custom_id": custom_id,
    }


def test_default_list_scope_reflects_resource_wildcard(client, monkeypatch):
    """默认列表（不带 mine_only）的口径：资源通配看全部，实体通配不扩范围。"""
    s = _scene()
    all_scene = set(SCENE_NAMES)
    expectations = {
        "operator": all_scene,
        "manager": all_scene,
        "wildcard": all_scene,
        "owner": all_scene,
        "entity_only": {"scope-everyone"},
        "granted": {"scope-everyone", "scope-custom"},
        "viewer": {"scope-everyone"},
    }
    for key, expected in expectations.items():
        body = _list_response(client, monkeypatch, s[key].id).json()
        names = {item["name"] for item in body["images"]}
        assert names & SCENE_NAMES == expected, f"{key}: {sorted(names & SCENE_NAMES)}"
        assert body["total_number"] == len(body["images"]), f"{key}: 总数与列表必须同口径"

    # 完全无权限：方法门先挡，列表不可见（资源范围再宽也没用）
    denied = _list_response(client, monkeypatch, s["nobody"].id)
    assert denied.status_code == 403
    assert denied.json()["error_reason"] == "insufficient_permission"


def test_default_list_agrees_with_point_checks(client, monkeypatch):
    """默认列表（SQL 谓词）与点判定（资源门 + 建容器可用性）对同一组样本结论一致。"""
    s = _scene()
    scene = {
        "scope-private": s["private_id"],
        "scope-everyone": s["everyone_id"],
        "scope-custom": s["custom_id"],
    }
    for key in ("operator", "manager", "wildcard", "entity_only", "owner", "granted", "viewer"):
        user = s[key]
        names = {item["name"] for item in _list_response(client, monkeypatch, user.id).json()["images"]}
        for name, image_id in scene.items():
            listed = name in names
            usable = (
                image_tasks.Can_use_image_for_container(user.id, image_id)
                is image_tasks.ImageUsability.OK
            )
            accessible = user_has_resource(user.id, "image", image_id)
            assert listed == usable == accessible, (
                f"{key}/{name}: 列表={listed} 建容器={usable} 资源门={accessible}"
            )


def test_mine_only_is_strictly_owned_and_wildcard_does_not_leak(client, monkeypatch):
    """「仅看我的」严格 created_by_user_id == 当前用户：授权与通配都不算"我的"。"""
    s = _scene()

    # 通配者/实体通配者都没建过样本里的模板 → 这一栏为空（内置模板也不是他建的）
    for key in ("operator", "manager", "wildcard", "entity_only"):
        body = _list_response(client, monkeypatch, s[key].id, mine_only=True).json()
        assert not {item["name"] for item in body["images"]} & SCENE_NAMES, key
        assert body["total_number"] == 0, key

    # 创建者被移出自己的 custom 名单后，凭 created_by 仍留在这一栏
    assert image_tasks.Set_image_visible_users(
        image_id=s["custom_id"], user_ids=[s["granted"].id], operator_user_id=s["owner"].id
    ) == [s["granted"].id]
    owner_names = {
        item["name"]
        for item in _list_response(client, monkeypatch, s["owner"].id, mine_only=True).json()["images"]
    }
    assert owner_names & SCENE_NAMES == SCENE_NAMES

    # 授权 ≠ 所有权：被授权者在这一栏看不到别人建的模板
    granted_names = {
        item["name"]
        for item in _list_response(client, monkeypatch, s["granted"].id, mine_only=True).json()["images"]
    }
    assert not granted_names & SCENE_NAMES, "user_images 授权只决定 CUSTOM 可见性，不得混进 mine_only"


def test_my_permissions_exposes_real_image_resource_wildcard(client, monkeypatch):
    """me/permissions 直接给资源级通配的真实判定，前端不必从 entities 派生集反推。"""
    s = _scene()
    combo = create_user()
    _bind_entities(
        combo, ("image:manage", "bypass_auth_entity"), group_name="img_scope_direct_combo"
    )

    users = {
        "operator": s["operator"],
        "manager": s["manager"],
        "wildcard": s["wildcard"],
        "combo": combo,
        "entity_only": s["entity_only"],
        "owner": s["owner"],
        "granted": s["granted"],
        "nobody": s["nobody"],
    }
    expected = {
        "operator": True,
        "manager": True,
        "wildcard": True,
        "combo": True,
        "entity_only": False,
        "owner": False,
        "granted": False,
        "nobody": False,
    }
    for key, want in expected.items():
        _auth(monkeypatch, users[key].id)
        body = client.get("/api/users/me/permissions").json()
        assert body["image_resource_unrestricted"] is want, key

    # 生效集里都有 image:manage，但两者结论相反——证明这一位不能从 entities 推出来
    _auth(monkeypatch, users["entity_only"].id)
    body = client.get("/api/users/me/permissions").json()
    assert "image:manage" in body["entities"]
    assert body["image_resource_unrestricted"] is False

    _auth(monkeypatch, users["combo"].id)
    body = client.get("/api/users/me/permissions").json()
    assert "image:manage" in body["entities"]
    assert body["image_resource_unrestricted"] is True


def test_direct_manage_with_entity_wildcard_keeps_full_resource_range(client, monkeypatch):
    """直持 image:manage + 方法通配：资源范围仍是全量（只看 entities 会误判为否）。"""
    combo = create_user()
    _bind_entities(
        combo, ("image:manage", "bypass_auth_entity"), group_name="img_scope_combo_range"
    )
    owner = create_user()
    private_id = _make_image(name="combo-private", owner=owner, valid_range=ImageValidRange.PRIVATE)
    everyone_id = _make_image(name="combo-everyone", owner=owner, valid_range=ImageValidRange.EVERYONE)

    names = {
        item["name"] for item in _list_response(client, monkeypatch, combo.id).json()["images"]
    }
    assert {"combo-private", "combo-everyone"} <= names
    assert user_has_resource(combo.id, "image", private_id) is True

    _auth(monkeypatch, combo.id)
    assert client.get(
        f"/api/images/get_image_detail_information?image_id={private_id}"
    ).status_code == 200
    assert client.post(
        "/api/images/update_image", json={"image_id": private_id, "description": "combo"}
    ).status_code == 200
    assert client.post(
        "/api/images/set_image_valid_range",
        json={"image_id": private_id, "valid_range": "private"},
    ).status_code == 200


def test_resource_wildcard_without_edit_cannot_edit_or_read_detail(client, monkeypatch):
    """有资源通配但没有 image:edit：列表看全部，完整详情与编辑仍被方法门挡住。"""
    user = create_user()
    _bind_entities(
        user, ("bypass_resource", "image:view"), group_name="img_scope_wild_view_only"
    )
    owner = create_user()
    private_id = _make_image(name="viewonly-private", owner=owner, valid_range=ImageValidRange.PRIVATE)

    names = {
        item["name"] for item in _list_response(client, monkeypatch, user.id).json()["images"]
    }
    assert "viewonly-private" in names, "资源通配者应当能列出全部"

    _auth(monkeypatch, user.id)
    detail = client.get(f"/api/images/get_image_detail_information?image_id={private_id}")
    assert detail.status_code == 403
    assert detail.json()["error_reason"] == "insufficient_permission"
    update = client.post(
        "/api/images/update_image", json={"image_id": private_id, "description": "no"}
    )
    assert update.status_code == 403
    assert update.json()["error_reason"] == "insufficient_permission"

    # 资源通配 + READY 仍可用来建容器（可用性判定不受方法门影响）
    assert image_tasks.Can_use_image_for_container(
        user.id, private_id
    ) is image_tasks.ImageUsability.OK


def test_edit_and_visibility_entrances_need_resource_wildcard(client, monkeypatch):
    """编辑与两个可见性入口：方法权限 + 资源范围都要过，实体通配不扩资源。"""
    s = _scene()
    target = s["private_id"]

    for key in ("operator", "manager", "wildcard", "owner"):
        _auth(monkeypatch, s[key].id)
        updated = client.post(
            "/api/images/update_image",
            json={"image_id": target, "description": f"edited-by-{key}"},
        )
        assert updated.status_code == 200, key
        ranged = client.post(
            "/api/images/set_image_valid_range",
            json={"image_id": target, "valid_range": "private"},
        )
        assert ranged.status_code == 200, key

    # entity_only/granted 有方法权限（image:edit），但资源范围不含别人的 private → 资源门 403
    for key, reason in (("entity_only", "resource_access_denied"), ("granted", "resource_access_denied")):
        _auth(monkeypatch, s[key].id)
        resp = client.post("/api/images/update_image", json={"image_id": target, "description": "no"})
        assert resp.status_code == 403, key
        assert resp.json()["error_reason"] == reason, key
    # viewer/nobody 连方法权限都没有 → 方法门 403
    for key in ("viewer", "nobody"):
        _auth(monkeypatch, s[key].id)
        resp = client.post("/api/images/update_image", json={"image_id": target, "description": "no"})
        assert resp.status_code == 403, key
        assert resp.json()["error_reason"] == "insufficient_permission", key


def test_detail_requires_image_edit_method_and_resource_visibility(client, monkeypatch):
    """完整详情是方法门（image:edit）+ 资源门的交集，两个方向都要锁。"""
    s = _scene()

    for key in ("operator", "manager", "wildcard", "owner"):
        _auth(monkeypatch, s[key].id)
        resp = client.get(f"/api/images/get_image_detail_information?image_id={s['private_id']}")
        assert resp.status_code == 200, key
        assert resp.json()["image"]["dockerfile_body"] == ""

    # 仅实体通配：方法够、资源不够 → 403（这条正是"实体通配不是资源通配"的证据）
    _auth(monkeypatch, s["entity_only"].id)
    assert client.get(
        f"/api/images/get_image_detail_information?image_id={s['private_id']}"
    ).status_code == 403
    # 同一个实体通配者在 everyone 模板上读得到
    assert client.get(
        f"/api/images/get_image_detail_information?image_id={s['everyone_id']}"
    ).status_code == 200

    # 只有 image:view：即便模板对他可见，完整详情也不开放
    _auth(monkeypatch, s["viewer"].id)
    resp = client.get(f"/api/images/get_image_detail_information?image_id={s['everyone_id']}")
    assert resp.status_code == 403
    assert resp.json()["error_reason"] == "insufficient_permission"

    # 授权查看者：被授权的 custom 读得到，别人的 private 读不到
    _auth(monkeypatch, s["granted"].id)
    assert client.get(
        f"/api/images/get_image_detail_information?image_id={s['custom_id']}"
    ).status_code == 200
    assert client.get(
        f"/api/images/get_image_detail_information?image_id={s['private_id']}"
    ).status_code == 403


def test_container_image_usability_follows_scope_and_ready_gate(client, monkeypatch):
    """创建容器的镜像判定与列表同口径；停用/草稿的状态门不被资源通配绕过。"""
    s = _scene()

    assert image_tasks.Can_use_image_for_container(
        s["operator"].id, s["private_id"]
    ) is image_tasks.ImageUsability.OK
    assert image_tasks.Can_use_image_for_container(
        s["wildcard"].id, s["private_id"]
    ) is image_tasks.ImageUsability.OK
    assert image_tasks.Can_use_image_for_container(
        s["manager"].id, s["private_id"]
    ) is image_tasks.ImageUsability.OK
    assert image_tasks.Can_use_image_for_container(
        s["entity_only"].id, s["private_id"]
    ) is image_tasks.ImageUsability.DENIED
    assert image_tasks.Can_use_image_for_container(
        s["entity_only"].id, s["everyone_id"]
    ) is image_tasks.ImageUsability.OK
    assert image_tasks.Can_use_image_for_container(
        s["granted"].id, s["custom_id"]
    ) is image_tasks.ImageUsability.OK
    assert image_tasks.Can_use_image_for_container(
        s["granted"].id, s["private_id"]
    ) is image_tasks.ImageUsability.DENIED
    assert image_tasks.Can_use_image_for_container(
        s["nobody"].id, s["private_id"]
    ) is image_tasks.ImageUsability.DENIED

    draft_id = _make_image(name="scope-draft", owner=s["owner"], status=ImageStatus.DRAFT)
    disabled_id = _make_image(name="scope-disabled", owner=s["owner"])
    assert image_tasks.Delete_image(image_id=disabled_id, operator_user_id=s["owner"].id) is True
    for key in ("operator", "manager", "wildcard", "owner"):
        assert image_tasks.Can_use_image_for_container(
            s[key].id, draft_id
        ) is image_tasks.ImageUsability.DISABLED, key
        assert image_tasks.Can_use_image_for_container(
            s[key].id, disabled_id
        ) is image_tasks.ImageUsability.DISABLED, key
    assert image_tasks.Can_use_image_for_container(
        s["operator"].id, 999999
    ) is image_tasks.ImageUsability.NOT_FOUND


def test_operator_full_chain_list_detail_edit_and_container(client, monkeypatch, db_session):
    """默认 operator 的完整链路：默认列表 → 完整详情 → 编辑他人 → 用它建容器。"""
    operator = create_user(operator=True)
    owner = create_user()
    private_id = _make_image(name="chain-private", owner=owner, valid_range=ImageValidRange.PRIVATE)
    machine = create_machine()
    create_auth(operator, token="op-chain-token")
    client.cookies.set("auth_token", "op-chain-token")
    mocks.mock_node_response(monkeypatch, node_comms, {"success": 1})

    listed = client.get("/api/images/list_image_bref_information?page_size=100")
    assert listed.status_code == 200
    assert "chain-private" in {item["name"] for item in listed.json()["images"]}

    detail = client.get(f"/api/images/get_image_detail_information?image_id={private_id}")
    assert detail.status_code == 200
    assert detail.json()["image"]["created_by_user_id"] == owner.id

    edited = client.post(
        "/api/images/update_image",
        json={"image_id": private_id, "description": "operator edited"},
    )
    assert edited.status_code == 200
    # 所有权不可转让：资源通配能改内容，但 created_by 不因编辑而改变
    after = client.get(f"/api/images/get_image_detail_information?image_id={private_id}").json()
    assert after["image"]["created_by_user_id"] == owner.id

    created = client.post(
        "/api/containers/create_container",
        json={
            "machine_id": machine.id,
            "image_id": private_id,
            "container": {
                "GPU_LIST": [],
                "CPU_NUMBER": 2,
                "MEMORY": 8,
                "SHARED_MEM": 2,
                "NAME": "op_chain_container",
            },
        },
    )
    assert created.status_code == 200

    # 状态门不被通配绕过：草稿不可用于新建容器
    draft_id = _make_image(name="chain-draft", owner=owner, status=ImageStatus.DRAFT)
    denied = client.post(
        "/api/containers/create_container",
        json={
            "machine_id": machine.id,
            "image_id": draft_id,
            "container": {
                "GPU_LIST": [],
                "CPU_NUMBER": 2,
                "MEMORY": 8,
                "SHARED_MEM": 2,
                "NAME": "op_chain_draft",
            },
        },
    )
    assert denied.status_code == 400
    assert denied.json()["error_reason"] == "image_not_ready"

    # 已停用同理
    disabled_id = _make_image(name="chain-disabled", owner=owner)
    assert image_tasks.Delete_image(image_id=disabled_id, operator_user_id=owner.id) is True
    disabled = client.post(
        "/api/containers/create_container",
        json={
            "machine_id": machine.id,
            "image_id": disabled_id,
            "container": {
                "GPU_LIST": [],
                "CPU_NUMBER": 2,
                "MEMORY": 8,
                "SHARED_MEM": 2,
                "NAME": "op_chain_disabled",
            },
        },
    )
    assert disabled.status_code == 400
    assert disabled.json()["error_reason"] == "image_not_ready"


def test_entity_wildcard_only_has_no_image_resource_range(client, monkeypatch):
    """仅实体通配：方法级全开，但镜像资源范围仍是三态——默认列表与资源门一致。"""
    user = create_user()
    _bind_entities(user, ("bypass_auth_entity",), group_name="img_entity_only_scope")
    owner = create_user()
    private_id = _make_image(name="entity-private", owner=owner, valid_range=ImageValidRange.PRIVATE)
    everyone_id = _make_image(name="entity-everyone", owner=owner, valid_range=ImageValidRange.EVERYONE)

    names = {
        item["name"]
        for item in _list_response(client, monkeypatch, user.id).json()["images"]
        if item["name"].startswith("entity-")
    }
    assert names == {"entity-everyone"}
    assert user_has_resource(user.id, "image", everyone_id) is True
    assert user_has_resource(user.id, "image", private_id) is False

    # 直持 image:manage 的对照：同一份样本下它就是资源通配
    manager = create_user()
    _bind_entities(manager, ("image:manage",), group_name="img_entity_scope_manager")
    manager_names = {
        item["name"]
        for item in _list_response(client, monkeypatch, manager.id).json()["images"]
        if item["name"].startswith("entity-")
    }
    assert manager_names == {"entity-everyone", "entity-private"}
