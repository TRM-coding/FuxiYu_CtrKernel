import pytest

from ...api import deps
from ...services import settings_tasks

pytestmark = pytest.mark.usefixtures("ensure_auth_users")


def _auth(monkeypatch, *, user_id=1, entity=True):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: entity)


def test_platform_injection_setting_is_seeded(db_session):
    value = settings_tasks.get_image_platform_injection_content()

    assert "openssh-server" in value
    assert "EXPOSE 22" in value
    assert "ssh-keygen -A" not in value


def test_platform_injection_setting_can_be_updated(db_session):
    custom = "USER root\nRUN echo fuxi\nEXPOSE 22"

    settings_tasks.set_setting_value(settings_tasks.IMAGE_PLATFORM_INJECTION_KEY, custom)

    assert settings_tasks.get_image_platform_injection_content() == custom


def test_platform_injection_setting_api_roundtrip(client, monkeypatch):
    _auth(monkeypatch, user_id=7)
    custom = "USER root\nRUN echo settings\nEXPOSE 22"

    update_resp = client.post(
        "/api/settings/image_platform_injection",
        json={"content": custom},
    )
    get_resp = client.get("/api/settings/image_platform_injection")

    assert update_resp.status_code == 200
    assert update_resp.json()["success"] == 1
    assert get_resp.status_code == 200
    assert get_resp.json()["content"] == custom


def test_system_settings_matrix_is_seeded(db_session):
    settings = {item["key"]: item for item in settings_tasks.list_settings()}

    assert "container.cleanup_after_days" in settings
    assert "container.cleanup_interval_seconds" in settings
    assert "container.disk_soft_limit_percent" in settings
    assert "announcement.batch_send_max" in settings
    assert settings[settings_tasks.IMAGE_PLATFORM_INJECTION_KEY]["multiline"] is True


def test_system_settings_seed_removes_deprecated_parallel_keys(db_session):
    from ...repositories import system_setting_repo

    with db_session() as session:
        system_setting_repo.create_setting(
            key="node.parallel_enabled_containers",
            value="true",
            description="deprecated",
            session=session,
        )
        session.commit()

    settings_tasks.seed_system_settings_defaults()

    settings = {item["key"]: item for item in settings_tasks.list_settings()}
    assert "node.parallel_enabled_containers" not in settings
    with db_session() as session:
        assert system_setting_repo.get_by_key("node.parallel_enabled_containers", session=session) is None


def test_system_settings_api_update_roundtrip(client, monkeypatch):
    _auth(monkeypatch, user_id=7)

    resp = client.post(
        "/api/settings",
        json={"values": {"container.cleanup_after_days": 12, "container.disk_check_enabled": True}},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert settings_tasks.get_container_cleanup_after_days() == 12
    assert settings_tasks.get_container_disk_check_enabled() is True


def test_system_settings_api_rejects_unknown_key(client, monkeypatch):
    _auth(monkeypatch, user_id=7)

    resp = client.post("/api/settings", json={"values": {"unknown.setting": "x"}})

    assert resp.status_code == 422
    assert resp.json()["error_reason"] == "invalid_setting"


def test_build_payload_includes_platform_injection(client, monkeypatch):
    _auth(monkeypatch, user_id=7)
    image_resp = client.post(
        "/api/images/create_image",
        json={
            "name": "build-template",
            "description": "template for container build",
            "base_image": "ubuntu:24.04",
            "dockerfile_body": "RUN echo hello\n",
        },
    )
    image_id = image_resp.json()["image_id"]

    from ...services.image_tasks import build_image_payload

    payload = build_image_payload(image_id)

    assert payload is not None
    assert payload["image_tag"].startswith(f"fuxi/image-{image_id}:")
    assert "FROM ubuntu:24.04" in payload["dockerfile_text"]
    assert "openssh-server" in payload["dockerfile_text"]
    assert "RUN echo hello" in payload["dockerfile_text"]


def test_image_build_tag_uses_second_level_utc_timestamp():
    from datetime import datetime, timezone, timedelta

    from ...services.image_tasks import format_image_build_tag

    updated_at = datetime(2026, 8, 29, 12, 34, 56, 789123, tzinfo=timezone(timedelta(hours=8)))

    assert format_image_build_tag(7, updated_at) == "fuxi/image-7:20260829T043456Z"
