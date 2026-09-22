import pytest

from ...api import deps
from ... import _ensure_image_template_schema
from ... import extensions
from ...constant import ImageStatus
from ...extensions import session_scope
from ...models.image import Image
from ...repositories import userimage_repo
from ..factories import SessionRegistry, create_user
from sqlalchemy import inspect, text

pytestmark = pytest.mark.usefixtures("ensure_auth_users")


def _auth(monkeypatch, *, user_id=1, entity=True, resource=True):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: entity)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, kind, rid: resource)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service._has_resource_manage_direct", lambda uid, kind: True)


def test_create_image_requires_auth(client, monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: False)

    resp = client.post("/api/images/create_image", json={"name": "img", "base_image": "ubuntu:24.04"})

    assert resp.status_code == 401


def test_legacy_image_table_is_upgraded_before_list(client, monkeypatch):
    """旧开发库 images 表缺新列时，启动期补列后列表接口不应 500。"""
    _auth(monkeypatch, user_id=7)
    with extensions.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS user_images"))
        conn.execute(text("DROP TABLE IF EXISTS images"))
        conn.execute(text("CREATE TABLE images (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL UNIQUE, description VARCHAR(500) NULL)"))

    _ensure_image_template_schema()
    columns = {column["name"] for column in inspect(extensions.engine).get_columns("images")}
    assert {"base_image", "dockerfile_body", "status", "created_by_user_id", "valid_range"} <= columns

    from ...services.image_tasks import seed_image_defaults

    seed_image_defaults()
    resp = client.get("/api/images/list_image_bref_information?page_number=1&page_size=100")
    assert resp.status_code == 200
    assert resp.json()["total_number"] >= 1


def test_legacy_images_unique_name_index_is_relaxed(client, monkeypatch):
    """旧库 images.name 是唯一索引时，启动自愈应降为普通索引（唯一性移交应用层）。"""
    _auth(monkeypatch, user_id=7)
    with extensions.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS user_images"))
        conn.execute(text("DROP TABLE IF EXISTS images"))
        conn.execute(text(
            "CREATE TABLE images ("
            "id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL,"
            "description VARCHAR(500) NULL, base_image VARCHAR(255) NOT NULL,"
            "dockerfile_body TEXT NOT NULL, status VARCHAR(8) NOT NULL,"
            "created_by_user_id INTEGER NULL, created_at DATETIME NOT NULL,"
            "updated_at DATETIME NOT NULL)"
        ))
        conn.execute(text("CREATE UNIQUE INDEX ix_images_name ON images(name)"))

    _ensure_image_template_schema()
    indexes = {idx["name"]: idx for idx in inspect(extensions.engine).get_indexes("images")}
    assert not indexes["ix_images_name"]["unique"]  # SQLite 报 0，MySQL 报 False，都当假值


def test_legacy_images_table_backfills_valid_range_once(client, monkeypatch):
    """旧库自愈：加 valid_range 列，并按**旧语义**回填存量行（系统行 → everyone）。

    这一步不做，`created_by IS NULL` 的存量内置模板会从所有普通用户眼前消失——
    因为"公开"自 2026-09 起只看 valid_range。

    ★ 回填以"列刚被加出来"为闸门，**只生效一次**：管理员之后故意把系统模板设成 custom，
      重启不该把它翻回 everyone（那是"自愈"变成"覆盖人工设置"的经典事故）。
    """
    _auth(monkeypatch, user_id=7)
    with extensions.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS user_images"))
        conn.execute(text("DROP TABLE IF EXISTS images"))
        # 旧表：没有 valid_range，也还没有 created_by_user_id
        conn.execute(text(
            "CREATE TABLE images ("
            "id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL,"
            "description VARCHAR(500) NULL, base_image VARCHAR(255) NOT NULL,"
            "dockerfile_body TEXT NOT NULL, status VARCHAR(8) NOT NULL,"
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO images (id, name, base_image, dockerfile_body, status, created_at, updated_at)"
            " VALUES (1, 'legacy-system', 'ubuntu:24.04', '', 'ready',"
            " '2026-09-01 00:00:00', '2026-09-01 00:00:00')"
        ))

    _ensure_image_template_schema()

    columns = {column["name"] for column in inspect(extensions.engine).get_columns("images")}
    assert "valid_range" in columns
    with extensions.engine.begin() as conn:
        # 该行没有 created_by_user_id（加列后为 NULL）→ 旧语义下是"系统内置、全员可见"
        assert conn.execute(
            text("SELECT valid_range FROM images WHERE id = 1")
        ).scalar() == "everyone"

    # 人工把它设成 custom，再自愈一次：必须保持 custom
    with extensions.engine.begin() as conn:
        conn.execute(text("UPDATE images SET valid_range = 'custom' WHERE id = 1"))
    _ensure_image_template_schema()
    with extensions.engine.begin() as conn:
        assert conn.execute(
            text("SELECT valid_range FROM images WHERE id = 1")
        ).scalar() == "custom", "列已存在时不得再回填，否则每次启动都会覆盖管理员设置"


def test_create_image_success(client, monkeypatch):
    _auth(monkeypatch, user_id=7)

    resp = client.post(
        "/api/images/create_image",
        json={
            "name": "pytorch-cuda",
            "description": "PyTorch CUDA",
            "base_image": "ubuntu:24.04",
            "dockerfile_body": "RUN pip install torch\n",
        },
    )

    assert resp.status_code == 201
    assert resp.json()["success"] == 1
    assert resp.json()["image_id"] > 0


def test_list_and_detail_image(client, monkeypatch):
    _auth(monkeypatch, user_id=7)
    created = client.post(
        "/api/images/create_image",
        json={"name": "cuda-base", "base_image": "ubuntu:24.04", "dockerfile_body": "RUN pip install torch\n"},
    ).json()

    list_resp = client.get("/api/images/list_image_bref_information?image_search=cuda")
    detail_resp = client.get(f"/api/images/get_image_detail_information?image_id={created['image_id']}")

    assert list_resp.status_code == 200
    assert list_resp.json()["total_number"] == 1
    assert detail_resp.status_code == 200
    assert detail_resp.json()["image"]["base_image"] == "ubuntu:24.04"
    assert detail_resp.json()["image"]["dockerfile_body"] == "RUN pip install torch\n"


def test_update_and_delete_image(client, monkeypatch):
    _auth(monkeypatch, user_id=7)
    image_id = client.post(
        "/api/images/create_image",
        json={"name": "base", "base_image": "ubuntu:22.04", "dockerfile_body": "RUN echo hello\n"},
    ).json()["image_id"]

    update_resp = client.post(
        "/api/images/update_image",
        json={
            "image_id": image_id,
            "name": "base-v2",
            "base_image": "ubuntu:24.04",
            "dockerfile_body": "RUN echo updated\n",
            "status": "ready",
        },
    )
    detail_resp = client.get(f"/api/images/get_image_detail_information?image_id={image_id}")
    delete_resp = client.post("/api/images/delete_image", json={"image_id": image_id})

    assert update_resp.status_code == 200
    assert detail_resp.json()["image"]["name"] == "base-v2"
    assert detail_resp.json()["image"]["status"] == "ready"
    assert detail_resp.json()["image"]["base_image"] == "ubuntu:24.04"
    assert detail_resp.json()["image"]["dockerfile_body"] == "RUN echo updated\n"
    assert delete_resp.status_code == 200


def test_create_image_persists_entrypoint(client, monkeypatch):
    """create 必须把 entrypoint 转发到 service。

    回归锁：schema 收、service 存，但 create 端点一度漏了转发这一根线——
    前端填了 entrypoint 会被**静默丢掉**，详情读回来还是空的（2026-09 实测）。
    """
    _auth(monkeypatch, user_id=7)

    created = client.post(
        "/api/images/create_image",
        json={
            "name": "jenkins",
            "base_image": "jenkins/jenkins:2.516.2",
            "dockerfile_body": "RUN echo hi\n",
            "entrypoint": "jenkins.sh",
        },
    ).json()
    detail = client.get(f"/api/images/get_image_detail_information?image_id={created['image_id']}").json()

    assert detail["image"]["entrypoint"] == "jenkins.sh"


def test_entrypoint_empty_string_clears_null_keeps(client, monkeypatch):
    """空串 = 清除（回到平台默认）；null 到不了 service（update 走 exclude_none），值不变。

    这是前端依赖的线上契约：清空功能只能靠发空串实现，发 null 等于什么都不改。
    """
    _auth(monkeypatch, user_id=7)
    image_id = client.post(
        "/api/images/create_image",
        json={
            "name": "entry-contract",
            "base_image": "ubuntu:24.04",
            "dockerfile_body": "",
            "entrypoint": "my-entrypoint",
        },
    ).json()["image_id"]

    def read_entrypoint():
        resp = client.get(f"/api/images/get_image_detail_information?image_id={image_id}")
        return resp.json()["image"]["entrypoint"]

    client.post("/api/images/update_image", json={"image_id": image_id, "entrypoint": None})
    assert read_entrypoint() == "my-entrypoint"

    client.post("/api/images/update_image", json={"image_id": image_id, "entrypoint": ""})
    assert read_entrypoint() is None


def test_seed_image_defaults_idempotent(client, monkeypatch):
    """内置镜像 seed 幂等：重复调用不产生重复行，内容直存 DB 可读。"""
    _auth(monkeypatch, user_id=7)
    from ...services.image_tasks import seed_image_defaults

    # db_session 已种过一次；再跑两遍都应只产生一行
    seed_image_defaults()
    seed_image_defaults()

    body = client.get("/api/images/list_image_bref_information?image_search=Ubuntu").json()
    assert body["total_number"] == 1
    img = body["images"][0]
    assert img["name"] == "Ubuntu 24.04 · 基础"
    assert img["status"] == "ready"

    detail = client.get(f"/api/images/get_image_detail_information?image_id={img['image_id']}").json()
    assert detail["image"]["base_image"] == "ubuntu:24.04"
    assert detail["image"]["dockerfile_body"] == ""


def test_seed_skips_existing_name(client, monkeypatch):
    """同名已存在（人工修改过内容）时不覆盖。"""
    _auth(monkeypatch, user_id=7)
    # 对预种的内置镜像改内容，模拟人工自定义
    pre = client.get("/api/images/list_image_bref_information?image_search=Ubuntu").json()
    seed_id = pre["images"][0]["image_id"]
    client.post(
        "/api/images/update_image",
        json={"image_id": seed_id, "base_image": "custom:1", "dockerfile_body": "RUN echo custom\n"},
    )

    from ...services.image_tasks import seed_image_defaults
    seed_image_defaults()

    body = client.get("/api/images/list_image_bref_information?image_search=Ubuntu").json()
    assert body["total_number"] == 1
    detail = client.get(f"/api/images/get_image_detail_information?image_id={body['images'][0]['image_id']}").json()
    assert detail["image"]["base_image"] == "custom:1"
    assert "custom" in detail["image"]["dockerfile_body"]


def test_system_image_visible_to_normal_user(client, monkeypatch):
    """系统内置镜像（created_by IS NULL）全员可见；他人私有镜像不可见。"""
    _auth(monkeypatch, user_id=7)
    client.post(
        "/api/images/create_image",
        json={"name": "private-img", "base_image": "ubuntu:24.04", "dockerfile_body": ""},
    )

    # 普通用户视角：无 image 资源通配
    _auth(monkeypatch, user_id=3)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service._has_resource_manage_direct", lambda uid, kind: False)

    body = client.get("/api/images/list_image_bref_information?page_size=50").json()
    names = [img["name"] for img in body["images"]]
    assert "Ubuntu 24.04 · 基础" in names
    assert "private-img" not in names


def test_normal_user_cannot_detail_system_image(client, monkeypatch):
    """内置模板可用于列表选择与建容器，但**完整 Dockerfile 读不到**。

    ★ 反批量抓取的防线落在 **entity 那一层**（详情要 image:edit，而 image:edit 默认只在
      运维组里），不在资源层——资源层（`require_resource("image")`）管的是"哪些模板"，
      内置模板是 everyone，对谁都放行。所以这里的拦截来自 require_permission。
    """
    _auth_as(monkeypatch, 3, entities=_VIEWER)  # 普通用户：有 image:view，没有 image:edit

    listed = client.get("/api/images/list_image_bref_information?image_search=Ubuntu").json()
    assert listed["total_number"] >= 1
    image_id = listed["images"][0]["image_id"]

    resp = client.get(f"/api/images/get_image_detail_information?image_id={image_id}")
    assert resp.status_code == 403


def test_mine_only_list_uses_user_image_binding_not_created_by(client, monkeypatch):
    """编辑页“只看我的”按 user_images 资源绑定，不按 created_by_user_id 派生。"""
    editor = create_user()
    _auth(monkeypatch, user_id=7)
    image_id = client.post(
        "/api/images/create_image",
        json={"name": "shared-to-editor", "base_image": "ubuntu:24.04", "dockerfile_body": ""},
    ).json()["image_id"]

    with session_scope() as session:
        userimage_repo.grant_image(editor.id, image_id, session=session)

    _auth(monkeypatch, user_id=editor.id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service._has_resource_manage_direct", lambda uid, kind: False)

    body = client.get("/api/images/list_image_bref_information?mine_only=true&page_size=50").json()
    images = {item["name"]: item for item in body["images"]}
    assert "shared-to-editor" in images
    assert images["shared-to-editor"]["created_by_user_id"] == 7
    assert "Ubuntu 24.04 · 基础" not in images


def test_update_other_private_image_still_denied_without_resource(client, monkeypatch):
    """写路径归属闸保留：非创建者（无 manage 通配）改他人模板仍 403。

    2026-09 起这条闸的口径是 `image:owner`（created_by == 自己），不再是"有没有授权行"——
    见 test_update_requires_ownership_not_just_visibility。
    """
    _auth(monkeypatch, user_id=7)
    image_id = client.post(
        "/api/images/create_image",
        json={"name": "owner-private", "base_image": "ubuntu:24.04", "dockerfile_body": ""},
    ).json()["image_id"]

    # 另一用户：有 image:edit（entity=True），但无 user_images 授权行、无 image:manage 通配
    _auth(monkeypatch, user_id=3)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service._has_resource_manage_direct", lambda uid, kind: False)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, kind, rid: False)

    resp = client.post(
        "/api/images/update_image",
        json={"image_id": image_id, "name": "hacked", "base_image": "ubuntu:24.04"},
    )
    assert resp.status_code == 403
    assert resp.json()["error_reason"] == "resource_access_denied"


# ── 可见范围三态（2026-09 决策） ──────────────────────────────────────────
#
# 这一组**不桩 user_has_resource**：口径本身就是要测的东西，桩掉等于什么都没测。
# 只桩 entity（方法级权限）与通配，资源判定走生产代码。


def _auth_as(monkeypatch, user_id, *, entities=(), manage=False):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_entity",
        lambda uid, code: code in set(entities),
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service._has_resource_manage_direct",
        lambda uid, kind: manage,
    )


_EDITOR = ("image:edit",)
_VIEWER = ("image:view",)


def _make_template(client, monkeypatch, *, name, owner_id, valid_range=None) -> int:
    """以 owner 身份建模板（建完即回切可见范围，不传则保持默认 custom）。"""
    _auth_as(monkeypatch, owner_id, entities=_EDITOR)
    image_id = client.post(
        "/api/images/create_image",
        json={"name": name, "base_image": "ubuntu:24.04", "dockerfile_body": ""},
    ).json()["image_id"]
    if valid_range is not None:
        resp = client.post(
            "/api/images/set_image_valid_range",
            json={"image_id": image_id, "valid_range": valid_range},
        )
        assert resp.status_code == 200
    return image_id


def _list_names(client, monkeypatch, user_id) -> set[str]:
    _auth_as(monkeypatch, user_id, entities=_VIEWER)
    body = client.get("/api/images/list_image_bref_information?page_size=100").json()
    return {item["name"] for item in body["images"]}


def _grant(user_id: int, image_id: int) -> None:
    with session_scope() as session:
        userimage_repo.grant_image(user_id, image_id, session=session)


def test_visibility_matrix(client, monkeypatch):
    """三态 × 三种观众：private 不看名单、everyone 全员、custom 只认名单。"""
    owner, other, granted = create_user(), create_user(), create_user()
    private_id = _make_template(client, monkeypatch, name="vr-private", owner_id=owner.id, valid_range="private")
    _make_template(client, monkeypatch, name="vr-everyone", owner_id=owner.id, valid_range="everyone")
    custom_id = _make_template(client, monkeypatch, name="vr-custom", owner_id=owner.id)
    # 给 private 也发一张授权：它**不该**因此变得可见（private 不看名单）
    _grant(granted.id, private_id)
    _grant(granted.id, custom_id)

    owner_names = _list_names(client, monkeypatch, owner.id)
    assert {"vr-private", "vr-everyone", "vr-custom"} <= owner_names, "自己建的三态都看得见"

    granted_names = _list_names(client, monkeypatch, granted.id)
    assert "vr-everyone" in granted_names
    assert "vr-custom" in granted_names, "custom 名单里的人看得见"
    assert "vr-private" not in granted_names, "★ private 有授权行也不可见"

    other_names = _list_names(client, monkeypatch, other.id)
    assert "vr-everyone" in other_names
    assert "vr-private" not in other_names
    assert "vr-custom" not in other_names


def test_created_by_null_no_longer_means_public(client, monkeypatch):
    """★ 旧语义的墓碑：created_by IS NULL 自 2026-09 起**不再**派生出"公开"。

    （迁移把存量系统行回填成 everyone，所以线上行为不变；但新建的行必须显式写这一列。）
    """
    viewer = create_user()
    image = Image(
        name="vr-legacy-system-row",
        description=None,
        base_image="ubuntu:24.04",
        dockerfile_body="",
        status=ImageStatus.READY,
        created_by_user_id=None,  # ← 旧语义下这就等于"全员可见"
    )
    SessionRegistry.add(image)
    SessionRegistry.commit()

    assert "vr-legacy-system-row" not in _list_names(client, monkeypatch, viewer.id)


def test_detail_requires_image_edit_even_when_visible(client, monkeypatch):
    """详情是"读完整 Dockerfile"的**能力闸**：只有 image:view 的用户即便看得见也读不到。"""
    owner = create_user()
    image_id = _make_template(client, monkeypatch, name="vr-detail", owner_id=owner.id, valid_range="everyone")
    _grant(owner.id, image_id)  # 连授权行都给上

    _auth_as(monkeypatch, owner.id, entities=_VIEWER)  # 有 view、无 edit
    resp = client.get(f"/api/images/get_image_detail_information?image_id={image_id}")
    assert resp.status_code == 403

    _auth_as(monkeypatch, owner.id, entities=_EDITOR)
    assert client.get(f"/api/images/get_image_detail_information?image_id={image_id}").status_code == 200


def test_update_requires_ownership_not_just_visibility(client, monkeypatch):
    """编辑只能动**自己建的**：有 image:edit + 模板对他可见，仍然改不了别人的。"""
    owner, editor = create_user(), create_user()
    image_id = _make_template(client, monkeypatch, name="vr-owner-only", owner_id=owner.id, valid_range="everyone")
    _grant(editor.id, image_id)

    _auth_as(monkeypatch, editor.id, entities=_EDITOR)
    denied = client.post(
        "/api/images/update_image", json={"image_id": image_id, "name": "hijacked"}
    )
    assert denied.status_code == 403
    assert denied.json()["error_reason"] == "resource_access_denied"

    _auth_as(monkeypatch, owner.id, entities=_EDITOR)
    allowed = client.post(
        "/api/images/update_image", json={"image_id": image_id, "name": "renamed-by-owner"}
    )
    assert allowed.status_code == 200


def test_set_visible_users_rejected_outside_custom(client, monkeypatch):
    """★ 非 custom 态下改名单**一律拒绝**：名单生不生效由 valid_range 决定，
    允许改等于让人改一个看不到效果的东西。"""
    owner, someone = create_user(), create_user()
    image_id = _make_template(client, monkeypatch, name="vr-not-custom", owner_id=owner.id, valid_range="everyone")

    _auth_as(monkeypatch, owner.id, entities=_EDITOR)
    resp = client.post(
        "/api/images/set_image_visible_users",
        json={"image_id": image_id, "user_ids": [someone.id]},
    )
    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "not_custom_range"


def test_switching_range_keeps_the_grant_list(client, monkeypatch):
    """★ 切态不删名单：切到 everyone 再切回 custom，名单原样还在。"""
    owner, granted = create_user(), create_user()
    image_id = _make_template(client, monkeypatch, name="vr-keep-list", owner_id=owner.id)
    _auth_as(monkeypatch, owner.id, entities=_EDITOR)
    set_users = client.post(
        "/api/images/set_image_visible_users",
        json={"image_id": image_id, "user_ids": [granted.id]},
    )
    assert set_users.status_code == 200 and set_users.json()["user_ids"] == [granted.id]

    for step in ("everyone", "custom"):
        assert client.post(
            "/api/images/set_image_valid_range",
            json={"image_id": image_id, "valid_range": step},
        ).status_code == 200

    detail = client.get(f"/api/images/get_image_detail_information?image_id={image_id}").json()
    assert detail["image"]["valid_range"] == "custom"
    assert detail["image"]["visible_user_ids"] == [granted.id], "名单在切态往返后仍然保留"


def test_visible_user_ids_only_exposed_for_custom(client, monkeypatch):
    """非 custom 态不回显名单：它存着但不生效，回显会画出与现实不符的勾选状态。"""
    owner, granted = create_user(), create_user()
    image_id = _make_template(client, monkeypatch, name="vr-no-echo", owner_id=owner.id)
    _auth_as(monkeypatch, owner.id, entities=_EDITOR)
    client.post("/api/images/set_image_visible_users", json={"image_id": image_id, "user_ids": [granted.id]})
    client.post("/api/images/set_image_valid_range", json={"image_id": image_id, "valid_range": "private"})

    detail = client.get(f"/api/images/get_image_detail_information?image_id={image_id}").json()
    assert detail["image"]["valid_range"] == "private"
    assert detail["image"].get("visible_user_ids") is None


def test_set_visible_users_rejects_unknown_user(client, monkeypatch):
    owner = create_user()
    image_id = _make_template(client, monkeypatch, name="vr-unknown", owner_id=owner.id)

    _auth_as(monkeypatch, owner.id, entities=_EDITOR)
    resp = client.post(
        "/api/images/set_image_visible_users",
        json={"image_id": image_id, "user_ids": [99999999]},
    )
    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "unknown_user"


def test_set_valid_range_rejects_junk_value(client, monkeypatch):
    owner = create_user()
    image_id = _make_template(client, monkeypatch, name="vr-junk", owner_id=owner.id)

    _auth_as(monkeypatch, owner.id, entities=_EDITOR)
    resp = client.post(
        "/api/images/set_image_valid_range",
        json={"image_id": image_id, "valid_range": "friends-only"},
    )
    # schema 的 Literal 先挡一层；应用把 RequestValidationError 统一折成 400/invalid_payload
    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_payload"


def test_mine_only_ignores_everyone(client, monkeypatch):
    """编辑页"只看我的"只认授权行：EVERYONE 但没授权的模板不该出现在里面。"""
    owner, viewer = create_user(), create_user()
    _make_template(client, monkeypatch, name="vr-mine-everyone", owner_id=owner.id, valid_range="everyone")

    _auth_as(monkeypatch, viewer.id, entities=_VIEWER)
    body = client.get("/api/images/list_image_bref_information?mine_only=true&page_size=100").json()
    assert "vr-mine-everyone" not in {item["name"] for item in body["images"]}
    assert body["total_number"] == 0, "总数必须与列表同口径"


def test_point_check_agrees_with_list_predicate(db_session):
    """★ 一条规则两个消费者：列表谓词（SQL）与点判定（Python）对同一组样本必须同结论。

    两处分叉的后果是"列表看得见、建容器被拒"或反过来——在页面上表现为随机 403。
    """
    from ...constant import ImageValidRange
    from ...repositories import image_repo
    from ...models.userimage import UserImage

    owner, viewer = create_user(), create_user()
    rows = []
    for name, valid_range, created_by in (
        ("p-private", ImageValidRange.PRIVATE, owner.id),
        ("p-everyone", ImageValidRange.EVERYONE, owner.id),
        ("p-custom-granted", ImageValidRange.CUSTOM, owner.id),
        ("p-custom-other", ImageValidRange.CUSTOM, owner.id),
    ):
        image = Image(
            name=name, description=None, base_image="ubuntu:24.04", dockerfile_body="",
            status=ImageStatus.READY, created_by_user_id=created_by, valid_range=valid_range,
        )
        SessionRegistry.add(image)
        rows.append(image)
    SessionRegistry.commit()
    db_session.add(UserImage(user_id=viewer.id, image_id=rows[2].id))
    db_session.commit()

    for viewer_id, granted in ((viewer.id, True), (None, False)):
        scope = image_repo.ImageScope(
            unrestricted=False,
            viewer_user_id=viewer_id,
            granted_ids=frozenset(r.id for r in rows if r.name == "p-custom-granted") if granted else frozenset(),
        )
        listed_ids = {img.id for img in image_repo.list_images(scope=scope, session=db_session)}
        for image in rows:
            point = image_repo.image_is_visible_to(
                image, viewer_user_id=viewer_id, granted=image.id in scope.granted_ids
            )
            assert (image.id in listed_ids) == point, f"{image.name}: SQL 与点判定分叉了"


def test_create_image_status_roundtrip(client, monkeypatch):
    """创建即带状态：不传 status → 草稿；显式传 ready → 一步到位（无需二次编辑）。"""
    _auth(monkeypatch, user_id=7)

    draft_id = client.post(
        "/api/images/create_image",
        json={"name": "draft-on-create", "base_image": "ubuntu:24.04"},
    ).json()["image_id"]
    resp = client.get(f"/api/images/get_image_detail_information?image_id={draft_id}")
    assert resp.status_code == 200
    assert resp.json()["image"]["status"] == "draft"

    ready_id = client.post(
        "/api/images/create_image",
        json={"name": "ready-on-create", "base_image": "ubuntu:24.04", "status": "ready"},
    ).json()["image_id"]
    resp2 = client.get(f"/api/images/get_image_detail_information?image_id={ready_id}")
    assert resp2.status_code == 200
    assert resp2.json()["image"]["status"] == "ready"
