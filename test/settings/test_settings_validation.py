"""系统设置输入校验：后端必须拒绝会被静默截断或丢弃的输入。"""

import pytest
from sqlalchemy import select

from ...api import deps
from ...models.operation_log import OperationLog
from ...services import settings_tasks


pytestmark = pytest.mark.usefixtures("ensure_auth_users")

INTEGER_KEY = "container.cleanup_after_days"
REMINDER_KEY = settings_tasks.CLEANUP_REMINDER_HOURS_KEY


def _auth(monkeypatch, *, user_id=7):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)


@pytest.mark.parametrize("value", [1.5, "1.5", True, "abc", ""])
def test_integer_setting_rejects_non_integer_without_writing(db_session, value):
    before = settings_tasks.get_setting_value(INTEGER_KEY)

    with pytest.raises(ValueError, match=r"container\.cleanup_after_days must be an integer"):
        settings_tasks.update_settings({INTEGER_KEY: value})

    assert settings_tasks.get_setting_value(INTEGER_KEY) == before
    log = db_session.scalars(select(OperationLog)).one()
    assert log.success is False
    assert "must be an integer" in log.error_reason
    assert log.detail["requested"] == {INTEGER_KEY: value}


def test_integer_setting_accepts_integral_number(db_session):
    settings_tasks.update_settings({INTEGER_KEY: 12.0})

    assert settings_tasks.get_setting_value(INTEGER_KEY) == "12"


def test_single_setting_entrypoint_also_rejects_fractional_integer(db_session):
    before = settings_tasks.get_setting_value(INTEGER_KEY)

    with pytest.raises(ValueError, match=r"container\.cleanup_after_days must be an integer"):
        settings_tasks.set_setting_value(INTEGER_KEY, 1.5)

    assert settings_tasks.get_setting_value(INTEGER_KEY) == before


@pytest.mark.parametrize("value", [
    "",
    " ",
    "72,bad,24",
    "72,,24",
    "0,24",
    "-1,24",
    "12.5",
])
def test_reminder_hours_rejects_malformed_input_without_writing(db_session, value):
    before = settings_tasks.get_setting_value(REMINDER_KEY)

    with pytest.raises(ValueError, match=r"container\.cleanup_reminder_hours"):
        settings_tasks.update_settings({REMINDER_KEY: value})

    assert settings_tasks.get_setting_value(REMINDER_KEY) == before
    log = db_session.scalars(select(OperationLog)).one()
    assert log.success is False
    assert log.detail["requested"] == {REMINDER_KEY: value}


def test_reminder_hours_accepts_positive_values_and_stays_parser_compatible(db_session):
    settings_tasks.update_settings({REMINDER_KEY: "72, 24,12"})

    assert settings_tasks.get_setting_value(REMINDER_KEY) == "72, 24,12"

    from ...schedulers.container_cleanup_task import _parse_reminder_hours

    assert _parse_reminder_hours(settings_tasks.get_container_cleanup_reminder_hours()) == [72, 24, 12]


def test_settings_api_rejects_fractional_integer(client, monkeypatch):
    _auth(monkeypatch)
    before = settings_tasks.get_setting_value(INTEGER_KEY)

    resp = client.post("/api/settings", json={"values": {INTEGER_KEY: 1.25}})

    assert resp.status_code == 422
    body = resp.json()
    assert body["error_reason"] == "invalid_setting"
    assert INTEGER_KEY in body["message"]
    assert "must be an integer" in body["message"]
    assert settings_tasks.get_setting_value(INTEGER_KEY) == before


def test_settings_api_rejects_malformed_reminder_hours(client, monkeypatch):
    _auth(monkeypatch)
    before = settings_tasks.get_setting_value(REMINDER_KEY)

    resp = client.post("/api/settings", json={"values": {REMINDER_KEY: "72,bad,24"}})

    assert resp.status_code == 422
    body = resp.json()
    assert body["error_reason"] == "invalid_setting"
    assert REMINDER_KEY in body["message"]
    assert "'bad'" in body["message"]
    assert settings_tasks.get_setting_value(REMINDER_KEY) == before
