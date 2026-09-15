from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone

from ...constant import ImageStatus, MachineStatus
from ...extensions import SessionRegistry
from ...api import container_api, deps
from ...models.image import Image
from ...services import container_tasks
from ...services.image_tasks import DockerfileParts, ImageBuild, ImageUsability as _ImageUsability
from ..factories import create_machine


def _fake_image_build(image_id: int, tag: str | None = None) -> ImageBuild:
    """构造一次构建的完整留痕（payload + 版本戳 + 配方）。"""
    parts = DockerfileParts(
        base_image="ubuntu:22.04", platform_injection="", dockerfile_body="RUN echo hello",
    )
    return ImageBuild(
        payload={
            "image_tag": tag or f"fuxi/image-{image_id}:20260826T000000Z",
            "dockerfile_text": parts.render(),
        },
        image_id=image_id,
        version_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        dockerfile_parts=parts,
    )


def _auth(monkeypatch, *, valid=True, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: valid)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.repositories.containers_repo.get_machine_id_by_container_id",
        lambda cid, session: 1,
    )


def test_create_container_api_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)

    resp = client.post("/api/containers/create_container", json={})

    assert resp.status_code == 401


def test_create_container_api_rejects_invalid_payload(client, monkeypatch):
    _auth(monkeypatch)

    resp = client.post(
        "/api/containers/create_container",
        json={"machine_id": 1, "image_id": 1, "container": {"CPU_NUMBER": "bad"}}
    )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_payload"


def test_create_container_api_duplicate_returns_409(client, monkeypatch):
    _auth(monkeypatch)
    err = IntegrityError("duplicate", params=None, orig="duplicate")
    monkeypatch.setattr(container_api.container_service, "Create_container", lambda **kwargs: (_ for _ in ()).throw(err))

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "image_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c"}}
    )

    assert resp.status_code == 409


def test_create_container_api_machine_permission_denied_returns_403(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(**kwargs):
        raise container_tasks.NodeServiceError("denied", reason="machine_permission_denied")

    monkeypatch.setattr(container_api.container_service, "Create_container", _raise)

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "image_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c"}}
    )

    assert resp.status_code == 403


def test_create_container_api_rejects_owner_without_machine_access(client, monkeypatch):
    """代建者有能力但 owner 对该机器无权限 → 403（API 边界门禁）。"""
    _auth(monkeypatch)
    # 依赖层(uid=1)机器校验放行；owner(uid=2)对该机器无权限
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_resource",
        lambda uid, rtype, rid: uid == 1,
    )
    monkeypatch.setattr(container_api.container_service, "Create_container", lambda **kwargs: True)

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "image_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c"}}
    )

    assert resp.status_code == 403
    assert resp.json()["error_reason"] == "machine_permission_denied"


def test_create_container_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "Create_container", lambda **kwargs: True)

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "image_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c"}}
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1


def test_create_container_for_another_requires_manage(client, monkeypatch):
    """普通用户(无 container:manage)代建他人容器 → 403（API 边界门禁）。"""
    _auth(monkeypatch)
    # 模拟普通 user 组：除 container:manage 外全放行
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_entity",
        lambda uid, code: code != "container:manage",
    )
    monkeypatch.setattr(container_api.container_service, "Create_container", lambda **kwargs: True)

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "image_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c"}}
    )

    assert resp.status_code == 403
    assert resp.json()["error_reason"] == "insufficient_permission"


def test_create_container_without_owner_creates_for_self(client, monkeypatch):
    """不传 owner_user_id → 主体归一为当前用户自己。"""
    _auth(monkeypatch)
    captured = {}
    def _fake_create(**kwargs):
        captured.update(kwargs)
        return True
    monkeypatch.setattr(container_api.container_service, "Create_container", _fake_create)

    resp = client.post(
        "/api/containers/create_container",
        json={"machine_id": 1, "image_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c"}}
    )

    assert resp.status_code == 200
    assert captured["owner_user_id"] == 1


def test_create_container_blank_owner_creates_for_self(client, monkeypatch):
    """owner_user_id 为空字符串也视为未传，避免前端空选择导致 422。"""
    _auth(monkeypatch)
    captured = {}

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(container_api.container_service, "Create_container", _fake_create)

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": "", "machine_id": 1, "image_id": 1, "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c"}}
    )

    assert resp.status_code == 200
    assert captured["owner_user_id"] == 1


def test_create_container_with_image_id_builds_payload(client, monkeypatch):
    _auth(monkeypatch)
    build = _fake_image_build(7)
    captured = {}

    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.image_tasks.resolve_image_build",
        lambda image_id: build if image_id == 7 else None,
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.image_tasks.Can_use_image_for_container",
        lambda uid, image_id: _ImageUsability.OK,
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_resource",
        lambda uid, rtype, rid: True,
    )

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(container_api.container_service, "Create_container", _fake_create)

    resp = client.post(
        "/api/containers/create_container",
        json={
            "owner_user_id": 2,
            "machine_id": 1,
            "image_id": 7,
            "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c"},
        },
    )

    assert resp.status_code == 200
    assert captured["image_build"] == build.payload
    assert captured["container"].image == build.payload["image_tag"]
    # 构建留痕随创建一起落库：版本戳用于判定"是否落后"，配方用于展示与精确还原
    assert captured["image_id"] == 7
    assert captured["image_version_at"] == build.version_at
    assert captured["dockerfile_parts"] == build.dockerfile_parts


def test_create_container_with_system_image_does_not_require_user_image_binding(client, monkeypatch):
    _auth(monkeypatch)
    image = Image(
        name="system-image-for-container",
        description="system image",
        base_image="ubuntu:22.04",
        dockerfile_body="",
        status=ImageStatus.READY,
        created_by_user_id=None,
    )
    SessionRegistry.add(image)
    SessionRegistry.commit()

    build = _fake_image_build(int(image.id))
    captured = {}

    def _resource_check(uid, rtype, rid):
        return rtype == "machine"

    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", _resource_check)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.image_tasks.resolve_image_build",
        lambda image_id: build if image_id == image.id else None,
    )
    monkeypatch.setattr(container_api.container_service, "Create_container", lambda **kwargs: captured.update(kwargs) or True)

    resp = client.post(
        "/api/containers/create_container",
        json={
            "machine_id": 1,
            "image_id": image.id,
            "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c"},
        },
    )

    assert resp.status_code == 200
    assert captured["image_build"] == build.payload
    assert captured["container"].image == build.payload["image_tag"]


def test_delete_container_api_not_found_returns_404(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(**kwargs):
        raise container_tasks.NodeServiceError("missing", reason="not_found")

    monkeypatch.setattr(container_api.container_service, "remove_container", _raise)

    resp = client.post("/api/containers/delete_container", json={"container_id": 1} )

    assert resp.status_code == 404


def test_delete_container_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "remove_container", lambda **kwargs: True)

    resp = client.post("/api/containers/delete_container", json={"container_id": 1} )

    assert resp.status_code == 200


def test_start_stop_restart_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(container_api.container_service, "start_container", lambda **kwargs: True)
    monkeypatch.setattr(container_api.container_service, "stop_container", lambda **kwargs: True)
    monkeypatch.setattr(container_api.container_service, "restart_container", lambda **kwargs: True)

    for endpoint in ("start_container", "stop_container", "restart_container"):
        resp = client.post(f"/api/containers/{endpoint}", json={"container_id": 1} )
        assert resp.status_code == 200


############################################################
# 机器准入族的 reason → 状态码（创建路径独有的一族）
############################################################

def _create_payload(machine_id):
    return {
        "machine_id": machine_id,
        "image_id": 1,
        "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c"},
    }


def test_create_container_api_maps_maintenance_to_503(client, monkeypatch, db_session):
    """维护中的机器：动作被拦（既有），且**回 503 而非 500**。

    创建路径没有容器、派生不出有效状态，撞的是**机器准入族**
    （machine_access._ensure_machine_online_for_operation 的 machine_maintenance），
    与动作类路径的 container_host_maintenance 不是同一个 reason——后者在映射表里，
    前者曾经没有，于是维护中创建容器会回 500，用户看到「服务器出现错误」。
    """
    _auth(monkeypatch)
    machine = create_machine(machine_name="api_maint", is_maintenance=True)

    resp = client.post("/api/containers/create_container", json=_create_payload(machine.id))

    assert resp.status_code == 503
    assert resp.json()["error_reason"] == "machine_maintenance"


def test_create_container_api_maps_offline_to_503(client, monkeypatch, db_session):
    _auth(monkeypatch)
    machine = create_machine(machine_name="api_offline", machine_status=MachineStatus.OFFLINE)

    resp = client.post("/api/containers/create_container", json=_create_payload(machine.id))

    assert resp.status_code == 503
    assert resp.json()["error_reason"] == "machine_offline"


def test_create_container_api_maps_missing_machine_to_404(client, monkeypatch, db_session):
    _auth(monkeypatch)

    resp = client.post("/api/containers/create_container", json=_create_payload(999999))

    assert resp.status_code == 404
    assert resp.json()["error_reason"] == "machine_not_found"
