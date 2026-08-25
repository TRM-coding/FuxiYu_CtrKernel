from ...api import deps
from ...services import settings_tasks


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
