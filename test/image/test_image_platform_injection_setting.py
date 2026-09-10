import pytest

from ...api import deps
from ...models.operation_log import OperationLog
from ...services import settings_tasks
from sqlalchemy import select

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
    log = db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "update_setting")
    ).one()
    assert log.detail["before"][settings_tasks.IMAGE_PLATFORM_INJECTION_KEY]
    assert log.detail["after"][settings_tasks.IMAGE_PLATFORM_INJECTION_KEY] == custom
    assert settings_tasks.IMAGE_PLATFORM_INJECTION_KEY in log.detail["setting_keys"]


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


def test_system_settings_api_update_roundtrip(client, db_session, monkeypatch):
    _auth(monkeypatch, user_id=7)

    resp = client.post(
        "/api/settings",
        json={"values": {"container.cleanup_after_days": 12, "container.disk_check_enabled": True}},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert settings_tasks.get_container_cleanup_after_days() == 12
    assert settings_tasks.get_container_disk_check_enabled() is True
    log = db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "update_setting")
    ).one()
    assert log.detail["after"] == {
        "container.cleanup_after_days": 12,
        "container.disk_check_enabled": True,
    }
    assert log.target_id == 0


@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("key,value", [
    ("container.disk_check_enabled", "maybe"),
    ("container.cleanup_after_days", "invalid-number"),
])
def test_rejected_setting_audit_preserves_input(db_session, single, key, value):
    before = settings_tasks.get_setting_value(key)
    with pytest.raises(ValueError):
        if single:
            settings_tasks.set_setting_value(key, value)
        else:
            settings_tasks.update_settings({key: value})
    log = db_session.scalars(select(OperationLog)).one()
    assert log.success is False
    assert log.detail["requested"] == {key: value}
    assert "after" not in log.detail
    assert key in log.detail["before"]
    assert log.detail["setting_keys"] == [key]
    assert settings_tasks.get_setting_value(key) == before


def test_settings_batch_target_is_order_independent(db_session):
    values = {"container.cleanup_after_days": 10, "container.disk_check_enabled": True}
    settings_tasks.update_settings(values)
    settings_tasks.update_settings(dict(reversed(list(values.items()))))
    logs = db_session.scalars(select(OperationLog).order_by(OperationLog.id)).all()
    assert [log.target_id for log in logs] == [0, 0]
    assert logs[0].detail["setting_keys"] == logs[1].detail["setting_keys"]
    settings_tasks.update_settings({"container.cleanup_after_days": 11})
    log = db_session.scalars(select(OperationLog).order_by(OperationLog.id.desc())).first()
    assert log.target_id > 0


def test_settings_rollback_has_no_applied_after(db_session, monkeypatch):
    repo = settings_tasks.system_setting_repo
    update = repo.update_setting
    before = settings_tasks.get_setting_value("container.cleanup_after_days")
    values = {"container.cleanup_after_days": 10, "container.disk_check_enabled": True}

    def fail_second(key, **kwargs):
        if key == "container.disk_check_enabled":
            raise RuntimeError("write failed")
        return update(key, **kwargs)

    monkeypatch.setattr(repo, "update_setting", fail_second)
    with pytest.raises(RuntimeError, match="write failed"):
        settings_tasks.update_settings(values)
    assert settings_tasks.get_setting_value("container.cleanup_after_days") == before
    log = db_session.scalars(select(OperationLog)).one()
    assert log.target_id == 0
    assert log.detail["requested"] == values
    assert "after" not in log.detail


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
