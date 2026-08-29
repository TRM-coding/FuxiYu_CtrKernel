from ...api import deps
from ... import _ensure_image_template_schema
from ... import extensions
from sqlalchemy import inspect, text


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
    assert {"base_image", "dockerfile_body", "pre_build", "status", "created_by_user_id"} <= columns

    from ...services.image_tasks import seed_image_defaults

    seed_image_defaults()
    resp = client.get("/api/images/list_image_bref_information?page_number=1&page_size=100")
    assert resp.status_code == 200
    assert resp.json()["total_number"] >= 1


def test_create_image_success(client, monkeypatch):
    _auth(monkeypatch, user_id=7)

    resp = client.post(
        "/api/images/create_image",
        json={
            "name": "pytorch-cuda",
            "description": "PyTorch CUDA",
            "base_image": "ubuntu:24.04",
            "dockerfile_body": "RUN pip install torch\n",
            "pre_build": "#!/bin/sh\n",
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
    assert img["name"] == "Ubuntu 22.04 · 基础"
    assert img["status"] == "ready"

    detail = client.get(f"/api/images/get_image_detail_information?image_id={img['image_id']}").json()
    assert detail["image"]["base_image"] == "ubuntu:22.04"
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
    assert "Ubuntu 22.04 · 基础" in names
    assert "private-img" not in names
